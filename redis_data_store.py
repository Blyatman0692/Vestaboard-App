from dataclasses import dataclass
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

        return BoardDisplayRecord(
            state=BoardState(data["state"]),
            source=data["source"],
            transition=data["transition"]
        )

    def set_current_record(self, message: BoardMessage, transition: Transition):
        self.client.hset(
            name=self.KEY,
            mapping={
                "state": message.state.value,
                "source": message.source,
                "transition": transition.value
            }
        )





