import logging
import random
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import requests

from flight_app.models import FlightInfo, GeoBounds, unix_to_utc


logger = logging.getLogger(__name__)


class OpenSkyClient:
    BASE_URL = "https://opensky-network.org/api/states/all"
    TOKEN_URL = (
        "https://auth.opensky-network.org/auth/realms/opensky-network/"
        "protocol/openid-connect/token"
    )
    TOKEN_REFRESH_MARGIN_S = 30

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout_s: int = 60,
        retry_attempts: int = 10,
        retry_base_delay_s: float = 0.8,
        retry_max_delay_s: float = 8.0,
        session: requests.Session | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout_s = timeout_s
        self.retry_attempts = retry_attempts
        self.retry_base_delay_s = retry_base_delay_s
        self.retry_max_delay_s = retry_max_delay_s
        self._session = session or requests.Session()
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    def _sleep_backoff(self, attempt: int, *, retry_after_s: float | None = None) -> None:
        if retry_after_s is not None:
            time.sleep(max(0.0, retry_after_s))
            return

        backoff = min(self.retry_max_delay_s, self.retry_base_delay_s * (2 ** (attempt - 1)))
        jitter = random.uniform(0.0, 0.5)
        time.sleep(backoff + jitter)

    def get_flights_in_bounds(self, bounds: GeoBounds) -> list[FlightInfo]:
        logger.info(
            "Fetching OpenSky flights in bounds: params=%s auth=%s timeout_s=%s retry_attempts=%s",
            bounds.as_params(),
            "enabled" if self._uses_auth() else "disabled",
            self.timeout_s,
            self.retry_attempts,
        )
        payload = self._request_json(bounds.as_params())
        states = payload.get("states") or []
        flights = [self._parse_state(state) for state in states]
        logger.info(
            "Parsed OpenSky states: raw_states=%d parsed_flights=%d",
            len(states),
            len(flights),
        )
        return flights

    def _request_json(self, params: dict[str, float]) -> dict[str, Any]:
        last_err: Exception | None = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                logger.info(
                    "OpenSky states request attempt %d/%d started",
                    attempt,
                    self.retry_attempts,
                )
                resp = self._session.get(
                    self.BASE_URL,
                    params=params,
                    headers=self._auth_headers(),
                    timeout=self.timeout_s,
                )
                self._log_response("OpenSky states response", resp)

                if resp.status_code == 401 and self._uses_auth():
                    logger.warning(
                        "OpenSky states request returned 401 with credentials; "
                        "refreshing token and retrying once."
                    )
                    resp = self._session.get(
                        self.BASE_URL,
                        params=params,
                        headers=self._auth_headers(force_refresh=True),
                        timeout=self.timeout_s,
                    )
                    self._log_response("OpenSky states response after token refresh", resp)

                if resp.status_code >= 400:
                    retry_after_s = self._parse_retry_after(resp)
                    if (
                        self._is_retryable_status(resp.status_code)
                        and attempt < self.retry_attempts
                    ):
                        logger.warning(
                            "OpenSky states request failed with retryable status=%d "
                            "attempt=%d/%d retry_after_s=%s body_excerpt=%r",
                            resp.status_code,
                            attempt,
                            self.retry_attempts,
                            retry_after_s,
                            self._response_excerpt(resp),
                        )
                        self._sleep_backoff(attempt, retry_after_s=retry_after_s)
                        continue

                    logger.error(
                        "OpenSky states request failed with status=%d body_excerpt=%r",
                        resp.status_code,
                        self._response_excerpt(resp),
                    )
                    resp.raise_for_status()

                try:
                    payload = resp.json()
                except ValueError:
                    logger.error(
                        "OpenSky states response was not valid JSON: status=%d body_excerpt=%r",
                        resp.status_code,
                        self._response_excerpt(resp),
                    )
                    raise

                logger.info(
                    "OpenSky states payload decoded: keys=%s states_count=%s api_time=%s",
                    sorted(payload.keys()),
                    len(payload.get("states") or []),
                    payload.get("time"),
                )
                return payload

            except (requests.Timeout, requests.ConnectionError, ValueError) as e:
                last_err = e
                logger.warning(
                    "OpenSky states request attempt %d/%d raised %s: %s",
                    attempt,
                    self.retry_attempts,
                    type(e).__name__,
                    e,
                    exc_info=attempt >= self.retry_attempts,
                )
                if attempt >= self.retry_attempts:
                    break
                self._sleep_backoff(attempt)

            except requests.HTTPError as e:
                last_err = e
                logger.exception(
                    "OpenSky states request failed with non-retryable HTTP error on attempt %d/%d",
                    attempt,
                    self.retry_attempts,
                )
                break

        assert last_err is not None
        logger.error(
            "OpenSky states request exhausted retries; raising last error: %s: %s",
            type(last_err).__name__,
            last_err,
        )
        raise last_err

    def _uses_auth(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _auth_headers(self, *, force_refresh: bool = False) -> dict[str, str] | None:
        if not self._uses_auth():
            return None

        token = self._get_token(force_refresh=force_refresh)
        return {"Authorization": f"Bearer {token}"}

    def _get_token(self, *, force_refresh: bool = False) -> str:
        now = datetime.now()
        if (
            not force_refresh
            and self._access_token
            and self._token_expires_at
            and now < self._token_expires_at
        ):
            logger.debug("Using cached OpenSky access token.")
            return self._access_token

        logger.info(
            "OpenSky token request started: force_refresh=%s client_id_set=%s client_secret_set=%s",
            force_refresh,
            bool(self.client_id),
            bool(self.client_secret),
        )
        resp = self._session.post(
            self.TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=self.timeout_s,
        )
        self._log_response("OpenSky token response", resp)
        if resp.status_code >= 400:
            logger.error(
                "OpenSky token request failed with status=%d body_excerpt=%r",
                resp.status_code,
                self._response_excerpt(resp),
            )
        resp.raise_for_status()

        try:
            data = resp.json()
        except ValueError:
            logger.error(
                "OpenSky token response was not valid JSON: status=%d body_excerpt=%r",
                resp.status_code,
                self._response_excerpt(resp),
            )
            raise

        if "access_token" not in data:
            logger.error(
                "OpenSky token response missing access_token: keys=%s",
                sorted(data.keys()),
            )

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 1800))
        self._token_expires_at = now + timedelta(
            seconds=max(0, expires_in - self.TOKEN_REFRESH_MARGIN_S)
        )
        logger.info(
            "OpenSky token cached: expires_in_s=%d refresh_at=%s",
            expires_in,
            self._token_expires_at.isoformat(),
        )
        return self._access_token

    @staticmethod
    def _parse_retry_after(resp: requests.Response) -> float | None:
        value = resp.headers.get("Retry-After")
        if value is None:
            return None

        try:
            return float(value)
        except ValueError:
            return None

    @staticmethod
    def _response_excerpt(resp: requests.Response, *, limit: int = 500) -> str:
        try:
            body = resp.text
        except Exception as e:
            return f"<unable to read response body: {type(e).__name__}>"

        body = " ".join(body.split())
        if len(body) <= limit:
            return body
        return f"{body[:limit]}..."

    @staticmethod
    def _log_response(message: str, resp: requests.Response) -> None:
        logger.info(
            "%s: status=%d elapsed_ms=%d retry_after=%s content_type=%s",
            message,
            resp.status_code,
            round(resp.elapsed.total_seconds() * 1000),
            resp.headers.get("Retry-After"),
            resp.headers.get("Content-Type"),
        )

    @staticmethod
    def _parse_state(state: list[Any]) -> FlightInfo:
        def at(index: int) -> Any:
            if index >= len(state):
                return None
            return state[index]

        callsign = at(1)
        if isinstance(callsign, str):
            callsign = callsign.strip() or None

        return FlightInfo(
            icao24=at(0),
            callsign=callsign,
            origin_country=at(2),
            longitude=at(5),
            latitude=at(6),
            baro_altitude_m=at(7),
            on_ground=bool(at(8)),
            velocity_mps=at(9),
            true_track_deg=at(10),
            vertical_rate_mps=at(11),
            geo_altitude_m=at(13),
            squawk=at(14),
            last_contact=unix_to_utc(at(4)),
            category=at(17),
        )
