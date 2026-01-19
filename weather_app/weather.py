import os
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from weather_app.cities import CITY_COORDS
import requests

@dataclass(frozen=True)
class WeatherNow:
    city: str
    temperature: int
    unit: str
    condition: str
    wind_speed: int
    wind_unit: str


class WeatherClient:
    """
    Fetches current weather using Open-Meteo (no API key required).

    Env configuration:
      - WEATHER_LAT (default: 47.67)
      - WEATHER_LON (default: -122.12)
      - WEATHER_CITY (default: "SEATTLE")
      - WEATHER_UNIT ("fahrenheit" or "celsius", default: "fahrenheit")
      - WEATHER_WIND_UNIT ("mph" or "kmh", default: "mph")

    Docs: https://open-meteo.com/
    """

    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(
        self,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        city: Optional[str] = None,
        temp_unit: Optional[str] = None,   # "fahrenheit" | "celsius"
        wind_unit: Optional[str] = None,   # "mph" | "kmh"
        timeout_s: int = 10,
    ):
        self.lat = lat if lat is not None else float(os.getenv("WEATHER_LAT", "47.67"))
        self.lon = lon if lon is not None else float(os.getenv("WEATHER_LON", "-122.12"))
        self.city = (city if city is not None else os.getenv("WEATHER_CITY", "SEATTLE")).strip().upper()
        self.cities_coords = CITY_COORDS

        self.temp_unit = (temp_unit if temp_unit is not None else os.getenv("WEATHER_UNIT", "fahrenheit")).strip().lower()
        self.wind_unit = (wind_unit if wind_unit is not None else os.getenv("WEATHER_WIND_UNIT", "mph")).strip().lower()

        if self.temp_unit not in {"fahrenheit", "celsius"}:
            raise ValueError("WEATHER_UNIT must be 'fahrenheit' or 'celsius'")
        if self.wind_unit not in {"mph", "kmh"}:
            raise ValueError("WEATHER_WIND_UNIT must be 'mph' or 'kmh'")

        self.timeout_s = timeout_s

    def get_current_weather(self) -> WeatherNow:
        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "current_weather": "true",
            "temperature_unit": self.temp_unit,
            "windspeed_unit": "mph" if self.wind_unit == "mph" else "kmh",
            "timezone": "auto",
        }

        resp = requests.get(self.BASE_URL, params=params, timeout=self.timeout_s)
        resp.raise_for_status()

        data: Dict[str, Any] = resp.json()
        cw = data.get("current_weather")
        if not cw:
            raise RuntimeError(f"Unexpected response: missing 'current_weather': {data}")

        temp = int(round(cw["temperature"]))
        wind = int(round(cw["windspeed"]))
        code = int(cw.get("weathercode", -1))

        condition = self._weathercode_to_text(code)
        unit = "F" if self.temp_unit == "fahrenheit" else "C"
        wind_unit = "mph" if self.wind_unit == "mph" else "km/h"

        return WeatherNow(
            city=self.city,
            temperature=temp,
            unit=unit,
            condition=condition,
            wind_speed=wind,
            wind_unit=wind_unit,
        )

    def get_current_weather_multi_cities(self):
        results: List[WeatherNow] = []

        for city, (lat, lon) in self.cities_coords.items():
            client = WeatherClient(
                lat=lat,
                lon=lon,
                city=city,
                temp_unit=self.temp_unit,
                wind_unit=self.wind_unit,
                timeout_s=self.timeout_s,
            )
            results.append(client.get_current_weather())

        return results

    @staticmethod
    def _weathercode_to_text(code: int) -> str:
        """
        Open-Meteo weather codes: simplified to short, board-friendly labels.
        """
        mapping: Dict[int, str] = {
            0: "CLEAR",
            1: "MOSTLY CLEAR",
            2: "PARTLY CLOUDY",
            3: "CLOUDY",
            45: "FOG",
            48: "RIME FOG",
            51: "LGT DRIZZLE",
            53: "DRIZZLE",
            55: "HVY DRIZZLE",
            56: "LGT FRZ DRZ",
            57: "FRZ DRIZZLE",
            61: "LGT RAIN",
            63: "RAIN",
            65: "HVY RAIN",
            66: "LGT FRZ RAIN",
            67: "FRZ RAIN",
            71: "LGT SNOW",
            73: "SNOW",
            75: "HVY SNOW",
            77: "SNOW GRAINS",
            80: "LGT SHOWERS",
            81: "SHOWERS",
            82: "HVY SHOWERS",
            85: "LGT SNOW SHWRS",
            86: "SNOW SHWRS",
            95: "T-STORM",
            96: "T-STORM HAIL",
            99: "SVR T-STORM",
        }

        return mapping.get(code, "UNKNOWN")


def format_weather_line(now: WeatherNow) -> str:
    """
    Returns a short message suitable for Vestaboard text mode.
    Example: 'SEATTLE 52F LIGHT RAIN'
    """
    return f"{now.city} {now.temperature}{now.unit} {now.condition}"