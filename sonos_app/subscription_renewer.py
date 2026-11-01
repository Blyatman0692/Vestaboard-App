import asyncio
import logging
import os

from sonos_app.data_store import PLAYBACK_METADATA_NAMESPACE, PostgresDataStore
from sonos_app.playback_subscription import subscribe_target_metadata
from sonos_app.sonos_client import SonosAPIError, SonosClient, SonosReauthorizationRequired
from sonos_app.sonos_oauth_client import SonosOAuthClient


logger = logging.getLogger(__name__)

DEFAULT_RENEW_AFTER_SECONDS = 2 * 24 * 60 * 60
DEFAULT_RENEWAL_INTERVAL_SECONDS = 6 * 60 * 60


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("%s must be an integer; using %s", name, default)
        return default

    if value <= 0:
        logger.warning("%s must be positive; using %s", name, default)
        return default

    return value


class PlaybackMetadataSubscriptionRenewer:
    def __init__(
        self,
        data_store: PostgresDataStore,
        oauth_client: SonosOAuthClient,
        *,
        renew_after_seconds: int | None = None,
        interval_seconds: int | None = None,
        lock: asyncio.Lock | None = None,
    ):
        self.data_store = data_store
        self.oauth_client = oauth_client
        self._lock = lock if lock is not None else asyncio.Lock()
        self.renew_after_seconds = renew_after_seconds or _positive_int_env(
            "SONOS_PLAYBACK_METADATA_RENEW_AFTER_SECONDS",
            DEFAULT_RENEW_AFTER_SECONDS,
        )
        self.interval_seconds = interval_seconds or _positive_int_env(
            "SONOS_SUBSCRIPTION_RENEW_INTERVAL_SECONDS",
            DEFAULT_RENEWAL_INTERVAL_SECONDS,
        )

    async def renew_due(self):
        async with self._lock:
            return await self._renew_due()

    async def _renew_due(self):
        due_subscriptions = self.data_store.list_due_playback_metadata_subscriptions(
            self.renew_after_seconds
        )
        target = self.data_store.load_playback_target()
        if target is not None:
            has_subscription = any(
                subscription["active"] and subscription["group_id"] == target["group_id"]
                for subscription in self.data_store.list_playback_metadata_subscriptions()
            )
            # A gone group is retired immediately. Keep retrying the saved speaker
            # on later passes even when there are no active subscriptions left.
            due_subscriptions = (
                [{"group_id": target["group_id"], "namespace": PLAYBACK_METADATA_NAMESPACE}]
                if due_subscriptions or not has_subscription else []
            )
        if not due_subscriptions:
            return {
                "ok": True,
                "reauthorization_required": False,
                "renew_after_seconds": self.renew_after_seconds,
                "due_count": 0,
                "renewed": [],
                "failed": [],
            }

        tokens = self.data_store.load_tokens()
        if not tokens or not tokens.refresh_token:
            return {
                "ok": False,
                "reauthorization_required": True,
                "detail": "No usable Sonos authorization was found. Start OAuth again.",
                "renew_after_seconds": self.renew_after_seconds,
                "due_count": len(due_subscriptions),
                "renewed": [],
                "failed": [],
            }

        client = SonosClient(tokens, self.data_store, self.oauth_client)
        renewed = []
        failed = []

        for subscription in due_subscriptions:
            group_id = subscription["group_id"]
            try:
                if target is not None:
                    renewed.append(await subscribe_target_metadata(
                        client, self.data_store, target, group_id=group_id
                    ))
                else:
                    try:
                        await client.subscribe_playback_metadata(group_id)
                    except SonosAPIError as exc:
                        if exc.status_code == 410:
                            self.data_store.invalidate_playback_metadata_subscription(group_id)
                        raise
                    renewed.append(self.data_store.save_playback_metadata_subscription(group_id))
            except SonosReauthorizationRequired as exc:
                return {
                    "ok": False,
                    "reauthorization_required": True,
                    "detail": str(exc),
                    "renew_after_seconds": self.renew_after_seconds,
                    "due_count": len(due_subscriptions),
                    "renewed": renewed,
                    "failed": failed,
                }
            except Exception as exc:
                logger.exception(
                    "Failed to renew Sonos playback metadata subscription for group %s",
                    group_id,
                )
                failure = {
                    "group_id": group_id,
                    "namespace": subscription["namespace"],
                    "error": str(exc),
                }
                if isinstance(exc, SonosAPIError):
                    failure.update(status_code=exc.status_code, error_code=exc.error_code)
                failed.append(failure)

        return {
            "ok": not failed,
            "reauthorization_required": False,
            "renew_after_seconds": self.renew_after_seconds,
            "due_count": len(due_subscriptions),
            "renewed": renewed,
            "failed": failed,
        }

    async def run_forever(self):
        logger.info(
            "Starting Sonos playback metadata renewal loop every %s seconds",
            self.interval_seconds,
        )

        while True:
            try:
                result = await self.renew_due()
                if result["due_count"] or result["failed"]:
                    logger.info("Sonos subscription renewal result: %s", result)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Sonos subscription renewal loop failed")

            await asyncio.sleep(self.interval_seconds)
