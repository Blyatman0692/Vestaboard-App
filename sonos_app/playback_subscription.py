from sonos_app.data_store import PostgresDataStore
from sonos_app.sonos_client import SonosAPIError, SonosClient


class PlaybackTargetUnavailable(RuntimeError):
    pass


class PlaybackTargetChanged(RuntimeError):
    pass


async def subscribe_target_metadata(
    client: SonosClient,
    data_store: PostgresDataStore,
    target: dict,
    *,
    group_id: str | None = None,
):
    """Subscribe to the selected speaker, rediscovering once after a gone group.

    Callers hold the shared subscription lock for this operation.
    """
    household_id, player_id = target["household_id"], target["player_id"]
    gone_group_id = None
    gone_error = None

    for attempt in range(2):
        if group_id is None:
            group_id = await client.get_player_group_id(household_id, player_id)
        if gone_error is not None and group_id == gone_group_id:
            # Discovery can lag behind a group change. Never retry the known dead ID.
            raise gone_error

        if not data_store.update_playback_target_group(household_id, player_id, group_id):
            raise PlaybackTargetChanged("The selected Sonos playback target changed. Retry the subscription.")
        if group_id is None:
            raise PlaybackTargetUnavailable(
                "The selected Sonos player is not currently available in its household."
            )

        try:
            await client.subscribe_playback_metadata(group_id)
        except SonosAPIError as exc:
            if exc.status_code != 410:
                raise
            data_store.invalidate_playback_metadata_subscription(group_id)
            if attempt == 1:
                raise
            gone_group_id, gone_error = group_id, exc
            group_id = None
        else:
            if data_store.load_playback_target() != {**target, "group_id": group_id}:
                raise PlaybackTargetChanged("The selected Sonos playback target changed.")
            return data_store.save_playback_metadata_subscription(group_id)
