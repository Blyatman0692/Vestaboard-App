from redis_data_store import RedisDataStore
from queued_message import QueuedMessage

class RedisMessageQueue:
    def __init__(self, redis_data_store: RedisDataStore) -> None:
        self.redis_data_store = redis_data_store

    def enqueue(self, message: QueuedMessage) -> str:
        payload = message.to_json()

        self.redis_data_store.enqueue_message(payload)
        return message.message_id

    def dequeue(self, timeout: int) -> QueuedMessage | None:
        payload = self.redis_data_store.dequeue_message(timeout)

        if payload is None:
            return None

        message = QueuedMessage.from_json(payload)

        return message

        





