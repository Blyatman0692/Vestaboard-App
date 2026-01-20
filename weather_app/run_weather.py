import logging
import sys

from typing import List
from dotenv import load_dotenv
from vestaboard import VestaboardMessenger
from weather_app.weather_header import WeatherHeader
from .weather import WeatherNow, WeatherClient, format_weather_line
from . import utils

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
)

logger = logging.getLogger()

def run():
    logger.info("Weather job started")

    load_dotenv()

    wc = WeatherClient()
    weather_header = WeatherHeader()
    vb = VestaboardMessenger()
    weather_data = List[WeatherNow]

    try:
        weather_data = wc.get_current_weather_multi_cities()
        logger.info(f"Successfully retrieved weather info:\n{weather_data}")
    except Exception as e:
        logger.exception(f"Error retrieving weather info: {e}")

    vbml_components = []
    for hc in weather_header.compose_header_components():
        vbml_components.append(hc)

    for now in weather_data:
        weather_string = "{67}" + format_weather_line(now)
        component = utils.compose_vbml_component(weather_string)
        vbml_components.append(component)

    vbml_payload = utils.compose_vbml_payload(vbml_components)
    print(vbml_payload)
    vbml_layout = vb.vbml_compose_layout(vbml_payload)

    try:
        vb.send_layout(vbml_layout)
        logger.info(f"Message sent:\n{vbml_layout}")
    except Exception as e:
        logger.exception(f"Error sending message: {e}")


if __name__ == "__main__":
    run()