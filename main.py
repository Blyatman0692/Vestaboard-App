import os
import sys
import utils
import weather

from vestaboard import VestaboardMessenger
from weather import WeatherClient

def main() -> int:
    try:
        vb = VestaboardMessenger()
        wc = WeatherClient()

        w = wc.get_current_weather()
        message = weather.format_weather_line(w)

        try:
            current = vb.get_message()
            current_text = (current.get("text") or "").strip()
        except Exception:
            current_text = ""

        if current_text == message.strip():
            print(f"No change. Board already shows: {message}")
            return 0

        vb.send_message(message)
        print(f"Sent to Vestaboard: {message}")
        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())