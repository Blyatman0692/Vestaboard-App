from dataclasses import dataclass

from app.config import AppConfig
from redis_data_store import RedisDataStore
from sonos_app.data_store import PostgresDataStore
from sonos_app.event_processor import EventProcessor
from sonos_app.sonos_oauth_client import SonosOAuthClient
from vestaboard.display_manager import DisplayManager
from vestaboard.vestaboard import VestaboardMessenger
from weather_app.weather import WeatherClient


@dataclass(frozen=True)
class AppContainer:
    config: AppConfig
    vestaboard_messenger: VestaboardMessenger
    redis_data_store: RedisDataStore
    display_manager: DisplayManager
    weather_client: WeatherClient
    sonos_data_store: PostgresDataStore
    sonos_oauth_client: SonosOAuthClient
    sonos_event_processor: EventProcessor


def build_container(config: AppConfig | None = None) -> AppContainer:
    config = config or AppConfig.from_env()

    vestaboard_messenger = VestaboardMessenger(api_key=config.vb_rw_api_key)
    redis_data_store = RedisDataStore(config.redis_url)
    display_manager = DisplayManager(
        messenger=vestaboard_messenger,
        redis_data_store=redis_data_store,
    )
    weather_client = WeatherClient()
    sonos_data_store = PostgresDataStore(
        config.database_url,
        config.sonos_client_id,
    )
    sonos_oauth_client = SonosOAuthClient(
        config.sonos_client_id,
        config.sonos_client_secret,
        config.sonos_redirect_uri,
        data_store=sonos_data_store,
    )
    sonos_event_processor = EventProcessor(
        vestaboard_messenger=vestaboard_messenger,
        display_manager=display_manager,
    )

    return AppContainer(
        config=config,
        vestaboard_messenger=vestaboard_messenger,
        redis_data_store=redis_data_store,
        display_manager=display_manager,
        weather_client=weather_client,
        sonos_data_store=sonos_data_store,
        sonos_oauth_client=sonos_oauth_client,
        sonos_event_processor=sonos_event_processor,
    )
