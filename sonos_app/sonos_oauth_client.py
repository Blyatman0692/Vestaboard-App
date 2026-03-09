import base64
import secrets
from urllib.parse import urlencode
from sonos_app.config import SONOS_OAUTH_BASE_URL, SONOS_OAUTH_TOKEN_URL, \
    DB_URL, SONOS_CLIENT_ID
import httpx
import logging

from sonos_app.data_store import PostgresDataStore

logger = logging.getLogger(__name__)


class SonosAuthError(Exception):
    """base error"""

class SonosAuthTokenExchangeError(SonosAuthError):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code



class SonosOAuthClient:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.auth_base_url = SONOS_OAUTH_BASE_URL
        self.db_client = PostgresDataStore(DB_URL, SONOS_CLIENT_ID)

    def get_oauth_url(self) -> str:
        state = secrets.token_urlsafe(24)
        self.db_client.save_oauth_state(state)

        logger.info(
            "[OAUTH START] Generated state=%s",
            state,
        )

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "state": state,
            "scope": "playback-control-all",
            "redirect_uri": self.redirect_uri,
        }

        return self.auth_base_url + urlencode(params)


    async def oauth_callback(self, code: str | None = None, state: str | None = None):
        if not code or not state:
            raise SonosAuthError("Missing code or state")

        if not self.db_client.consume_oauth_state(state):
            logger.error(
                "[OAUTH CLIENT] STATE MISMATCH! received=%s",
                state,
            )
            raise SonosAuthError("State does not match")

        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()

        headers = {"Authorization": f"Basic {basic}"}
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                SONOS_OAUTH_TOKEN_URL,
                headers=headers,
                data=data,
            )

        if resp.status_code != 200:
            raise SonosAuthTokenExchangeError("Token exchange failure", resp.status_code)

        return resp.json()

    async def refresh_token(self, refresh_token: str):
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()).decode()
        headers = {
            "Authorization": f"Basic {basic}",
            "Accept": "application/json",
        }

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                SONOS_OAUTH_TOKEN_URL,
                headers=headers,
                data=data,
            )

        if resp.status_code != 200:
            raise SonosAuthError(f"Refresh failed: {resp.status_code}")

        return resp.json()



