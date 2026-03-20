from dataclasses import dataclass

from app.config import BoardConfig, SonosConfig
from redis_data_store import RedisDataStore
from vestaboard.display_manager import DisplayManager
from vestaboard.vestaboard import VestaboardMessenger
from weather_app.weather import WeatherClient


@dataclass(frozen=True)
class BoardContainer:
    config: BoardConfig
    vestaboard_messenger: VestaboardMessenger
    redis_data_store: RedisDataStore
    display_manager: DisplayManager


@dataclass(frozen=True)
class WeatherContainer:
    board: BoardContainer
    weather_client: WeatherClient


@dataclass(frozen=True)
class SonosContainer:
    board: BoardContainer
    config: SonosConfig
    sonos_data_store: "PostgresDataStore"
    sonos_oauth_client: "SonosOAuthClient"
    sonos_event_processor: "EventProcessor"


def build_board_container(config: BoardConfig | None = None) -> BoardContainer:
    config = config or BoardConfig.from_env()

    vestaboard_messenger = VestaboardMessenger(api_key=config.vb_rw_api_key)
    redis_data_store = RedisDataStore(config.redis_url)
    display_manager = DisplayManager(
        messenger=vestaboard_messenger,
        redis_data_store=redis_data_store,
    )

    return BoardContainer(
        config=config,
        vestaboard_messenger=vestaboard_messenger,
        redis_data_store=redis_data_store,
        display_manager=display_manager,
    )


def build_weather_container(board: BoardContainer | None = None) -> WeatherContainer:
    board = board or build_board_container()

    return WeatherContainer(
        board=board,
        weather_client=WeatherClient(),
    )


def build_sonos_container(
    *,
    board: BoardContainer | None = None,
    config: SonosConfig | None = None,
) -> SonosContainer:
    from sonos_app.data_store import PostgresDataStore
    from sonos_app.event_processor import EventProcessor
    from sonos_app.sonos_oauth_client import SonosOAuthClient

    board = board or build_board_container()
    config = config or SonosConfig.from_env()

    sonos_data_store = PostgresDataStore(
        config.database_url,
        config.client_id,
    )
    sonos_oauth_client = SonosOAuthClient(
        config.client_id,
        config.client_secret,
        config.redirect_uri,
        data_store=sonos_data_store,
    )
    sonos_event_processor = EventProcessor(
        vestaboard_messenger=board.vestaboard_messenger,
        display_manager=board.display_manager,
    )

    return SonosContainer(
        board=board,
        config=config,
        sonos_data_store=sonos_data_store,
        sonos_oauth_client=sonos_oauth_client,
        sonos_event_processor=sonos_event_processor,
    )
