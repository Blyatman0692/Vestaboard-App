from dataclasses import dataclass
import math
from typing import cast

import redis

from vestaboard.board_message import BoardMessage
from vestaboard.board_state import BoardState
from vestaboard.transitions import Transition


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
        # RPUSH appends on the right; BLPOP removes from the left for FIFO order.
        self.client.rpush(self.PENDING_QUEUE_KEY, payload_json)

    def dequeue_message(self, timeout_s: int) -> str | None:
        """Remove the oldest payload, or return None after timeout_s seconds.

        Zero waits indefinitely. BLPOP removes the entry immediately, so a
        consumer crash after this call can lose the message until recovery is
        implemented.
        """
        queue_entry = cast(
            tuple[str, str] | None,
            self.client.blpop([self.PENDING_QUEUE_KEY], timeout=timeout_s),
        )

        if queue_entry is None:
            return None

        _queue_key, payload_json = queue_entry
        return payload_json

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

    def mark_flight_seen(self, fr24_id: str, ttl_s: int = 60 * 60) -> None:
        if ttl_s <= 0:
            raise ValueError("Flight seen TTL must be greater than 0.")

        self.client.set(self._flight_seen_key(fr24_id), "1", ex=ttl_s)

    def _flight_seen_key(self, fr24_id: str) -> str:
        return f"{self.FLIGHT_SEEN_KEY_PREFIX}:{fr24_id}"
