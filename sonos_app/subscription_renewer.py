import asyncio
import logging
import os

from sonos_app.data_store import PLAYBACK_METADATA_NAMESPACE, PostgresDataStore
from sonos_app.playback_subscription import subscribe_target_metadata
from sonos_app.sonos_client import SonosAPIError, SonosClient, SonosReauthorizationRequired
from sonos_app.sonos_oauth_client import SonosOAuthClient


logger = logging.getLogger(__name__)

DEFAULT_RENEW_AFTER_SECONDS = 2 * 24 * 60 * 60
DEFAULT_RENEWAL_INTERVAL_SECONDS = 5 * 60


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
        result = {
            "ok": True,
            "reauthorization_required": False,
            "renew_after_seconds": self.renew_after_seconds,
            "due_count": 0,
            "renewed": [],
            "failed": [],
        }
        target = self.data_store.load_playback_target()
        if target is not None:
            # Discovery runs on every pass, even when neither subscription is due.
            subscriptions = [
                {"household_id": target["household_id"], "namespace": "groups"},
                {"group_id": target["group_id"], "namespace": PLAYBACK_METADATA_NAMESPACE},
            ]
        else:
            subscriptions = self.data_store.list_due_playback_metadata_subscriptions(
                self.renew_after_seconds
            )
        if not subscriptions:
            return result

        tokens = self.data_store.load_tokens()
        if not tokens or not tokens.refresh_token:
            result.update(
                ok=False,
                reauthorization_required=True,
                detail="No usable Sonos authorization was found. Start OAuth again.",
            )
            return result

        client = SonosClient(tokens, self.data_store, self.oauth_client)

        for subscription in subscriptions:
            try:
                if subscription["namespace"] == "groups":
                    household_id = subscription["household_id"]
                    if not self.data_store.groups_subscription_due(household_id, self.renew_after_seconds):
                        continue
                    result["due_count"] += 1
                    await client.subscribe_groups(household_id)
                    renewed = self.data_store.save_groups_subscription(household_id)
                elif target is not None:
                    result["due_count"] += 1
                    renewed = await subscribe_target_metadata(
                        client, self.data_store, target,
                        renew_after_seconds=self.renew_after_seconds,
                    )
                    if renewed is None:
                        result["due_count"] -= 1
                        continue
                else:
                    result["due_count"] += 1
                    group_id = subscription["group_id"]
                    try:
                        await client.subscribe_playback_metadata(group_id)
                    except SonosAPIError as exc:
                        if exc.status_code == 410:
                            self.data_store.invalidate_playback_metadata_subscription(group_id)
                        raise
                    renewed = self.data_store.save_playback_metadata_subscription(group_id)
                result["renewed"].append(renewed)
            except SonosReauthorizationRequired as exc:
                result.update(ok=False, reauthorization_required=True, detail=str(exc))
                return result
            except Exception as exc:
                logger.exception(
                    "Failed to reconcile Sonos subscription: %s", subscription,
                )
                failure = {
                    **{key: subscription[key] for key in ("group_id", "household_id") if key in subscription},
                    "namespace": subscription["namespace"],
                    "error": str(exc),
                }
                if isinstance(exc, SonosAPIError):
                    failure.update(status_code=exc.status_code, error_code=exc.error_code)
                result["failed"].append(failure)

        result["ok"] = not result["failed"]
        return result

    async def run_forever(self):
        logger.info(
            "Starting Sonos discovery and subscription renewal checks every %s seconds",
            self.interval_seconds,
        )

        while True:
            try:
                result = await self.renew_due()
                if result["due_count"] or result["failed"] or result["reauthorization_required"]:
                    logger.info("Sonos subscription renewal result: %s", result)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Sonos subscription renewal loop failed")

            await asyncio.sleep(self.interval_seconds)
