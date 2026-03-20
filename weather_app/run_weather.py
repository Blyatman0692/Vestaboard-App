import logging
import sys
from typing import List

from app import build_container
from vestaboard.board_message import BoardMessage
from vestaboard.board_state import BoardState
from weather_app.weather_header import WeatherHeader
from weather_app.weather import WeatherNow, format_weather_line

from vestaboard import utils

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
)

logger = logging.getLogger(__name__)

def run():
    logger.info("Weather job started")

    # Time gate: only run between 09:00–23:00 Pacific Time
    if not utils.time_gate(logger, 9, 0, 23, 0):
        return

    container = build_container()
    wc = container.weather_client
    weather_header = WeatherHeader()
    vb = container.vestaboard_messenger
    manager = container.display_manager

    weather_data: List[WeatherNow] = []

    try:
        weather_data = wc.get_current_weather_multi_cities()
        logger.info("Successfully retrieved weather info (%d cities)", len(weather_data))
    except Exception:
        logger.exception("Error retrieving weather info")
        # In production/scheduled runs, fail fast so the platform marks the job as failed.
        raise

    if not weather_data:
        logger.warning("No weather data returned; skipping message send.")
        return

    vbml_components = []
    for hc in weather_header.compose_header_components():
        vbml_components.append(hc)

    for now in weather_data:
        weather_string = "{67}" + format_weather_line(now)
        component = utils.compose_vbml_component(weather_string)
        vbml_components.append(component)

    vbml_payload = utils.compose_vbml_payload(vbml_components)
    logger.debug("VBML payload prepared")
    vbml_layout = vb.vbml_compose_layout(vbml_payload)

    try:
        msg = BoardMessage(BoardState.WEATHER, "weather_app", layout=vbml_layout)
        manager.send(msg)
        logger.info("Message sent successfully")
    except Exception:
        logger.exception("Error sending message")
        raise


if __name__ == "__main__":
    run()
