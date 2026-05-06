from __future__ import annotations

from dataclasses import dataclass

from app.config import BoardConfig, FlightConfig, SonosConfig
from flight_app.models import GeoBounds
from flight_app.opensky_client import OpenSkyClient


@dataclass(frozen=True)
class BoardContainer:
    config: BoardConfig
    vestaboard_messenger: "VestaboardMessenger"
    redis_data_store: "RedisDataStore"
    display_manager: "DisplayManager"


@dataclass(frozen=True)
class WeatherContainer:
    board: BoardContainer
    weather_client: "WeatherClient"


@dataclass(frozen=True)
class FlightContainer:
    config: FlightConfig
    bounds: GeoBounds
    opensky_client: OpenSkyClient


@dataclass(frozen=True)
class SonosContainer:
    board: BoardContainer
    config: SonosConfig
    postgres_data_store: "PostgresDataStore"
    sonos_oauth_client: "SonosOAuthClient"
    sonos_event_processor: "EventProcessor"


def build_board_container(config: BoardConfig | None = None) -> BoardContainer:
    from redis_data_store import RedisDataStore
    from vestaboard.display_manager import DisplayManager
    from vestaboard.vestaboard import VestaboardMessenger

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
    from weather_app.weather import WeatherClient

    board = board or build_board_container()

    return WeatherContainer(
        board=board,
        weather_client=WeatherClient(),
    )


def build_flight_container(config: FlightConfig | None = None) -> FlightContainer:
    config = config or FlightConfig.from_env()
    bounds = GeoBounds(
        lamin=config.lamin,
        lomin=config.lomin,
        lamax=config.lamax,
        lomax=config.lomax,
    )
    opensky_client = OpenSkyClient(
        client_id=config.opensky_client_id,
        client_secret=config.opensky_client_secret,
        token_timeout_s=config.opensky_token_timeout_s,
        anonymous_fallback_on_auth_network_error=(
            config.opensky_anonymous_fallback_on_auth_network_error
        ),
    )

    return FlightContainer(
        config=config,
        bounds=bounds,
        opensky_client=opensky_client,
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
        postgres_data_store=sonos_data_store,
        sonos_oauth_client=sonos_oauth_client,
        sonos_event_processor=sonos_event_processor,
    )
