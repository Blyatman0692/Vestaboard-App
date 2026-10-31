import logging

from sonos_app.playback_metadata import PlaybackMetadata
from vestaboard import utils
from vestaboard.board_message import BoardMessage
from vestaboard.board_state import BoardState
from vestaboard.message_queue import RedisMessageQueue
from vestaboard.queued_message import QueuedMessage
from vestaboard.vestaboard import VestaboardMessenger


logger = logging.getLogger(__name__)


class EventProcessor:
    def __init__(
        self,
        vestaboard_messenger: VestaboardMessenger,
        message_queue: RedisMessageQueue,
    ):
        self.vb_messenger = vestaboard_messenger
        self.message_queue = message_queue

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
        message_id = self.message_queue.enqueue(QueuedMessage(message=msg))
        logger.info("Sonos message queued: %s", message_id)

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
            height=1,
            width=22,
            justify="center",
            align="top"
        )

        placeholder = utils.compose_vbml_component(
            template="",
            height=1,
            width=22,
            justify="center",
            align="top"
        )
        return [top_comp, placeholder]

    @staticmethod
    def compose_metadata_component(metadata: PlaybackMetadata):
        track_name_comp = utils.compose_vbml_component(
            template=metadata.track_name,
            height=2,
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

        return [track_name_comp, artist_comp, album_comp]

