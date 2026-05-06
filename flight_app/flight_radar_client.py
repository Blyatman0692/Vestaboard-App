import random
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class FlightPosition:
    fr24_id: str
    flight: str | None
    callsign: str | None
    lat: float
    lon: float
    track: int
    alt: int
    gspeed: int
    vspeed: int
    squawk: str
    timestamp: str
    source: str
    hex: str | None
    aircraft_type: str | None
    reg: str | None
    painted_as: str | None
    operating_as: str | None
    orig_iata: str | None
    orig_icao: str | None
    dest_iata: str | None
    dest_icao: str | None
    eta: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "FlightPosition":
        return cls(
            fr24_id=data["fr24_id"],
            flight=data.get("flight"),
            callsign=data.get("callsign"),
            lat=float(data["lat"]),
            lon=float(data["lon"]),
            track=int(data["track"]),
            alt=int(data["alt"]),
            gspeed=int(data["gspeed"]),
            vspeed=int(data["vspeed"]),
            squawk=str(data["squawk"]),
            timestamp=data["timestamp"],
            source=data["source"],
            hex=data.get("hex"),
            aircraft_type=data.get("type"),
            reg=data.get("reg"),
            painted_as=data.get("painted_as"),
            operating_as=data.get("operating_as"),
            orig_iata=data.get("orig_iata"),
            orig_icao=data.get("orig_icao"),
            dest_iata=data.get("dest_iata"),
            dest_icao=data.get("dest_icao"),
            eta=data.get("eta"),
        )

    @property
    def display_name(self) -> str:
        return self.flight or self.callsign or self.reg or self.fr24_id

    @property
    def route(self) -> str:
        origin = self.orig_iata or self.orig_icao or "?"
        destination = self.dest_iata or self.dest_icao or "?"
        return f"{origin}->{destination}"


class FlightRadarApiError(RuntimeError):
    def __init__(self, status_code: int, message: str, details: str | None = None):
        self.status_code = status_code
        self.message = message
        self.details = details

        error = f"FR24 API error {status_code}: {message}"
        if details:
            error = f"{error} ({details})"
        super().__init__(error)


class FlightRadarClient:
    BASE_URL = "https://fr24api.flightradar24.com"
    LIVE_POSITIONS_FULL_PATH = "/api/live/flight-positions/full"

    def __init__(
        self,
        api_token: str,
        *,
        base_url: str = BASE_URL,
        api_version: str = "v1",
        timeout_s: int = 10,
        retry_attempts: int = 3,
        retry_base_delay_s: float = 0.8,
        retry_max_delay_s: float = 10.0,
        session: requests.Session | None = None,
    ):
        if not api_token:
            raise ValueError("Missing FR24 API token. Set FR24_API_TOKEN or pass api_token=...")

        self.api_token = api_token
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.timeout_s = timeout_s
        self.retry_attempts = retry_attempts
        self.retry_base_delay_s = retry_base_delay_s
        self.retry_max_delay_s = retry_max_delay_s
        self._session = session or requests.Session()

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Accept-Version": self.api_version,
            "Authorization": f"Bearer {self.api_token}",
        }

    def get_live_positions_full(
        self,
        *,
        bounds: str | None = None,
        limit: int | None = None,
        flights: str | None = None,
        callsigns: str | None = None,
        registrations: str | None = None,
        painted_as: str | None = None,
        operating_as: str | None = None,
        airports: str | None = None,
        routes: str | None = None,
        aircraft: str | None = None,
        altitude_ranges: str | None = None,
        squawks: str | None = None,
        categories: str | None = None,
        data_sources: str | None = None,
        airspaces: str | None = None,
        gspeed: str | None = None,
    ) -> list[FlightPosition]:
        filters = {
            "bounds": bounds,
            "flights": flights,
            "callsigns": callsigns,
            "registrations": registrations,
            "painted_as": painted_as,
            "operating_as": operating_as,
            "airports": airports,
            "routes": routes,
            "aircraft": aircraft,
            "altitude_ranges": altitude_ranges,
            "squawks": squawks,
            "categories": categories,
            "data_sources": data_sources,
            "airspaces": airspaces,
            "gspeed": gspeed,
        }
        params = {key: value for key, value in filters.items() if value is not None}

        if not params:
            raise ValueError("At least one FR24 live positions filter is required.")

        if limit is not None:
            if limit <= 0 or limit > 30000:
                raise ValueError("FR24 live positions limit must be between 1 and 30000.")
            params["limit"] = limit

        payload = self._get_json(self.LIVE_POSITIONS_FULL_PATH, params=params)
        return [FlightPosition.from_api(item) for item in payload.get("data", [])]

    def _get_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_err: Exception | None = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                response = self._session.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=self.timeout_s,
                )

                if response.status_code >= 400:
                    if self._is_retryable_status(response.status_code) and attempt < self.retry_attempts:
                        self._sleep_backoff(attempt, response=response)
                        continue

                    raise self._api_error(response)

                return response.json()

            except (requests.Timeout, requests.ConnectionError) as exc:
                last_err = exc
                if attempt >= self.retry_attempts:
                    break
                self._sleep_backoff(attempt)

            except ValueError as exc:
                last_err = exc
                break

        assert last_err is not None
        raise last_err

    def _sleep_backoff(
        self,
        attempt: int,
        *,
        response: requests.Response | None = None,
    ) -> None:
        retry_after_s = None
        if response is not None and "Retry-After" in response.headers:
            try:
                retry_after_s = float(response.headers["Retry-After"])
            except ValueError:
                retry_after_s = None

        if retry_after_s is not None:
            time.sleep(max(0.0, retry_after_s))
            return

        backoff = min(self.retry_max_delay_s, self.retry_base_delay_s * (2 ** (attempt - 1)))
        jitter = random.uniform(0.0, 0.5)
        time.sleep(backoff + jitter)

    @staticmethod
    def _api_error(response: requests.Response) -> FlightRadarApiError:
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        message = payload.get("message") or response.reason or "Request failed"
        details = payload.get("details") or response.text or None
        return FlightRadarApiError(response.status_code, message, details)
