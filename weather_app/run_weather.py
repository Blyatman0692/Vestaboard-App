import logging
import os
import sys
from typing import List

from dotenv import load_dotenv

from datetime import datetime
from zoneinfo import ZoneInfo

from weather_app.weather_header import WeatherHeader
from weather_app.weather import WeatherNow, WeatherClient, format_weather_line

import utils
from vestaboard import VestaboardMessenger

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

    load_dotenv(override=False)

    # Time gate: only run between 08:00–23:00 Pacific Time
    now_pt = datetime.now(ZoneInfo("America/Los_Angeles"))
    if not (8 <= now_pt.hour <= 23):
        logger.info(
            "Outside allowed PT window (08–23). Current PT time: %s. Skipping run.",
            now_pt.strftime("%Y-%m-%d %H:%M:%S")
        )
        return

    wc = WeatherClient()
    weather_header = WeatherHeader()
    vb = VestaboardMessenger()

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
        vb.send_layout(vbml_layout)
        logger.info("Message sent successfully")
    except Exception:
        logger.exception("Error sending message")
        raise


if __name__ == "__main__":
    run()