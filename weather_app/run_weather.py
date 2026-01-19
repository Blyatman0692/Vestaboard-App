from dotenv import load_dotenv
import weather
from vestaboard import VestaboardMessenger

def run():
    load_dotenv()

    wc = weather.WeatherClient()
    vb = VestaboardMessenger()

    weather_data = wc.get_current_weather_multi_cities()

    message = ""
    for now in weather_data:
        message += weather.format_weather_line(now) + "\n"

    vb.send_message(message)

if __name__ == "__main__":
    run()