import asyncio
import logging
import os

from sonos_app.data_store import PostgresDataStore
from sonos_app.sonos_client import SonosClient, SonosReauthorizationRequired
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
    ):
        self.data_store = data_store
        self.oauth_client = oauth_client
        self.renew_after_seconds = renew_after_seconds or _positive_int_env(
            "SONOS_PLAYBACK_METADATA_RENEW_AFTER_SECONDS",
            DEFAULT_RENEW_AFTER_SECONDS,
        )
        self.interval_seconds = interval_seconds or _positive_int_env(
            "SONOS_SUBSCRIPTION_RENEW_INTERVAL_SECONDS",
            DEFAULT_RENEWAL_INTERVAL_SECONDS,
        )

    async def renew_due(self):
        due_subscriptions = self.data_store.list_due_playback_metadata_subscriptions(
            self.renew_after_seconds
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
                await client.subscribe_playback_metadata(group_id)
                renewed.append(
                    self.data_store.save_playback_metadata_subscription(group_id)
                )
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
                failed.append(
                    {
                        "group_id": group_id,
                        "namespace": subscription["namespace"],
                        "error": str(exc),
                    }
                )

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
