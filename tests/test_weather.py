import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, call, patch

from weather_app.weather import WeatherClient


class Values(list):
    def __getitem__(self, item):
        result = super().__getitem__(item)
        return Values(result) if isinstance(item, slice) else result

    def max(self) -> float:
        return max(self)


class WeatherClientTests(unittest.TestCase):
    def test_get_detailed_weather_separates_current_and_daily_data(self) -> None:
        response = self._weather_response()
        air_quality_response = self._air_quality_response(42.4)
        api_client = Mock()
        api_client.weather_api.side_effect = [
            [response],
            [air_quality_response],
        ]

        client = WeatherClient.__new__(WeatherClient)
        client.client = api_client
        client.temp_unit = "fahrenheit"
        client.wind_unit = "mph"

        detailed = client.get_detailed_weather(
            "WOODINVILLE",
            47.75,
            -122.16,
        )

        self.assertEqual(detailed.city, "WOODINVILLE")
        self.assertEqual(detailed.temperature_unit, "F")
        self.assertEqual(detailed.current.temperature, 72.5)
        self.assertEqual(detailed.current.apparent_temperature, 71.25)
        self.assertEqual(detailed.current.condition, "PARTLY CLOUDY")
        self.assertEqual(detailed.current.uv_index, 3.2)
        self.assertEqual(detailed.current.us_aqi, 42)
        self.assertEqual(detailed.today.maximum_temperature, 78.0)
        self.assertEqual(detailed.today.minimum_temperature, 58.0)
        self.assertEqual(detailed.today.maximum_uv_index, 6.5)
        self.assertEqual(detailed.today.maximum_precipitation_probability, 35.0)
        self.assertEqual(
            detailed.today.sunrise,
            datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            detailed.today.next_sunrise,
            datetime(2026, 8, 7, 12, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(
            api_client.weather_api.call_args_list,
            [
                call(
                    WeatherClient.BASE_URL,
                    params={
                        "latitude": 47.75,
                        "longitude": -122.16,
                        "current": [
                            "temperature_2m",
                            "apparent_temperature",
                            "weather_code",
                            "uv_index",
                        ],
                        "daily": [
                            "temperature_2m_max",
                            "temperature_2m_min",
                            "uv_index_max",
                            "precipitation_probability_max",
                            "sunrise",
                            "sunset",
                        ],
                        "forecast_days": 2,
                        "temperature_unit": "fahrenheit",
                        "timezone": "auto",
                    },
                ),
                call(
                    WeatherClient.AIR_QUALITY_URL,
                    params={
                        "latitude": 47.75,
                        "longitude": -122.16,
                        "current": ["us_aqi"],
                        "timezone": "auto",
                        "forecast_days": 1,
                    },
                ),
            ],
        )

    @patch("weather_app.weather.logger")
    def test_get_detailed_weather_keeps_weather_when_aqi_fails(
        self,
        logger: Mock,
    ) -> None:
        api_client = Mock()
        api_client.weather_api.side_effect = [
            [self._weather_response()],
            RuntimeError("AQI unavailable"),
        ]

        client = WeatherClient.__new__(WeatherClient)
        client.client = api_client
        client.temp_unit = "celsius"
        client.wind_unit = "kmh"

        detailed = client.get_detailed_weather("WOODINVILLE", 47.75, -122.16)

        self.assertIsNone(detailed.current.us_aqi)
        logger.warning.assert_called_once_with(
            "Unable to retrieve current AQI",
            exc_info=True,
        )

    @staticmethod
    def _weather_response() -> Mock:
        current_values = [72.5, 71.25, 2, 3.2]
        daily_values = [
            Values([78.0, 79.0]),
            Values([58.0, 59.0]),
            Values([6.5, 6.0]),
            Values([35.0, 20.0]),
            Values([1786017600, 1786104060]),
            Values([1786072500, 1786158840]),
        ]

        current = Mock()
        current_variables = [
            Mock(Value=Mock(return_value=value)) for value in current_values
        ]
        current.Variables.side_effect = lambda index: current_variables[index]

        daily = Mock()
        daily_variables = []
        for index, values in enumerate(daily_values):
            variable = Mock()
            if index < 4:
                variable.ValuesAsNumpy.return_value = values
            else:
                variable.ValuesInt64AsNumpy.return_value = values
            daily_variables.append(variable)
        daily.Variables.side_effect = lambda index: daily_variables[index]

        response = Mock()
        response.Current.return_value = current
        response.Daily.return_value = daily
        response.UtcOffsetSeconds.return_value = 0
        return response

    @staticmethod
    def _air_quality_response(us_aqi: float) -> Mock:
        variable = Mock()
        variable.Value.return_value = us_aqi

        current = Mock()
        current.Variables.return_value = variable

        response = Mock()
        response.Current.return_value = current
        return response


if __name__ == "__main__":
    unittest.main()
