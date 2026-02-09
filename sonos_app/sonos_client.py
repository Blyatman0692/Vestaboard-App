import datetime
import httpx

from sonos_app.config import SONOS_CONTROL_BASE_URL, SONOS_CLIENT_ID, DB_URL
from sonos_app.sonos_oauth_client import SonosOAuthClient
from sonos_app.token import SonosToken
from sonos_app.data_store import PostgresDataStore


class SonosClient:
    def __init__(
        self,
        tokens: SonosToken,
        data_store: PostgresDataStore,
        oauth_client: SonosOAuthClient,
    ):
        self.tokens = tokens
        self.data_store = data_store
        self.oauth_client = oauth_client

    async def get_households(self) -> dict:
        url = f"{SONOS_CONTROL_BASE_URL}/households"
        return await self._get_json(url)

    async def get_groups(self, householdId: str):
        url = f"{SONOS_CONTROL_BASE_URL}/households/{householdId}/groups"

        return await self._get_json(url)

    async def _get_json(self, url: str) -> dict:
        async def do_get(token: SonosToken):
            headers = {
                "Authorization": f"Bearer {token.access_token}",
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=20) as client:
                return await client.get(url, headers=headers)

        # First attempt
        resp = await do_get(self.tokens)

        # Refresh token on 401
        if resp.status_code == 401:
            latest = self.data_store.load_tokens()
            if not latest or not latest.refresh_token:
                raise RuntimeError(
                    "Sonos access token expired and no refresh_token found. Re-auth required."
                )

            refreshed = await self.oauth_client.refresh_token(
                latest.refresh_token)

            # Build new SonosToken
            new_token = SonosToken(
                access_token=refreshed["access_token"],
                refresh_token=refreshed.get("refresh_token",
                                            latest.refresh_token),
                expires_in=refreshed.get("expires_in"),
                scope=refreshed.get("scope"),
                updated_at=datetime.datetime.now(),
            )

            # Persist
            self.data_store.save_tokens(
                {
                    "access_token": new_token.access_token,
                    "refresh_token": new_token.refresh_token,
                    "expires_in": new_token.expires_in,
                    "scope": new_token.scope,
                }
            )

            # Update in-memory token
            self.tokens = new_token

            # Retry once
            resp = await do_get(self.tokens)

        # Handle remaining errors
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Sonos API error {resp.status_code}: {resp.text}")

        return resp.json()
