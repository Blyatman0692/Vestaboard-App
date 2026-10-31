from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
import math
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests
from redis.exceptions import ConnectionError as RedisConnectionError, LockNotOwnedError

from redis_data_store import RedisDataStore
from vestaboard.board_message import BoardMessage
from vestaboard.board_state import BoardState
from vestaboard.display_manager import DisplayManager
from vestaboard.message_queue import RedisMessageQueue
from vestaboard.queued_message import QueuedMessage
from vestaboard.run_display_worker import DisplayWorker
from vestaboard.vestaboard import VestaboardMessenger


class Clock:
    now = 0.0

    def sleep(self, duration_s):
        self.now += duration_s


class MemoryRedis:
    """Minimal Redis test double with shared FIFO, expiring keys, and leases."""

    def __init__(self, clock):
        self.clock = clock
        self.pending = deque()
        self.values = {}
        self.hashes = {}
        self.leases = {}
        self.mutex = Lock()

    def rpush(self, key, payload):
        with self.mutex:
            self.pending.append(payload)

    def blpop(self, keys, timeout):
        with self.mutex:
            return (keys[0], self.pending.popleft()) if self.pending else None

    def set(self, key, value, px):
        self.values[key] = self.clock.now + px / 1000

    def pttl(self, key):
        deadline = self.values.get(key)
        if deadline is None or deadline <= self.clock.now:
            return -2
        return math.ceil((deadline - self.clock.now) * 1000)

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def hset(self, name, mapping):
        self.hashes[name] = mapping.copy()

    def lock(self, key, timeout):
        return MemoryLease(self, key, timeout)


class MemoryLease:
    def __init__(self, client, key, timeout):
        self.client, self.key, self.timeout = client, key, timeout

    def acquire(self, blocking):
        with self.client.mutex:
            owner, deadline = self.client.leases.get(self.key, (None, 0))
            if owner is not None and deadline > self.client.clock.now:
                return False
            self.client.leases[self.key] = (self, self.client.clock.now + self.timeout)
            return True

    def _check_owner(self):
        owner, deadline = self.client.leases.get(self.key, (None, 0))
        if owner is not self or deadline <= self.client.clock.now:
            raise LockNotOwnedError("Lease expired or belongs to another worker")

    def extend(self, timeout, replace_ttl):
        with self.client.mutex:
            self._check_owner()
            self.client.leases[self.key] = (self, self.client.clock.now + timeout)

    def release(self):
        with self.client.mutex:
            self._check_owner()
            del self.client.leases[self.key]


def response(status=200, body=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body or {"status": "ok"}).encode()
    result.headers.update(headers or {})
    return result


class DisplayWorkerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.redis = MemoryRedis(self.clock)
        self.writes = []
        self.outcomes = deque()
        self.on_content_write = None
        for target, replacement in (
            ("vestaboard.run_display_worker.time.monotonic", lambda: self.clock.now),
            ("vestaboard.run_display_worker.time.sleep", self.clock.sleep),
            ("vestaboard.vestaboard.random.uniform", lambda *_: 0),
        ):
            patcher = patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.board = self.make_board()
        self.worker = DisplayWorker(self.board)

    def make_board(self):
        store = RedisDataStore.__new__(RedisDataStore)
        store.client = self.redis
        session = Mock()
        session.request.side_effect = self.request
        messenger = VestaboardMessenger(api_key="test-key", session=session)
        return SimpleNamespace(
            redis_data_store=store,
            message_queue=RedisMessageQueue(store),
            vestaboard_messenger=messenger,
            display_manager=DisplayManager(messenger, store),
        )

    def request(self, method, url, **kwargs):
        self.assertIn(RedisDataStore.DISPLAY_LOCK_KEY, self.redis.leases)
        if method == "PUT":
            return response(body=kwargs["json"])
        self.writes.append((self.clock.now, kwargs["json"]))
        if self.on_content_write:
            self.on_content_write()
        outcome = self.outcomes.popleft() if self.outcomes else response()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def enqueue(self, state=BoardState.WEATHER, text="WEATHER"):
        queued = QueuedMessage(BoardMessage(state, state.value, text=text))
        self.board.message_queue.enqueue(queued)
        return queued

    def test_weather_then_flight_are_sent_in_fifo_order_sixteen_seconds_apart(self):
        self.enqueue()
        layout = [[1] * 22 for _ in range(6)]
        self.board.message_queue.enqueue(
            QueuedMessage(BoardMessage(BoardState.FLIGHT, "flight", layout=layout))
        )

        self.assertTrue(self.worker.process_next_message())
        self.assertTrue(self.worker.process_next_message())

        self.assertEqual(self.writes, [(0, {"text": "WEATHER"}), (16, layout)])
        self.assertEqual(self.board.redis_data_store.get_current_record().state, BoardState.FLIGHT)

    def test_retries_respect_cooldown_and_retry_after_and_renew_the_lease(self):
        self.enqueue()
        self.outcomes.extend([
            response(503),
            requests.Timeout("Response lost"),
            response(429, headers={"Retry-After": "90"}),
        ])

        self.worker.process_next_message()

        self.assertEqual([at for at, _ in self.writes], [0, 16, 32, 122])
        self.assertIsNotNone(self.board.redis_data_store.get_current_record())

    def test_cooldown_starts_after_request_completion_including_timeouts(self):
        self.enqueue()
        self.outcomes.append(requests.Timeout("Response lost"))
        self.on_content_write = lambda: self.clock.sleep(10)

        self.worker.process_next_message()

        self.assertEqual([at for at, _ in self.writes], [0, 26])
        self.assertEqual(self.board.redis_data_store.get_display_cooldown_s(), 16)

    def test_restarted_worker_reads_shared_cooldown(self):
        self.enqueue()
        self.worker.process_next_message()
        self.enqueue(BoardState.FLIGHT, "FLIGHT")
        restarted = DisplayWorker(self.make_board())

        restarted.process_next_message()

        self.assertEqual([at for at, _ in self.writes], [0, 16])

    def test_second_worker_cannot_dequeue_or_change_transition_during_send(self):
        self.enqueue()
        self.enqueue(BoardState.FLIGHT, "FLIGHT")
        second = DisplayWorker(self.make_board())

        def try_second_worker():
            self.assertFalse(second.process_next_message())
            self.assertEqual(len(self.redis.pending), 1)
            second.board.vestaboard_messenger._session.request.assert_not_called()

        self.on_content_write = try_second_worker
        self.worker.process_next_message()
        self.on_content_write = None
        second.process_next_message()

        self.assertEqual([payload["text"] for _, payload in self.writes], ["WEATHER", "FLIGHT"])

    def test_lost_lease_cannot_retry_or_overwrite_successor_state(self):
        self.enqueue()
        self.enqueue(BoardState.FLIGHT, "FLIGHT")
        successor = DisplayWorker(self.make_board())

        def expire_and_take_over():
            self.on_content_write = None
            self.assertEqual(self.board.redis_data_store.get_display_cooldown_s(), 76)
            self.clock.sleep(61)
            successor.process_next_message()

        self.on_content_write = expire_and_take_over
        with self.assertLogs("vestaboard.run_display_worker", level="WARNING"):
            with self.assertRaises(LockNotOwnedError):
                self.worker.process_next_message()

        self.assertEqual([at for at, _ in self.writes], [0, 76])
        self.assertEqual(self.board.redis_data_store.get_current_record().state, BoardState.FLIGHT)
        self.assertEqual(self.board.redis_data_store.get_display_cooldown_s(), 16)

    def test_exhausted_retries_log_failure_and_allow_the_next_message(self):
        failed = self.enqueue()
        self.enqueue(BoardState.FLIGHT, "FLIGHT")
        self.outcomes.extend(response(503) for _ in range(5))

        with self.assertLogs("vestaboard.run_display_worker", level="ERROR") as logs:
            self.worker.process_next_message()
        self.assertIn(failed.message_id, "\n".join(logs.output))
        self.assertIsNone(self.board.redis_data_store.get_current_record())
        self.worker.process_next_message()

        self.assertEqual(len(self.writes), 6)
        for previous, current in zip(self.writes, self.writes[1:]):
            self.assertGreaterEqual(current[0] - previous[0], 16)
            self.assertLess(current[0] - previous[0], 16.01)
        self.assertEqual(self.board.redis_data_store.get_current_record().state, BoardState.FLIGHT)

    def test_shutdown_finishes_claimed_message_and_leaves_next_pending(self):
        self.enqueue()
        self.enqueue(BoardState.FLIGHT, "FLIGHT")
        self.on_content_write = self.worker.request_stop

        self.worker.run()

        self.assertEqual(len(self.writes), 1)
        self.assertEqual(len(self.redis.pending), 1)
        self.assertIsNotNone(self.board.redis_data_store.get_current_record())
        self.assertEqual(self.redis.leases, {})

    def test_stopped_worker_does_not_dequeue(self):
        self.enqueue()
        self.worker.request_stop()

        self.assertFalse(self.worker.process_next_message())
        self.assertEqual(len(self.redis.pending), 1)
        self.assertEqual(self.writes, [])

    def test_empty_queue_releases_lease_without_sending(self):
        self.assertFalse(self.worker.process_next_message())
        self.assertEqual(self.redis.leases, {})
        self.assertEqual(self.writes, [])

    def test_invalid_payload_does_not_block_next_message(self):
        self.board.redis_data_store.enqueue_message("invalid JSON")
        self.enqueue()

        with self.assertLogs("vestaboard.run_display_worker", level="ERROR"):
            self.worker.process_next_message()
        self.worker.process_next_message()

        self.assertEqual(len(self.writes), 1)

    def test_redis_failure_before_content_send_fails_closed(self):
        self.enqueue()
        with (
            patch.object(self.redis, "pttl", side_effect=RedisConnectionError("offline")),
            self.assertLogs("vestaboard.run_display_worker", level="ERROR"),
            self.assertRaises(RedisConnectionError),
        ):
            self.worker.process_next_message()
        self.assertEqual(self.writes, [])

    def test_cooldown_setting_cannot_violate_api_limit(self):
        for interval in (0, -1, 14.9, float("nan"), float("inf")):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                DisplayWorker(self.board, min_interval_s=interval)

    def test_independent_producers_share_one_fifo(self):
        producers = [RedisMessageQueue(self.board.redis_data_store) for _ in range(2)]
        messages = [QueuedMessage(BoardMessage(BoardState.WEATHER, "test", text=str(i))) for i in range(20)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda item: producers[item[0] % 2].enqueue(item[1]), enumerate(messages)))
        accepted_order = [QueuedMessage.from_json(value).message_id for value in self.redis.pending]
        dequeued = [self.board.message_queue.dequeue(1).message_id for _ in messages]

        self.assertEqual(set(ids), set(dequeued))
        self.assertEqual(dequeued, accepted_order)


class MessengerGuardTests(unittest.TestCase):
    def test_reads_and_vbml_formatting_do_not_take_display_lease(self):
        session = Mock()
        session.request.return_value = response()
        guard = Mock()
        messenger = VestaboardMessenger(api_key="test-key", session=session, write_guard=guard)

        messenger.get_message()
        messenger.vbml_compose_layout({"components": []})
        messenger.vbml_format_message("WEATHER")

        guard.assert_not_called()
