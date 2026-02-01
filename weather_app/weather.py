import os
import time
import random
from dataclasses import dataclass
from typing import Dict, Any, List
from retry_requests import retry

import requests
import openmeteo_requests
import requests_cache

from weather_app.cities import CITY_COORDS

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
        retry_attempts: int = 5,
        retry_base_delay_s: float = 0.8,
        retry_max_delay_s: float = 10.0,
        session: requests.Session | None = None,
    ):
        self.cities_coords = CITY_COORDS
        self.temp_unit = temp_unit
        self.wind_unit = wind_unit

        if self.temp_unit not in {"fahrenheit", "celsius"}:
            raise ValueError("WEATHER_UNIT must be 'fahrenheit' or 'celsius'")
        if self.wind_unit not in {"mph", "kmh"}:
            raise ValueError("WEATHER_WIND_UNIT must be 'mph' or 'kmh'")

        self.timeout_s = timeout_s
        self.retry_attempts = retry_attempts
        self.retry_base_delay_s = retry_base_delay_s
        self.retry_max_delay_s = retry_max_delay_s
        self._session = session or requests.Session()

        self.cache_session = requests_cache.CachedSession('.cache', expire_after=500)
        self.retry_session = retry(self.cache_session, retries=5, backoff_factor=0.2)
        self.client = openmeteo_requests.Client(session=self.retry_session)

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        # Transient server-side or throttling
        return status_code in {429, 500, 502, 503, 504}

    def _sleep_backoff(self, attempt: int) -> None:
        # Exponential backoff + small jitter
        backoff = min(self.retry_max_delay_s, self.retry_base_delay_s * (2 ** (attempt - 1)))
        jitter = random.uniform(0.0, 0.5)
        time.sleep(backoff + jitter)

    def get_current_weather(self) -> list[WeatherNow]:
        results: List[WeatherNow] = []

        for city, (lat, lon) in self.cities_coords.items():
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": ["temperature_2m", "wind_speed_10m", "weather_code"],
                "temperature_unit": self.temp_unit,
                "windspeed_unit": "kmh" if self.wind_unit == "kmh" else "mph",
                "timezone": "auto",
            }

            responses = self.client.weather_api(self.BASE_URL, params=params)
            response = responses[0]

            results.append(self._parse_current_to_weather_now(response=response, city=city))

        return results

    def _parse_current_to_weather_now(self, response, city: str) -> WeatherNow:
        """
        Convert Open-Meteo response object into WeatherNow.
        """
        current = response.Current()

        temperature = float(current.Variables(0).Value())
        wind_speed = int(round(float(current.Variables(1).Value())))
        weather_code = int(current.Variables(2).Value())

        unit = "C" if self.temp_unit == "celsius" else "F"
        condition = self._weathercode_to_text(weather_code)

        return WeatherNow(
            city=city,
            temperature=temperature,
            unit=unit,
            condition=condition,
            wind_speed=wind_speed,
            wind_unit=self.wind_unit,
        )

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