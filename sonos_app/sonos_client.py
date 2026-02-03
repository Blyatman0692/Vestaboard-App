import os
import base64
from dataclasses import dataclass
import httpx

CONTROL_API_BASE_URL = "https://api.ws.sonos.com/control/api/v1"
SONOS_OAUTH_TOKEN_URL = "https://api.sonos.com/login/v3/oauth/access"

@dataclass
class SonosToken:
    access_token: str
    refresh_token: str | None = None


class SonosClient:

    def __init__(self, tokens: SonosToken):
        self.tokens = tokens

    async def get_households(self) -> dict:
        url = f"{CONTROL_API_BASE_URL}/households"
        return await self._get_json(url)

    async def _get_json(self, url: str) -> dict:
        headers = {"Authorization": f"Bearer {self.tokens.access_token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code >= 400:
            raise RuntimeError(f"Sonos API error {resp.status_code}: {resp.text}")

        return resp.json()
