from dataclasses import dataclass

from redis_data_store import RedisDataStore
from vestaboard.queued_message import QueuedMessage
from vestaboard.transitions import Transition


@dataclass
class MessageClaim:
    """Raw payload and persisted attempt counts for the single active delivery."""

    payload_json: str
    recovered: bool
    content_attempts: int
    transition_attempts: int


class AttemptsExhausted(RuntimeError):
    """A persisted HTTP attempt budget has been used up, including before a crash."""


class RedisMessageQueue:
    """Persist FIFO messages until acknowledgment or explicit failure."""

    def __init__(self, redis_data_store: RedisDataStore) -> None:
        self.redis_data_store = redis_data_store

    def enqueue(self, message: QueuedMessage) -> str | None:
        """Return the message ID after Redis accepts the write.

        Duplicate tracked flights return None. Serialization and Redis errors
        propagate to the caller.
        """
        payload_json = message.to_json()

        if message.flight_id is not None:
            if not self.redis_data_store.enqueue_flight_message(
                payload_json, message.message_id, message.flight_id
            ):
                return None
        else:
            self.redis_data_store.enqueue_message(payload_json)
        return message.message_id

    def claim(self, lease_token: str) -> MessageClaim | None:
        """Recover unfinished work first, otherwise claim the oldest pending item."""
        result = self.redis_data_store.claim_message(lease_token)
        if result is None:
            return None
        payload, recovered, content_attempts, transition_attempts = result
        return MessageClaim(payload, bool(recovered), int(content_attempts), int(transition_attempts))

    def start_attempt(
        self, claim: MessageClaim, lease_token: str, is_content: bool, max_attempts: int
    ) -> int:
        attempt = self.redis_data_store.start_message_attempt(
            lease_token, claim.payload_json, is_content, max_attempts
        )
        if attempt == 0:
            raise AttemptsExhausted("Persisted HTTP retry limit reached")
        if is_content:
            claim.content_attempts = attempt
        else:
            claim.transition_attempts = attempt
        return attempt

    def acknowledge(
        self, claim: MessageClaim, lease_token: str,
        message: QueuedMessage, transition: Transition,
    ) -> None:
        self.redis_data_store.acknowledge_message(
            lease_token, claim.payload_json, message.message, message.message_id,
            transition, message.flight_id,
        )

    def fail(
        self, claim: MessageClaim, lease_token: str, error: Exception,
        message: QueuedMessage | None = None,
    ) -> None:
        self.redis_data_store.fail_message(
            lease_token, claim.payload_json, f"{type(error).__name__}: {error}",
            message.message_id if message else "",
            message.message.source if message else "",
            message.flight_id if message else None,
        )
