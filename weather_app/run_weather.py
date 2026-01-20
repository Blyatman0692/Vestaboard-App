import logging
import os

import utils
import weather
from typing import List
from dotenv import load_dotenv
from datetime import date
from vestaboard import VestaboardMessenger
from weather_app.weather import WeatherNow

LOG_FILE = "/var/log/mycron.log"

logging.basicConfig(
    filename="/Users/zjw/Desktop/Vestaboard App/weather_cron.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger()

def get_headers():
    pass


def run():
    logger.info("Weather job started")

    load_dotenv()

    wc = weather.WeatherClient()
    vb = VestaboardMessenger()
    weather_data = List[WeatherNow]

    header_string = 2 * "{66}" + 2 * "{68}" + date.today().strftime(
        "%Y-%m-%d") + 2 * "{68}" + 2 * "{66}"

    try:
        weather_data = wc.get_current_weather_multi_cities()
        logger.info(f"Successfully retrieved weather info:\n{weather_data}")
    except Exception as e:
        logger.exception(f"Error retrieving weather info: {e}")

    vbml_components = [utils.compose_vbml_component(header_string, justify="center", align="top")]

    for now in weather_data:
        weather_string = "{67}" + weather.format_weather_line(now)
        component = utils.compose_vbml_component(weather_string)
        vbml_components.append(component)

    vbml_payload = utils.compose_vbml_payload(vbml_components)
    vbml_layout = vb.vbml_compose(vbml_payload)

    try:
        vb.send_layout(vbml_layout)
        logger.info(f"Message sent:\n{vbml_layout}")
    except Exception as e:
        logger.exception(f"Error sending message: {e}")


if __name__ == "__main__":
    run()