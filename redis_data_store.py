from dataclasses import dataclass
from typing import cast

import redis
from vestaboard.board_message import BoardMessage
from vestaboard.board_state import BoardState
from vestaboard.transitions import Transition
from vestaboard.queued_message import QueuedMessage

@dataclass
class BoardDisplayRecord:
    state: BoardState
    source: str
    transition: Transition

class RedisDataStore:
    BOARD_KEY = "vestaboard:display:current"
    FLIGHT_SEEN_KEY_PREFIX = "flight:seen"
    QUEUE_KEY = "vestaboard:queue:pending"

    def __init__(self, redis_url):
        self.client = redis.Redis.from_url(
            redis_url,
            decode_responses=True
        )

    def get_current_record(self):
        data = self.client.hgetall(self.BOARD_KEY)

        if not data:
            raise ValueError("No current board state recorded")

        return BoardDisplayRecord(
            state=BoardState(data["state"]),
            source=data["source"],
            transition=data["transition"]
        )

    def set_current_record(self, message: BoardMessage, transition: Transition):
        self.client.hset(
            name=self.BOARD_KEY,
            mapping={
                "state": message.state.value,
                "source": message.source,
                "transition": transition.value
            }
        )

    def enqueue_message(self, payload: str) -> None:
        self.client.rpush(self.QUEUE_KEY, payload)

    def dequeue_message(self, timeout: int) -> str | None:
        result = cast(
            tuple[str, str] | None,
            self.client.blpop([self.QUEUE_KEY], timeout=timeout),
        )

        if result is None:
            return None

        _, payload = result
        return payload


    def has_seen_flight(self, fr24_id: str) -> bool:
        return bool(self.client.exists(self._flight_seen_key(fr24_id)))

    def mark_flight_seen(self, fr24_id: str, ttl_s: int = 60 * 60) -> None:
        if ttl_s <= 0:
            raise ValueError("Flight seen TTL must be greater than 0.")

        self.client.set(self._flight_seen_key(fr24_id), "1", ex=ttl_s)

    def _flight_seen_key(self, fr24_id: str) -> str:
        return f"{self.FLIGHT_SEEN_KEY_PREFIX}:{fr24_id}"





