import os
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from weather_app.cities import CITY_COORDS
import requests

@dataclass(frozen=True)
class WeatherNow:
    city: str
    temperature: float
    unit: str
    condition: str
    wind_speed: int
    wind_unit: str


class WeatherClient:
    """
    Fetches current weather using Open-Meteo (no API key required).
    Docs: https://open-meteo.com/
    """

    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(
        self,
        temp_unit: str = "celsius",
        wind_unit: str = "kmh",
        timeout_s: int = 10,
    ):
        self.cities_coords = CITY_COORDS
        self.temp_unit = temp_unit
        self.wind_unit = wind_unit

        if self.temp_unit not in {"fahrenheit", "celsius"}:
            raise ValueError("WEATHER_UNIT must be 'fahrenheit' or 'celsius'")
        if self.wind_unit not in {"mph", "kmh"}:
            raise ValueError("WEATHER_WIND_UNIT must be 'mph' or 'kmh'")

        self.timeout_s = timeout_s

    def get_current_weather(self, lat, lon, city) -> WeatherNow:
        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "temperature_unit": self.temp_unit,
            "windspeed_unit": "kmh" if self.wind_unit == "kmh" else "mph",
            "timezone": "auto",
        }

        resp = requests.get(self.BASE_URL, params=params, timeout=self.timeout_s)
        resp.raise_for_status()

        data: Dict[str, Any] = resp.json()
        print(data)
        cw = data.get("current_weather")
        if not cw:
            raise RuntimeError(f"Unexpected response: missing 'current_weather': {data}")

        temp = float(round(cw["temperature"], 1))
        wind = int(round(cw["windspeed"]))
        code = int(cw.get("weathercode", -1))

        condition = self._weathercode_to_text(code)
        unit = "C" if self.temp_unit == "celsius" else "F"
        wind_unit = "kmh" if self.wind_unit == "kmh" else "mph"

        return WeatherNow(
            city=city,
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
                temp_unit=self.temp_unit,
                wind_unit=self.wind_unit,
                timeout_s=self.timeout_s,
            )
            results.append(client.get_current_weather(lat, lon, city))

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
    Returns a fixed-width (21 chars) Vestaboard-friendly line.

    Layout:
    [CITY................][TEMP]
    City: left-aligned
    Temperature: right-aligned, always 2 digits
    """

    TOTAL_WIDTH = 21
    TEMP_WIDTH = 5  # e.g. 12.4C

    # Normalize temperature to 2 digits
    temp = f"{now.temperature:4.1f}{now.unit}"

    city = now.city.upper()

    # Truncate city if too long
    max_city_len = TOTAL_WIDTH - TEMP_WIDTH
    city = city[:max_city_len]

    # Build fixed-width line
    line = f"{city}{' ' * (TOTAL_WIDTH - len(city) - TEMP_WIDTH)}{temp}"

    # Safety trim
    return line[:TOTAL_WIDTH]