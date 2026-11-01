from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fakeredis
import requests
from redis.exceptions import ConnectionError as RedisConnectionError, LockNotOwnedError, ResponseError

from redis_data_store import RedisDataStore
from vestaboard.board_message import BoardMessage
from vestaboard.board_state import BoardState
from vestaboard.display_manager import DisplayManager
from vestaboard.message_queue import RedisMessageQueue
from vestaboard.queued_message import QueuedMessage
from vestaboard.run_display_worker import DisplayWorker
from vestaboard.transitions import Transition
from vestaboard.vestaboard import VestaboardMessenger


class Clock:
    now = 0.0

    def sleep(self, duration_s):
        self.now += duration_s


def response(status=200, body=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body or {"status": "ok"}).encode()
    result.headers.update(headers or {})
    return result


class DisplayWorkerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.writes = []
        self.outcomes = deque()
        self.on_content_write = None
        for target, replacement in (
            ("time.time", lambda: self.clock.now),
            ("vestaboard.run_display_worker.time.monotonic", lambda: self.clock.now),
            ("vestaboard.run_display_worker.time.sleep", self.clock.sleep),
            ("vestaboard.vestaboard.random.uniform", lambda *_: 0),
        ):
            patcher = patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.server = fakeredis.FakeServer()
        self.redis = fakeredis.FakeRedis(server=self.server, decode_responses=True)
        self.board = self.make_board()
        self.worker = DisplayWorker(self.board)

    def make_board(self):
        store = RedisDataStore.__new__(RedisDataStore)
        store.client = fakeredis.FakeRedis(server=self.server, decode_responses=True)
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
        self.assertTrue(self.redis.exists(RedisDataStore.DISPLAY_LOCK_KEY))
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
            self.assertEqual(self.redis.llen(RedisDataStore.PENDING_QUEUE_KEY), 1)
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
        self.assertEqual(self.board.redis_data_store.get_current_record().state, BoardState.WEATHER)
        self.assertEqual(self.redis.llen(RedisDataStore.PENDING_QUEUE_KEY), 1)
        self.assertEqual(self.board.redis_data_store.get_display_cooldown_s(), 16)

    def test_exhausted_retries_log_failure_and_allow_the_next_message(self):
        failed = self.enqueue()
        self.enqueue(BoardState.FLIGHT, "FLIGHT")
        self.outcomes.extend(response(503) for _ in range(5))

        with self.assertLogs("vestaboard.run_display_worker", level="ERROR") as logs:
            self.worker.process_next_message()
        self.assertIn(failed.message_id, "\n".join(logs.output))
        self.assertIsNone(self.board.redis_data_store.get_current_record())
        failure = json.loads(self.redis.lindex(RedisDataStore.FAILED_QUEUE_KEY, 0))
        self.assertEqual(failure["payload"], failed.to_json())
        self.assertEqual(failure["content_attempts"], 5)
        self.assertEqual(failure["transition_attempts"], 1)
        self.assertIn("HTTPError", failure["error"])
        self.assertFalse(self.redis.exists(RedisDataStore.INFLIGHT_QUEUE_KEY))
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
        self.assertEqual(self.redis.llen(RedisDataStore.PENDING_QUEUE_KEY), 1)
        self.assertIsNotNone(self.board.redis_data_store.get_current_record())
        self.assertFalse(self.redis.exists(RedisDataStore.DISPLAY_LOCK_KEY))

    def test_stopped_worker_does_not_dequeue(self):
        self.enqueue()
        self.worker.request_stop()

        self.assertFalse(self.worker.process_next_message())
        self.assertEqual(self.redis.llen(RedisDataStore.PENDING_QUEUE_KEY), 1)
        self.assertEqual(self.writes, [])

    def test_empty_queue_releases_lease_without_sending(self):
        self.assertFalse(self.worker.process_next_message())
        self.assertFalse(self.redis.exists(RedisDataStore.DISPLAY_LOCK_KEY))
        self.assertEqual(self.writes, [])

    def test_invalid_payload_does_not_block_next_message(self):
        self.board.redis_data_store.enqueue_message("invalid JSON")
        self.enqueue()

        with self.assertLogs("vestaboard.run_display_worker", level="ERROR"):
            self.worker.process_next_message()
        self.worker.process_next_message()

        self.assertEqual(len(self.writes), 1)
        failure = json.loads(self.redis.lindex(RedisDataStore.FAILED_QUEUE_KEY, 0))
        self.assertEqual(failure["payload"], "invalid JSON")
        self.assertEqual(failure["content_attempts"], 0)

    def test_crash_after_claim_recovers_before_newer_messages(self):
        first = self.enqueue()
        self.enqueue(BoardState.FLIGHT, "FLIGHT")
        lease = self.board.redis_data_store.display_lock(60)
        lease.acquire(blocking=False, token="crashed-worker")
        claim = self.board.message_queue.claim("crashed-worker")
        self.assertEqual(claim.payload_json, first.to_json())
        self.clock.sleep(61)  # No release: simulate an abruptly terminated process.

        replacement = DisplayWorker(self.make_board())
        with self.assertLogs("vestaboard.run_display_worker", level="INFO") as logs:
            replacement.process_next_message()
        replacement.process_next_message()

        self.assertIn(f"Recovered message {first.message_id}", "\n".join(logs.output))
        self.assertEqual([body["text"] for _, body in self.writes], ["WEATHER", "FLIGHT"])
        self.assertFalse(self.redis.exists(RedisDataStore.INFLIGHT_QUEUE_KEY))

    def test_lost_claim_response_preserves_recoverable_message(self):
        queued = self.enqueue()
        claim_message = self.board.redis_data_store.claim_message

        def claim_then_disconnect(token):
            claim_message(token)
            raise RedisConnectionError("Claim reply lost")

        with (
            patch.object(self.board.redis_data_store, "claim_message", side_effect=claim_then_disconnect),
            self.assertRaises(RedisConnectionError),
        ):
            self.worker.process_next_message()

        self.assertEqual(self.redis.hget(RedisDataStore.INFLIGHT_QUEUE_KEY, "payload"), queued.to_json())
        DisplayWorker(self.make_board()).process_next_message()
        self.assertEqual(len(self.writes), 1)

    def test_crash_after_api_success_recovers_without_premature_acknowledgment(self):
        queued = self.enqueue()
        with (
            patch.object(self.board.message_queue, "acknowledge", side_effect=SystemExit),
            self.assertRaises(SystemExit),
        ):
            self.worker.process_next_message()

        self.assertEqual(self.redis.hget(RedisDataStore.INFLIGHT_QUEUE_KEY, "payload"), queued.to_json())
        self.assertIsNone(self.board.redis_data_store.get_current_record())
        # The board may have applied the first attempt before the process died.
        self.outcomes.append(response(409, {"status": "skipped"}))
        DisplayWorker(self.make_board()).process_next_message()

        self.assertEqual([at for at, _ in self.writes], [0, 16])
        self.assertFalse(self.redis.exists(RedisDataStore.INFLIGHT_QUEUE_KEY))
        self.assertEqual(self.redis.hget(RedisDataStore.BOARD_KEY, "message_id"), queued.message_id)

    def test_retry_budget_survives_repeated_worker_crashes(self):
        queued = self.enqueue()

        def crash_during_request():
            raise SystemExit

        self.on_content_write = crash_during_request
        for _ in range(5):
            with self.assertRaises(SystemExit):
                DisplayWorker(self.make_board()).process_next_message()
        self.on_content_write = None

        with self.assertLogs("vestaboard.run_display_worker", level="ERROR"):
            DisplayWorker(self.make_board()).process_next_message()

        failure = json.loads(self.redis.lindex(RedisDataStore.FAILED_QUEUE_KEY, 0))
        self.assertEqual(failure["message_id"], queued.message_id)
        self.assertEqual(failure["content_attempts"], 5)
        self.assertEqual(len(self.writes), 5)
        self.assertFalse(self.redis.exists(RedisDataStore.INFLIGHT_QUEUE_KEY))

    def test_redis_ack_failure_keeps_work_for_recovery(self):
        self.enqueue()
        with (
            patch.object(self.board.message_queue, "acknowledge", side_effect=RedisConnectionError("offline")),
            self.assertRaises(RedisConnectionError),
        ):
            self.worker.process_next_message()

        self.assertTrue(self.redis.exists(RedisDataStore.INFLIGHT_QUEUE_KEY))
        self.assertEqual(self.redis.llen(RedisDataStore.FAILED_QUEUE_KEY), 0)
        self.assertIsNone(self.board.redis_data_store.get_current_record())
        DisplayWorker(self.make_board()).process_next_message()
        self.assertFalse(self.redis.exists(RedisDataStore.INFLIGHT_QUEUE_KEY))

    def test_lost_ack_response_does_not_replay_committed_message(self):
        first = self.enqueue()
        self.enqueue(BoardState.FLIGHT, "FLIGHT")
        acknowledge = self.board.message_queue.acknowledge

        def commit_then_disconnect(*args):
            acknowledge(*args)
            raise RedisConnectionError("Acknowledgment reply lost")

        with (
            patch.object(self.board.message_queue, "acknowledge", side_effect=commit_then_disconnect),
            self.assertRaises(RedisConnectionError),
        ):
            self.worker.process_next_message()

        self.assertFalse(self.redis.exists(RedisDataStore.INFLIGHT_QUEUE_KEY))
        self.assertEqual(self.redis.hget(RedisDataStore.BOARD_KEY, "message_id"), first.message_id)
        DisplayWorker(self.make_board()).process_next_message()
        self.assertEqual([body["text"] for _, body in self.writes], ["WEATHER", "FLIGHT"])

    def test_failure_storage_error_does_not_discard_inflight_payload(self):
        self.board.redis_data_store.enqueue_message("broken JSON")
        self.redis.set(RedisDataStore.FAILED_QUEUE_KEY, "wrong Redis type")

        with self.assertRaises(ResponseError) as error:
            self.worker.process_next_message()

        self.assertIn("WRONGTYPE", str(error.exception))
        self.assertEqual(self.redis.hget(RedisDataStore.INFLIGHT_QUEUE_KEY, "payload"), "broken JSON")
        self.redis.delete(RedisDataStore.FAILED_QUEUE_KEY)
        with self.assertLogs("vestaboard.run_display_worker", level="ERROR"):
            DisplayWorker(self.make_board()).process_next_message()
        self.assertFalse(self.redis.exists(RedisDataStore.INFLIGHT_QUEUE_KEY))
        self.assertEqual(self.redis.llen(RedisDataStore.FAILED_QUEUE_KEY), 1)

    def test_stale_worker_cannot_claim_acknowledge_fail_or_spend_attempts(self):
        first = self.enqueue()
        self.enqueue(BoardState.FLIGHT, "FLIGHT")
        old_lease = self.board.redis_data_store.display_lock(60)
        old_lease.acquire(blocking=False, token="old")
        claim = self.board.message_queue.claim("old")
        self.clock.sleep(61)
        new_lease = self.board.redis_data_store.display_lock(60)
        new_lease.acquire(blocking=False, token="new")
        queue = self.board.message_queue
        operations = (
            lambda: queue.claim("old"),
            lambda: queue.acknowledge(claim, "old", first, Transition.CLASSIC),
            lambda: queue.fail(claim, "old", RuntimeError("stale"), first),
            lambda: queue.start_attempt(claim, "old", True, 5),
        )
        for operation in operations:
            with self.assertRaises(LockNotOwnedError):
                operation()

        self.assertEqual(self.redis.llen(RedisDataStore.PENDING_QUEUE_KEY), 1)
        self.assertEqual(self.redis.llen(RedisDataStore.FAILED_QUEUE_KEY), 0)
        self.assertIsNone(self.board.redis_data_store.get_current_record())
        self.assertEqual(self.redis.hget(RedisDataStore.INFLIGHT_QUEUE_KEY, "content_attempts"), "0")
        queue.acknowledge(claim, "new", first, Transition.CLASSIC)
        new_lease.release()

    def test_failed_flight_can_requeue_but_success_is_suppressed_for_one_hour(self):
        queued = QueuedMessage(
            BoardMessage(BoardState.FLIGHT, "flight_app", text="FLIGHT"), flight_id="flight-1"
        )
        queue, store = self.board.message_queue, self.board.redis_data_store
        self.assertEqual(queue.enqueue(queued), queued.message_id)
        self.assertTrue(store.has_pending_or_seen_flight("flight-1"))
        self.assertFalse(store.has_seen_flight("flight-1"))
        self.outcomes.append(response(400))
        with self.assertLogs("vestaboard.run_display_worker", level="ERROR"):
            self.worker.process_next_message()

        self.assertFalse(store.has_pending_or_seen_flight("flight-1"))
        retry = QueuedMessage(queued.message, flight_id="flight-1")
        self.assertEqual(queue.enqueue(retry), retry.message_id)
        self.worker.process_next_message()
        self.assertTrue(store.has_seen_flight("flight-1"))
        self.assertFalse(self.redis.exists("flight:pending:flight-1"))
        self.assertIsNone(queue.enqueue(QueuedMessage(queued.message, flight_id="flight-1")))
        self.clock.sleep(3601)
        self.assertIsNotNone(queue.enqueue(QueuedMessage(queued.message, flight_id="flight-1")))

    def test_pending_flight_does_not_expire_while_waiting_or_after_worker_crash(self):
        queued = QueuedMessage(
            BoardMessage(BoardState.FLIGHT, "flight_app", text="FLIGHT"), flight_id="flight-1"
        )
        queue = self.board.message_queue
        queue.enqueue(queued)
        self.clock.sleep(3601)
        self.assertEqual(self.redis.ttl("flight:pending:flight-1"), -1)
        self.assertIsNone(queue.enqueue(QueuedMessage(queued.message, flight_id="flight-1")))
        with (
            patch.object(queue, "acknowledge", side_effect=SystemExit),
            self.assertRaises(SystemExit),
        ):
            self.worker.process_next_message()
        self.assertIsNone(queue.enqueue(QueuedMessage(queued.message, flight_id="flight-1")))
        self.assertFalse(self.board.redis_data_store.has_seen_flight("flight-1"))
        DisplayWorker(self.make_board()).process_next_message()
        self.assertTrue(self.board.redis_data_store.has_seen_flight("flight-1"))

    def test_concurrent_flight_enqueues_accept_exactly_one_pending_message(self):
        messages = [QueuedMessage(
            BoardMessage(BoardState.FLIGHT, "flight_app", text="FLIGHT"), flight_id="same-flight"
        ) for _ in range(8)]
        producers = [self.make_board().message_queue for _ in messages]
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda pair: pair[0].enqueue(pair[1]), zip(producers, messages)))

        accepted = [message_id for message_id in ids if message_id is not None]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(self.redis.llen(RedisDataStore.PENDING_QUEUE_KEY), 1)
        self.assertEqual(self.redis.get("flight:pending:same-flight"), accepted[0])

    def test_lost_flight_enqueue_response_cannot_create_duplicate(self):
        queued = QueuedMessage(
            BoardMessage(BoardState.FLIGHT, "flight_app", text="FLIGHT"), flight_id="flight-1"
        )
        store = self.board.redis_data_store
        enqueue = store.enqueue_flight_message

        def enqueue_then_disconnect(*args):
            enqueue(*args)
            raise RedisConnectionError("Enqueue reply lost")

        with (
            patch.object(store, "enqueue_flight_message", side_effect=enqueue_then_disconnect),
            self.assertRaises(RedisConnectionError),
        ):
            self.board.message_queue.enqueue(queued)
        self.assertIsNone(self.board.message_queue.enqueue(
            QueuedMessage(queued.message, flight_id="flight-1")
        ))
        self.assertEqual(self.redis.llen(RedisDataStore.PENDING_QUEUE_KEY), 1)

    def test_redis_failure_before_content_send_fails_closed(self):
        self.enqueue()
        with (
            patch.object(self.board.redis_data_store.client, "pttl", side_effect=RedisConnectionError("offline")),
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
        accepted_order = [
            QueuedMessage.from_json(value).message_id
            for value in self.redis.lrange(RedisDataStore.PENDING_QUEUE_KEY, 0, -1)
        ]
        lease = self.board.redis_data_store.display_lock(60)
        lease.acquire(blocking=False, token="consumer")
        dequeued = []
        for _ in messages:
            claim = self.board.message_queue.claim("consumer")
            queued = QueuedMessage.from_json(claim.payload_json)
            dequeued.append(queued.message_id)
            self.board.message_queue.acknowledge(claim, "consumer", queued, Transition.CLASSIC)
        lease.release()

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
