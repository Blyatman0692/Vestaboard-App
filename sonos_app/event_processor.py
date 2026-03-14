from sonos_app.data_store import PostgresDataStore
from sonos_app.playback_metadata import PlaybackMetadata
from vestaboard import vestaboard, utils, display_manager
from sonos_app.config import DB_URL, SONOS_CLIENT_ID
from vestaboard.board_message import BoardMessage
from vestaboard.board_state import BoardState


class EventProcessor:
    def __init__(self):
        self.vb_messenger = vestaboard.VestaboardMessenger()
        self.manager = display_manager.DisplayManager()
        self.db_client = PostgresDataStore(DB_URL, SONOS_CLIENT_ID)

    def process_metadata(self, metadata: PlaybackMetadata):
        if not self._is_relevant_metadata(metadata):
            return

        vbml_components = []
        headers = self.compose_header_components()
        for h in headers:
            vbml_components.append(h)

        metas = self.compose_metadata_component(metadata)
        for m in metas:
            vbml_components.append(m)

        vbml_payload = utils.compose_vbml_payload(vbml_components)

        vbml_layout = self.vb_messenger.vbml_compose_layout(vbml_payload)

        msg = BoardMessage(BoardState.SONOS, "sonos_app", layout=vbml_layout)
        self.manager.send(msg)

    @staticmethod
    def _is_relevant_metadata(metadata: PlaybackMetadata):
        return bool(
            metadata and
            metadata.group_id and
            metadata.track_name
        )

    @staticmethod
    def compose_header_components():
        top_comp = utils.compose_vbml_component(
            template="{66}{67}{68}  NOW PLAYING   {68}{67}{66}",
            height=2,
            width=22,
            justify="center",
            align="top"
        )
        return [top_comp]

    @staticmethod
    def compose_metadata_component(metadata: PlaybackMetadata):
        track_name_comp = utils.compose_vbml_component(
            template=metadata.track_name,
            height=2,
            width=22,
            justify="center",
            align="top"
        )

        by_comp = utils.compose_vbml_component(
            template="BY",
            height=1,
            width=22,
            justify="center",
            align="top"
        )

        artist_comp = utils.compose_vbml_component(
            template=metadata.artist_name,
            height=1,
            width=22,
            justify="center",
            align="top"
        )

        album_comp = utils.compose_vbml_component(
            template=metadata.album_name,
            height=1,
            width=22,
            justify="center",
            align="top"
        )

        return [track_name_comp, by_comp, artist_comp, album_comp]



