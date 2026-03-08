from sonos_app.data_store import PostgresDataStore
from sonos_app.playback_metadata import PlaybackMetadata
from vestaboard import VestaboardMessenger
from config import DB_URL, SONOS_CLIENT_ID

class EventProcessor:
    def __init__(self):
        self.vb_messenger = VestaboardMessenger()
        self.db_client = PostgresDataStore(DB_URL, SONOS_CLIENT_ID)

    def process_metadata(self, metadata: PlaybackMetadata):
        if not self._is_relevant_metadata(metadata):
            return

        self.vb_messenger.send_message(metadata.track_name)


    @staticmethod
    def _is_relevant_metadata(metadata: PlaybackMetadata):
        return bool(
            metadata and
            metadata.group_id and
            metadata.track_name
        )




