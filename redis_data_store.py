import os
import redis
from dotenv import load_dotenv

from vestaboard.board_message import BoardMessage
from vestaboard.board_state import BoardState


class RedisDataStore:
    KEY = "vestaboard:display:current"

    def __init__(self, redis_url):
        self.client = redis.Redis.from_url(
            redis_url,
            decode_responses=True
        )

    def get_current_record(self):
        data = self.client.hgetall(self.KEY)

        if not data:
            raise ValueError("No current board state recorded")

        return BoardMessage(
            state=BoardState(data["state"]),
            source=data["source"]
        )

    def set_current_record(self, message: BoardMessage):
        self.client.hset(
            name=self.KEY,
            mapping={
                "state": message.state.value,
                "source": message.source
            }
        )





