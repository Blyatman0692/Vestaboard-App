import base64
import secrets
from urllib.parse import urlencode

import httpx

SONOS_AUTH_BASE_URL = "https://api.sonos.com/login/v3/oauth?"

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
        self.pending_states: set[str] = set()
        self.auth_base_url = SONOS_AUTH_BASE_URL

    def get_oauth_url(self) -> str:
        state = secrets.token_urlsafe(24)
        self.pending_states.add(state)

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

        if state not in self.pending_states:
            raise SonosAuthError("State does not match")

        self.pending_states.remove(state)

        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()

        headers = {"Authorization": f"Basic {basic}"}
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.sonos.com/login/v3/oauth/access",
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
                "https://api.sonos.com/login/v3/oauth/access",
                headers=headers,
                data=data,
            )

        if resp.status_code != 200:
            raise SonosAuthError(f"Refresh failed: {resp.status_code}")

        return resp.json()



