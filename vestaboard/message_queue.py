from redis_data_store import RedisDataStore
from vestaboard.queued_message import QueuedMessage


class RedisMessageQueue:
    """Translate queued messages to and from Redis FIFO payloads."""

    def __init__(self, redis_data_store: RedisDataStore) -> None:
        self.redis_data_store = redis_data_store

    def enqueue(self, message: QueuedMessage) -> str:
        """Return the message ID after Redis accepts the write.

        Serialization and Redis errors propagate to the caller.
        """
        payload_json = message.to_json()

        self.redis_data_store.enqueue_message(payload_json)
        return message.message_id

    def dequeue(self, timeout_s: int) -> QueuedMessage | None:
        """Remove the oldest message, or return None when the wait expires.

        A timeout of zero waits indefinitely. Invalid payloads raise ValueError
        after removal from Redis; this queue does not yet support recovery.
        """
        payload_json = self.redis_data_store.dequeue_message(timeout_s)

        if payload_json is None:
            return None

        return QueuedMessage.from_json(payload_json)
