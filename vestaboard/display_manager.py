import os

from redis_data_store import RedisDataStore, BoardDisplayRecord
from vestaboard.board_message import BoardMessage
from vestaboard.transitions import Transition, TransitionSpeed
from vestaboard.vestaboard import VestaboardMessenger
from dotenv import load_dotenv

class DisplayManager:
    def __init__(self):
        load_dotenv()
        self.messenger = VestaboardMessenger()
        self.redis_data_store = RedisDataStore(os.getenv("REDIS_URL"))


    def send(self, message: BoardMessage):
        prev_record = self._get_prev_record()

        transition, transition_speed = self._decide_transition(prev_record, message)
        board_transition, board_transition_speed = self.messenger.set_transition(transition, transition_speed)

        # persist record first to allow transition to be properly set
        self._persist_record(message, board_transition)
        self._send_content(message)

    def _get_prev_record(self) -> BoardDisplayRecord:
        return self.redis_data_store.get_current_record()

    def _persist_record(self, message: BoardMessage, transition: Transition):
        self.redis_data_store.set_current_record(message, transition)

    def _send_content(self, message: BoardMessage):
        if message.layout:
            self.messenger.send_layout(message.layout)
            return

        self.messenger.send_message(message.text)

    @staticmethod
    def _decide_transition(prev_record: BoardDisplayRecord, next_message: BoardMessage):
        if prev_record.state != next_message.state:
            return Transition.CURTAIN, TransitionSpeed.FAST

        return Transition.CLASSIC, TransitionSpeed.FAST