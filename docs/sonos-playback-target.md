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

After saving a selection, subscribe to its current group:

```http
POST /sonos/playback-target/subscribe
```

Each call first subscribes to the household's `groups` events, then gets fresh
groups from the saved household, finds the group whose
`playerIds` contains the selected player, caches its full `id`, and subscribes to
that group's `playbackMetadata`. The selected player does not need to be the
group coordinator. The response lists both `groups` and `playbackMetadata` in
`subscribed`. A metadata subscription record is saved only after Sonos accepts it.

If the player is absent, the endpoint returns 404 and clears only the cached
group; the selected household and player remain saved. Initial discovery failures
return 502 and preserve the previous cache. Subscription failures other than 410
also return 502, but the cache retains the group just discovered: a cached group
does not imply a successful subscription. Authorization failures use the existing 401 response
with the reauthorization link. A missing selection or a selection changed during
discovery or subscription returns 409.

After deployment, call this endpoint once for an existing saved target to enable
group-change notifications. Signed `groups` events for that household are
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

If the selected speaker has no active subscription, the existing renewal loop
retries it on a later pass, even when there are no due subscription rows. This also
allows a newly selected or previously offline speaker to be subscribed. The
existing check interval defaults to six hours; healthy subscriptions retain the
48-hour renewal threshold. When a target is selected, renewal processes that one
speaker instead of separately attempting every historical group ID.

Without a saved playback target, renewal retires a group returning 410 but cannot
choose a replacement speaker. The legacy `/sonos/subscribe/{group_id}` endpoint
also retires a gone group and returns 410; it continues to address the explicit ID.
Use `/sonos/playback-target/subscribe` for discovery and recovery.

Background failures are logged. A later event, a renewal pass for a target without
an active subscription, or another call to the subscribe endpoint can retry.
General startup reconciliation, periodic discovery of otherwise active targets,
and scheduled household subscription renewal remain for step 5.
Until household renewal is added, call the subscribe endpoint again to refresh
it before its three-day lifetime expires. See the
[Sonos subscription lifecycle](https://docs.sonos.com/docs/subscribe).

Run the persistence and API tests against a local test PostgreSQL database:

```sh
SONOS_TEST_DATABASE_URL='postgresql:///sonos_test' python -m unittest tests.test_sonos_playback_target -v
```

The tests create and remove an isolated schema and do not contact Sonos.
