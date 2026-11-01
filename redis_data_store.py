from dataclasses import dataclass
from datetime import datetime, timezone
import math

import redis
from redis.exceptions import LockNotOwnedError, ResponseError

from vestaboard.board_message import BoardMessage
from vestaboard.board_state import BoardState
from vestaboard.transitions import Transition
from vestaboard import queue_scripts


@dataclass
class BoardDisplayRecord:
    state: BoardState
    source: str
    transition: Transition


class RedisDataStore:
    BOARD_KEY = "vestaboard:display:current"
    FLIGHT_SEEN_KEY_PREFIX = "flight:seen"
    # The queue namespace currently assumes one board per Redis database.
    PENDING_QUEUE_KEY = "vestaboard:queue:pending"
    INFLIGHT_QUEUE_KEY = "vestaboard:queue:inflight"
    FAILED_QUEUE_KEY = "vestaboard:queue:failed"
    FLIGHT_PENDING_KEY_PREFIX = "flight:pending"
    DISPLAY_LOCK_KEY = "vestaboard:display:lock"
    DISPLAY_COOLDOWN_KEY = "vestaboard:display:cooldown"

    def __init__(self, redis_url):
        self.client = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
        )

    def get_current_record(self) -> BoardDisplayRecord | None:
        data = self.client.hgetall(self.BOARD_KEY)

        if not data:
            return None

        return BoardDisplayRecord(
            state=BoardState(data["state"]),
            source=data["source"],
            transition=Transition(data["transition"]),
        )

    def set_current_record(self, message: BoardMessage, transition: Transition):
        self.client.hset(
            name=self.BOARD_KEY,
            mapping={
                "state": message.state.value,
                "source": message.source,
                "transition": transition.value,
            },
        )

    def enqueue_message(self, payload_json: str) -> None:
        """Append serialized content; Redis write errors propagate to the caller."""
        # Claims take the leftmost entry, preserving Redis acceptance order.
        self.client.rpush(self.PENDING_QUEUE_KEY, payload_json)

    def _queue_operation(self, script: str, keys: list[str], *args):
        try:
            return self.client.eval(script, len(keys), *keys, *args)
        except ResponseError as exc:
            if "DISPLAY_LEASE_LOST" in str(exc) or "DISPLAY_CLAIM_CHANGED" in str(exc):
                raise LockNotOwnedError(str(exc)) from exc
            raise

    def claim_message(self, lease_token: str):
        return self._queue_operation(
            queue_scripts.CLAIM,
            [self.DISPLAY_LOCK_KEY, self.INFLIGHT_QUEUE_KEY, self.PENDING_QUEUE_KEY],
            lease_token,
        )

    def start_message_attempt(
        self, lease_token: str, payload_json: str, is_content: bool, max_attempts: int
    ) -> int:
        return self._queue_operation(
            queue_scripts.START_ATTEMPT,
            [self.DISPLAY_LOCK_KEY, self.INFLIGHT_QUEUE_KEY],
            lease_token, payload_json,
            "content_attempts" if is_content else "transition_attempts", max_attempts,
        )

    def acknowledge_message(
        self, lease_token: str, payload_json: str, message: BoardMessage,
        message_id: str, transition: Transition, flight_id: str | None,
    ) -> None:
        self._queue_operation(
            queue_scripts.ACKNOWLEDGE,
            [self.DISPLAY_LOCK_KEY, self.INFLIGHT_QUEUE_KEY, self.BOARD_KEY,
             self._flight_pending_key(flight_id or ""), self._flight_seen_key(flight_id or "")],
            lease_token, payload_json, message.state.value, message.source,
            transition.value, message_id, flight_id or "",
        )

    def fail_message(
        self, lease_token: str, payload_json: str, error: str,
        message_id: str = "", source: str = "", flight_id: str | None = None,
    ) -> None:
        self._queue_operation(
            queue_scripts.FAIL,
            [self.DISPLAY_LOCK_KEY, self.INFLIGHT_QUEUE_KEY, self.FAILED_QUEUE_KEY,
             self._flight_pending_key(flight_id or "")],
            lease_token, payload_json, error, datetime.now(timezone.utc).isoformat(),
            message_id, source, flight_id or "",
        )

    def enqueue_flight_message(self, payload_json: str, message_id: str, flight_id: str) -> bool:
        """Atomically suppress duplicates and register pending delivery without a TTL."""
        return bool(self._queue_operation(
            queue_scripts.ENQUEUE_FLIGHT,
            [self.PENDING_QUEUE_KEY, self._flight_pending_key(flight_id),
             self._flight_seen_key(flight_id)],
            payload_json, message_id,
        ))

    def display_lock(self, timeout_s: float):
        """Create a token-owned lease shared by all display workers."""
        return self.client.lock(self.DISPLAY_LOCK_KEY, timeout=timeout_s)

    def get_display_cooldown_s(self) -> float:
        """Read remaining cooldown using Redis time, independent of worker clocks."""
        ttl_ms = self.client.pttl(self.DISPLAY_COOLDOWN_KEY)
        if ttl_ms == -1:
            raise ValueError("Display cooldown key must have an expiration.")
        return max(0, ttl_ms) / 1000

    def set_display_cooldown(self, duration_s: float) -> None:
        self.client.set(
            self.DISPLAY_COOLDOWN_KEY, "1", px=math.ceil(duration_s * 1000)
        )

    def has_seen_flight(self, fr24_id: str) -> bool:
        return bool(self.client.exists(self._flight_seen_key(fr24_id)))

    def has_pending_or_seen_flight(self, fr24_id: str) -> bool:
        return bool(self.client.exists(
            self._flight_pending_key(fr24_id), self._flight_seen_key(fr24_id)
        ))

    def _flight_pending_key(self, fr24_id: str) -> str:
        return f"{self.FLIGHT_PENDING_KEY_PREFIX}:{fr24_id}"

    def _flight_seen_key(self, fr24_id: str) -> str:
        return f"{self.FLIGHT_SEEN_KEY_PREFIX}:{fr24_id}"
