import os
import time
import random
import json
from contextlib import AbstractContextManager, nullcontext
import requests
from typing import Any, Callable, Dict, Optional, List, Tuple
from vestaboard.transitions import Transition, TransitionSpeed


class VestaboardMessenger:
    """Small helper for interacting with the Vestaboard Read/Write API.

    Expects the environment variable `VB_RW_API_KEY` to be set.

    API docs:
      - GET  https://rw.vestaboard.com/   -> returns current message
      - POST https://rw.vestaboard.com/   -> sets message (e.g., {"text": "..."})

    Note: Vestaboard recommends not sending more often than ~1 message / 15 seconds.
    """

    VESTABOARD_URL = "https://cloud.vestaboard.com/"
    TRANSITION_URL = "https://cloud.vestaboard.com/transition"
    VBML_URL_FORMAT = "https://vbml.vestaboard.com/format"
    VBML_URL_COMPOSE = "https://vbml.vestaboard.com/compose"
    HEADER_NAME = "X-Vestaboard-Token"

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_s: int = 10,
        retry_attempts: int = 5,
        retry_base_delay_s: float = 0.8,
        retry_max_delay_s: float = 10.0,
        session: requests.Session | None = None,
        write_guard: Callable[[bool], AbstractContextManager] | None = None,
        retry_sleep: Callable[[float], None] | None = None,
    ):
        self.api_key = api_key or os.getenv("VB_RW_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Missing Vestaboard Read/Write key. Set env var VB_RW_API_KEY "
                "or pass api_key=... to VestaboardMessenger()."
            )

        self.timeout_s = timeout_s
        self.retry_attempts = retry_attempts
        self.retry_base_delay_s = retry_base_delay_s
        self.retry_max_delay_s = retry_max_delay_s
        self._session = session or requests.Session()
        # The display worker supplies lease/cooldown handling for every attempt.
        self.write_guard = write_guard
        self.retry_sleep = retry_sleep
        self.headers = {
            "Content-Type": "application/json",
            self.HEADER_NAME: self.api_key,
        }

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    def _sleep_backoff(self, attempt: int, *, retry_after_s: float | None = None) -> None:
        sleep = self.retry_sleep or time.sleep
        # Prefer server-provided Retry-After when present.
        if retry_after_s is not None:
            sleep(max(0.0, retry_after_s))
            return

        backoff = min(self.retry_max_delay_s, self.retry_base_delay_s * (2 ** (attempt - 1)))
        jitter = random.uniform(0.0, 0.5)
        sleep(backoff + jitter)

    def _request_json(self, method: str, url: str, *, json: Any | None = None) -> Any:
        """Make an HTTP request with retries and return parsed JSON."""
        last_err: Exception | None = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                is_content_write = method == "POST" and url == self.VESTABOARD_URL
                is_transition_write = method == "PUT" and url == self.TRANSITION_URL
                guard = (
                    self.write_guard(is_content_write)
                    if self.write_guard and (is_content_write or is_transition_write)
                    else nullcontext()
                )
                # Include each retry and ambiguous timeout in the same timing gate.
                with guard:
                    resp = self._session.request(
                        method,
                        url,
                        headers=self.headers,
                        json=json,
                        timeout=self.timeout_s,
                    )

                # Intercept 409 Conflict (Message already displayed)
                if resp.status_code == 409:
                    try:
                        return resp.json()
                    except ValueError:
                        return {
                            "status": "skipped",
                            "detail": "Message already displayed on the board (409 Conflict)."
                        }

                # Retry on transient HTTP status codes
                if resp.status_code >= 400:
                    retry_after_s: float | None = None
                    if "Retry-After" in resp.headers:
                        try:
                            retry_after_s = float(resp.headers["Retry-After"])
                        except ValueError:
                            retry_after_s = None

                    if self._is_retryable_status(resp.status_code) and attempt < self.retry_attempts:
                        self._sleep_backoff(attempt, retry_after_s=retry_after_s)
                        continue

                    resp.raise_for_status()

                return resp.json()

            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = e
                if attempt >= self.retry_attempts:
                    break
                self._sleep_backoff(attempt)

            except ValueError as e:
                last_err = e
                if attempt >= self.retry_attempts:
                    break
                self._sleep_backoff(attempt)

            except requests.HTTPError as e:
                last_err = e
                break

        assert last_err is not None
        raise last_err

    def get_message(self) -> Dict[str, Any]:
        """Fetch the current message shown on the Vestaboard."""
        response = self._request_json("GET", self.VESTABOARD_URL)

        current_message = response.get("currentMessage", {})
        layout = current_message.get("layout")

        if isinstance(layout, str):
            try:
                layout = json.loads(layout)
            except json.JSONDecodeError:
                pass

        return {
            "layout": layout,
            "id": current_message.get("id"),
            "raw": response,
        }

    def send_message(self, message: str) -> Dict[str, Any]:
        """Send a plain-text message to the Vestaboard."""
        payload = {"text": message}
        return self._request_json("POST", self.VESTABOARD_URL, json=payload)

    def send_layout(self, layout: List[List]) -> Dict[str, Any]:
        """Send a pre-formatted layout (character-code array).
        """
        return self._request_json("POST", self.VESTABOARD_URL, json=layout)

    def get_transition(self) -> Dict[str, Transition | TransitionSpeed]:
        """Fetch the current transition settings for the Vestaboard."""
        response = self._request_json("GET", self.TRANSITION_URL)

        return {
            "transition": Transition(response["transition"]),
            "transitionSpeed": TransitionSpeed(response["transitionSpeed"]),
        }

    def set_transition(self, transition: Transition, transition_speed: TransitionSpeed)\
            -> Tuple[Transition, TransitionSpeed]:
        """Update the Vestaboard transition settings."""
        payload = {
            "transition": transition.value,
            "transitionSpeed": transition_speed.value,
        }

        response = self._request_json("PUT", self.TRANSITION_URL, json=payload)

        current_transition = Transition(response["transition"])
        current_speed = TransitionSpeed(response["transitionSpeed"])

        return current_transition, current_speed

    def vbml_format_message(self, message: str) -> List[List]:
        payload = {"message": message}
        return self._request_json("POST", self.VBML_URL_FORMAT, json=payload)

    def vbml_compose_layout(self, payload) -> List[List]:
        return self._request_json("POST", self.VBML_URL_COMPOSE, json=payload)
