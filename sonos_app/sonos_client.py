import datetime
import httpx

from sonos_app.config import SONOS_CONTROL_BASE_URL
from sonos_app.sonos_oauth_client import SonosAuthTokenRefreshError, SonosOAuthClient
from sonos_app.token import SonosToken
from sonos_app.data_store import PostgresDataStore


TOKEN_REFRESH_SKEW_SECONDS = 300


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class SonosReauthorizationRequired(RuntimeError):
    pass


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

    async def subscribe_playback(self, group_id: str):
        url = f"{SONOS_CONTROL_BASE_URL}/groups/{group_id}/playback/subscription"

        return await self._post_json(url)

    async def subscribe_playback_metadata(self, group_id: str):
        url = f"{SONOS_CONTROL_BASE_URL}/groups/{group_id}/playbackMetadata/subscription"

        return await self._post_json(url)

    @staticmethod
    def _parse_updated_at(value):
        if isinstance(value, datetime.datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None

        if parsed.tzinfo:
            parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)

        return parsed

    @classmethod
    def _access_token_refresh_due(cls, token: SonosToken) -> bool:
        if token.expires_in is None or token.updated_at is None:
            return False

        try:
            expires_in = int(token.expires_in)
        except (TypeError, ValueError):
            return False

        updated_at = cls._parse_updated_at(token.updated_at)
        if updated_at is None:
            return False

        refresh_at = updated_at + datetime.timedelta(
            seconds=max(0, expires_in - TOKEN_REFRESH_SKEW_SECONDS)
        )

        return _utcnow() >= refresh_at

    async def _refresh_access_token_if_due(self):
        latest = self.data_store.load_tokens()
        if not latest:
            raise SonosReauthorizationRequired(
                "Sonos authorization is missing or expired. Start OAuth again."
            )

        self.tokens = latest
        if self._access_token_refresh_due(latest):
            await self._refresh_access_token()

    async def _refresh_access_token(self):
        latest = self.data_store.load_tokens()
        if not latest or not latest.refresh_token:
            raise SonosReauthorizationRequired(
                "Sonos authorization is missing or expired. Start OAuth again."
            )

        try:
            refreshed = await self.oauth_client.refresh_token(latest.refresh_token)
        except SonosAuthTokenRefreshError as exc:
            if exc.code in {400, 401, 403}:
                self.data_store.clear_tokens()
                raise SonosReauthorizationRequired(
                    "Sonos rejected the saved refresh token. Start OAuth again."
                ) from exc
            raise

        new_token = SonosToken(
            access_token=refreshed["access_token"],
            refresh_token=refreshed.get("refresh_token", latest.refresh_token),
            expires_in=refreshed.get("expires_in"),
            scope=refreshed.get("scope"),
            updated_at=_utcnow(),
        )

        self.data_store.save_tokens(
            {
                "access_token": new_token.access_token,
                "refresh_token": new_token.refresh_token,
                "expires_in": new_token.expires_in,
                "scope": new_token.scope,
            }
        )
        self.tokens = new_token

    async def _get_json(self, url: str) -> dict:
        async def do_get(token: SonosToken):
            headers = {
                "Authorization": f"Bearer {token.access_token}",
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=20) as client:
                return await client.get(url, headers=headers)

        await self._refresh_access_token_if_due()

        # First attempt
        resp = await do_get(self.tokens)

        # Refresh token on 401
        if resp.status_code == 401:
            await self._refresh_access_token()
            resp = await do_get(self.tokens)

        if resp.status_code == 401:
            raise SonosReauthorizationRequired(
                "Sonos rejected the refreshed access token. Start OAuth again."
            )

        # Handle remaining errors
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Sonos API error {resp.status_code}: {resp.text}")

        return resp.json()

    async def _post_json(self, url: str) -> dict:
        async def do_post(token: SonosToken):
            headers = {
                "Authorization": f"Bearer {token.access_token}",
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=20) as client:
                return await client.post(url, headers=headers)

        await self._refresh_access_token_if_due()

        resp = await do_post(self.tokens)

        if resp.status_code == 401:
            await self._refresh_access_token()
            resp = await do_post(self.tokens)

        if resp.status_code == 401:
            raise SonosReauthorizationRequired(
                "Sonos rejected the refreshed access token. Start OAuth again."
            )

        if resp.status_code >= 400:
            raise RuntimeError(
                f"Sonos API error {resp.status_code}: {resp.text}")

        return resp.json() if resp.text else {}
