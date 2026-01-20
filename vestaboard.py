from http.client import responses
from dotenv import load_dotenv
import os
from typing import Any, Dict, Optional, List
from pathlib import Path
import requests


class VestaboardMessenger:
    """Small helper for interacting with the Vestaboard Read/Write API.

    Expects the environment variable `VESTABOARD_RW_KEY` to be set.

    API docs:
      - GET  https://rw.vestaboard.com/   -> returns current message
      - POST https://rw.vestaboard.com/   -> sets message (e.g., {"text": "..."})

    Note: Vestaboard recommends not sending more often than ~1 message / 15 seconds.
    """

    VESTABOARD_URL = "https://rw.vestaboard.com/"
    VBML_URL_FORMAT = "https://vbml.vestaboard.com/format"
    VBML_URL_COMPOSE = "https://vbml.vestaboard.com/compose"
    HEADER_NAME = "X-Vestaboard-Read-Write-Key"

    def __init__(self, api_key: Optional[str] = None, timeout_s: int = 10):
        env_path = Path(__file__).parent / ".env"
        load_dotenv(dotenv_path=env_path)

        self.api_key = api_key or os.getenv("VB_RW_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Missing Vestaboard Read/Write key. Set env var VB_RW_API_KEY "
                "or pass api_key=... to VestaboardMessenger()."
            )

        self.timeout_s = timeout_s
        self.headers = {
            "Content-Type": "application/json",
            self.HEADER_NAME: self.api_key,
        }

    def get_message(self) -> Dict[str, Any]:
        """Fetch the current message shown on the Vestaboard."""
        resp = requests.get(
            self.VESTABOARD_URL,
            headers=self.headers,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.json()

    def send_message(self, message: str) -> Dict[str, Any]:
        """Send a plain-text message to the Vestaboard."""
        payload = {"text": message}
        resp = requests.post(
            self.VESTABOARD_URL,
            json=payload,
            headers=self.headers,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.json()

    def send_layout(self, layout: List[List]) -> Dict[str, Any]:
        """Send a pre-formatted layout (character-code array or similar).

        Use this if you already converted text to Vestaboard character codes.
        """
        resp = requests.post(
            self.VESTABOARD_URL,
            json=layout,
            headers=self.headers,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.json()

    def vbml_format_message(self, message: str) -> List[List]:
        payload = {"message": message}
        resp = requests.post(
            self.VBML_URL_FORMAT,
            json=payload,
            headers=self.headers,
            timeout=self.timeout_s
        )
        resp.raise_for_status()
        return resp.json()

    def vbml_compose_layout(self, payload) -> List[List]:
        payload = payload
        resp = requests.post(
            self.VBML_URL_COMPOSE,
            json=payload,
            headers=self.headers,
            timeout=self.timeout_s
        )
        resp.raise_for_status()
        return resp.json()


