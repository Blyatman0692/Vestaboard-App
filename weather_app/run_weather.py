import logging
import os


import weather
from typing import List
from dotenv import load_dotenv
from vestaboard import VestaboardMessenger
from weather_app.weather import WeatherNow

LOG_FILE = "/var/log/mycron.log"

logging.basicConfig(
    filename="/Users/zjw/Desktop/Vestaboard App/weather_cron.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger()

def run():
    logger.info("Weather job started")

    load_dotenv()

    wc = weather.WeatherClient()
    vb = VestaboardMessenger()
    weather_data = List[WeatherNow]

    try:
        weather_data = wc.get_current_weather_multi_cities()
        logger.info(f"Successfully retrieved weather info:\n{weather_data}")
    except Exception as e:
        logger.exception(f"Error retrieving weather info: {e}")

    message = ""
    for now in weather_data:
        message += weather.format_weather_line(now) + "\n"
    try:
        vb.send_message(message)
        logger.info(f"Message sent:\n{message}")
    except Exception as e:
        logger.exception(f"Error sending message: {e}")


if __name__ == "__main__":
    run()