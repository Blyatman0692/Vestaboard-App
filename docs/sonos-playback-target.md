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

The `sonos_playback_target` table is created on first use. Existing subscriptions
are retained, and no speaker is inferred from historical group IDs.

After saving a selection, subscribe to its current group:

```http
POST /sonos/playback-target/subscribe
```

Each call gets fresh groups from the saved household, finds the group whose
`playerIds` contains the selected player, caches its full `id`, and subscribes to
that group's `playbackMetadata`. The selected player does not need to be the
group coordinator. A subscription record is saved only after Sonos accepts it.

If the player is absent, the endpoint returns 404 and clears only the cached
group; the selected household and player remain saved. Discovery failures return
502 and preserve the previous cache. Subscription failures also return 502, but
the cache retains the group just discovered: a cached group does not imply a
successful subscription. Authorization failures use the existing 401 response
with the reauthorization link. A missing selection or a selection changed during
discovery returns 409.

This endpoint performs discovery and subscription on demand. Group-change events,
retiring obsolete subscriptions, and automatic recovery belong to later steps.
The existing `/sonos/subscribe/{group_id}` and renewal endpoints still behave as
before.

Run the persistence and API tests against a local test PostgreSQL database:

```sh
SONOS_TEST_DATABASE_URL='postgresql:///sonos_test' python -m unittest tests.test_sonos_playback_target -v
```

The tests create and remove an isolated schema and do not contact Sonos.
