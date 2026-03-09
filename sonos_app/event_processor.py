from sonos_app.data_store import PostgresDataStore
from sonos_app.playback_metadata import PlaybackMetadata
from vestaboard import VestaboardMessenger
from sonos_app.config import DB_URL, SONOS_CLIENT_ID

import utils

class EventProcessor:
    def __init__(self):
        self.vb_messenger = VestaboardMessenger()
        self.db_client = PostgresDataStore(DB_URL, SONOS_CLIENT_ID)

    def process_metadata(self, metadata: PlaybackMetadata):
        if not self._is_relevant_metadata(metadata):
            return

        vbml_components = []
        vbml_components.append(self.compose_header_components())
        vbml_components.append(self.compose_metadata_component(metadata))

        vbml_payload = utils.compose_vbml_payload(vbml_components)

        vbml_layout = self.vb_messenger.vbml_compose_layout(vbml_payload)

        self.vb_messenger.send_layout(vbml_layout)

    @staticmethod
    def _is_relevant_metadata(metadata: PlaybackMetadata):
        return bool(
            metadata and
            metadata.group_id and
            metadata.track_name
        )

    @staticmethod
    def compose_header_components():
        left_filler_comp = utils.compose_vbml_component(
            template="{66}{67}{68}",
            height=1,
            width=3,
            justify="left",
            align="top"
        )

        center_comp = utils.compose_vbml_component(
            template="NOW PLAYING",
            height=1,
            width=16,
            justify="center",
            align="top"
        )

        right_filler_comp = utils.compose_vbml_component(
            template="{68}{67}{66}",
            height=1,
            width=3,
            justify="right",
            align="top"
        )

        left_border = utils.compose_vbml_component(
            template="{66}\n{66}\n{66}\n{66}\n{66}",
            height=5,
            width=1,
            abs_x=0,
            abs_y=1
        )

        right_boarder = utils.compose_vbml_component(
            template="{66}\n{66}\n{66}\n{66}\n{66}",
            height=5,
            width=1,
            abs_x=21,
            abs_y=1
        )

        return [left_filler_comp, center_comp, right_filler_comp, left_border, right_boarder]

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

        return [track_name_comp, by_comp, artist_comp]



