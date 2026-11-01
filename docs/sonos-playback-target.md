# Sonos playback target

The playback target stores the speaker the board should follow, separately from
the group subscriptions. There is one target per configured `user_key`.

Use the household ID from `GET /sonos/households` and a player ID from the
`players` array returned by `GET /sonos/groups` to save a selection:

```http
PUT /sonos/playback-target
Content-Type: application/json

{"household_id": "Sonos_example", "player_id": "RINCON_example"}
```

`GET /sonos/playback-target` returns the saved selection, or `target: null` if
none has been saved:

```json
{
  "ok": true,
  "target": {
    "household_id": "Sonos_example",
    "player_id": "RINCON_example",
    "group_id": null
  }
}
```

The nullable `group_id` caches the current group discovered by the app;
it is not a field clients set. Saving the same selection preserves the cached
group. Changing either the household or player clears it. The selection is
saved in PostgreSQL without contacting Sonos, so an offline speaker can remain selected.

The `sonos_playback_target` table is created on first use. No speaker is inferred
from historical group IDs.

The background worker discovers and subscribes to the saved speaker on startup
and every five minutes. To subscribe immediately after saving a selection:

```http
POST /sonos/playback-target/subscribe
```

Each call first subscribes to the household's `groups` events, then gets fresh
groups from the saved household, finds the group whose
`playerIds` contains the selected player, caches its full `id`, and subscribes to
that group's `playbackMetadata`. The selected player does not need to be the
group coordinator. The response lists both `groups` and `playbackMetadata` in
`subscribed`. Each subscription's successful timestamp is saved only after Sonos
accepts that subscription. Household timestamps are stored by user and household
in `sonos_groups_subscriptions`, which is created on first use.

If the player is absent, the endpoint returns 404 and clears only the cached
group; the selected household and player remain saved. Initial discovery failures
return 502 and preserve the previous cache. Subscription failures other than 410
also return 502, but the cache retains the group just discovered: a cached group
does not imply a successful subscription. Authorization failures use the existing 401 response
with the reauthorization link. A missing selection or a selection changed during
discovery or subscription returns 409.

The startup check also enables group-change notifications for existing saved
targets. Signed `groups` events for that household are
acknowledged before discovery or subscription calls begin. A background task
fetches the latest groups and subscribes to the selected player's current group.
It does not register another household subscription, so initial subscription
events do not cause a resubscription loop. Events for other households are ignored.

When discovery succeeds, the cached group is updated and all other
`playbackMetadata` subscription records for this user are marked inactive in the
same transaction. This includes historical records from before player selection
was introduced. With a selected target, only its current group is followed; other
users and other namespaces are unaffected. If the player is absent, all of this
user's metadata subscriptions become inactive while the selection is preserved.
A later group event can restore its subscription when the player returns.

Inactive records are excluded from renewal. Remote subscriptions are left to
expire, and metadata from groups other than the selected player's cached group
is ignored. Background reconciliation and the renewal loop share a lock within
the web process to prevent overlapping subscription updates. The provided
`Procfile` runs one web worker; this lock does not coordinate multiple processes.

Sonos API failures expose `status_code` and `error_code` through `SonosAPIError`.
For a metadata subscription failure with HTTP 410, the failed group is marked
inactive and its cached ID is cleared immediately. The saved speaker is then
rediscovered, and the subscription is retried once against its current group.
This recovery is shared by manual target subscriptions, group events, and renewals.
If discovery still returns the same gone ID, no second POST is sent. A second 410
retires the replacement group too and ends the attempt. Other HTTP failures do not
trigger group recovery. Failed rediscovery leaves the known gone group retired.

The existing renewal worker discovers the selected speaker's current group on
every pass, even when no subscriptions are due. A changed group or a missing
subscription is subscribed immediately. An unchanged, healthy subscription is
left alone until its last successful subscription is 48 hours old. This catches
missed group events and retries newly selected or previously offline speakers.
Only the selected speaker and its household are processed, so historical groups
and households are not resubscribed.

Household `groups` subscriptions use the same 48-hour renewal threshold, with
their own persisted timestamp. This renews both subscriptions before their
three-day lifetime expires; see the
[Sonos subscription lifecycle](https://docs.sonos.com/docs/subscribe).
A household subscription failure does not prevent metadata discovery, and a
discovery failure does not prevent household renewal. Failed attempts leave their
subscription timestamps unchanged and are retried on a later pass.

`SONOS_SUBSCRIPTION_RENEW_INTERVAL_SECONDS` controls the discovery/check interval
(default `300`). `SONOS_PLAYBACK_METADATA_RENEW_AFTER_SECONDS` controls the renewal
age for both subscription types (default `172800`). Existing explicit settings
remain in effect. `POST /sonos/subscriptions/renew` runs the same check immediately;
its `renewed` results can include `groups` records with a `household_id` and
`playbackMetadata` records with a `group_id`.

Without a saved playback target, renewal retires a group returning 410 but cannot
choose a replacement speaker. The legacy `/sonos/subscribe/{group_id}` endpoint
also retires a gone group and returns 410; it continues to address the explicit ID.
Use `/sonos/playback-target/subscribe` for discovery and recovery.

Background failures are logged. A later event, the next periodic check, or another
call to the subscribe endpoint can retry.

Run the persistence and API tests against a local test PostgreSQL database:

```sh
SONOS_TEST_DATABASE_URL='postgresql:///sonos_test' python -m unittest tests.test_sonos_playback_target -v
```

The tests create and remove an isolated schema and do not contact Sonos.
