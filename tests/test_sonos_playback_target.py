import asyncio
import base64
import hashlib
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, call, patch
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import psycopg
from psycopg.conninfo import make_conninfo

from sonos_app.data_store import PostgresDataStore
from sonos_app.config import SONOS_CONTROL_BASE_URL
from sonos_app.sonos_client import SonosAPIError, SonosClient, SonosReauthorizationRequired
from sonos_app.subscription_renewer import PlaybackMetadataSubscriptionRenewer
from sonos_app.token import SonosToken


@unittest.skipUnless(
    os.environ.get("SONOS_TEST_DATABASE_URL"),
    "Set SONOS_TEST_DATABASE_URL to run the Sonos persistence tests",
)
class PlaybackTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = f"sonos_target_test_{uuid4().hex}"
        conn = psycopg.connect(os.environ["SONOS_TEST_DATABASE_URL"], autocommit=True)
        cls.addClassCleanup(conn.close)
        conn.execute(f"create schema {schema}")
        cls.addClassCleanup(conn.execute, f"drop schema {schema} cascade")
        cls.db_url = make_conninfo(
            os.environ["SONOS_TEST_DATABASE_URL"], options=f"-c search_path={schema}"
        )

        # Load the routes without constructing clients from the real app configuration.
        routes_path = Path(__file__).resolve().parents[1] / "sonos_app" / "routes.py"
        spec = importlib.util.spec_from_file_location("sonos_target_test_routes", routes_path)
        cls.routes = importlib.util.module_from_spec(spec)
        with patch("app.build_sonos_container", return_value=Mock()):
            spec.loader.exec_module(cls.routes)

    def setUp(self):
        self.store = PostgresDataStore(self.db_url, uuid4().hex)
        self.routes.db_client = self.store
        self.routes.subscription_lock = asyncio.Lock()
        self.routes.sonos_config = SimpleNamespace(client_id="test-client", client_secret="test-secret")
        self.routes.event_processor = Mock()
        # No lifespan: these tests must not start the subscription renewal worker.
        self.client = TestClient(self.routes.app)
        self.addCleanup(self.client.close)
        tokens = patch.object(
            self.store, "load_tokens", return_value=SonosToken("access-token", "refresh-token")
        )
        self.load_tokens = tokens.start()
        self.addCleanup(tokens.stop)
        get = patch.object(SonosClient, "_get_json", return_value={"groups": []})
        self.sonos_get = get.start()
        self.addCleanup(get.stop)
        post = patch.object(SonosClient, "_post_json", return_value={})
        self.sonos_post = post.start()
        self.addCleanup(post.stop)

    def select(self, household_id="household-1", player_id="player-1"):
        response = self.client.put(
            "/sonos/playback-target",
            json={"household_id": household_id, "player_id": player_id},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["target"]

    def cache_group(self, group_id):
        target = self.store.load_playback_target()
        self.assertTrue(self.store.update_playback_target_group(
            target["household_id"], target["player_id"], group_id
        ))

    def event_headers(self, namespace="groups", event_type="groups", target_type="householdId",
                      target_value="household-1", sequence="1"):
        values = [sequence, namespace, event_type, target_type, target_value, "test-client", "test-secret"]
        signature = base64.urlsafe_b64encode(
            hashlib.sha256("".join(values).encode()).digest()
        ).decode().rstrip("=")
        return {
            "X-Sonos-Event-Seq-Id": sequence,
            "X-Sonos-Namespace": namespace,
            "X-Sonos-Type": event_type,
            "X-Sonos-Target-Type": target_type,
            "X-Sonos-Target-Value": target_value,
            "X-Sonos-Event-Signature": signature,
        }

    def assert_only_household_subscriptions(self):
        self.assertTrue(all(
            awaited == call(f"{SONOS_CONTROL_BASE_URL}/households/household-1/groups/subscription")
            for awaited in self.sonos_post.await_args_list
        ))

    @staticmethod
    def gone_error():
        return SonosAPIError(410, '{"errorCode":"ERROR_RESOURCE_GONE"}')

    @staticmethod
    def discovered_group(group_id):
        return {"groups": [{"id": group_id, "playerIds": ["player-1"]}]} if group_id else {"groups": []}

    def make_subscriptions_due(self):
        with psycopg.connect(self.db_url) as conn:
            conn.execute(
                "update sonos_subscriptions set last_subscribed_at = now() - interval '3 days' where user_key = %s",
                (self.store.user_key,),
            )

    def renew(self):
        renewer = PlaybackMetadataSubscriptionRenewer(self.store, Mock(), lock=self.routes.subscription_lock)
        with patch("sonos_app.subscription_renewer.logger.exception"):
            return asyncio.run(renewer.renew_due())

    def test_selection_persists_without_a_group_or_sonos_authorization(self):
        self.load_tokens.return_value = None
        self.assertEqual(
            self.client.get("/sonos/playback-target").json(),
            {"ok": True, "target": None},
        )

        target = self.select()

        self.assertEqual(
            target,
            {"household_id": "household-1", "player_id": "player-1", "group_id": None},
        )
        reopened_store = PostgresDataStore(self.db_url, self.store.user_key)
        self.assertEqual(reopened_store.load_playback_target(), target)
        self.assertEqual(self.client.get("/sonos/playback-target").json()["target"], target)
        self.sonos_get.assert_not_awaited()
        self.sonos_post.assert_not_awaited()

    def test_saving_the_same_selection_preserves_its_cached_group(self):
        self.select()
        self.cache_group("group-1")

        self.assertEqual(self.select()["group_id"], "group-1")

    def test_changing_the_player_or_household_clears_the_cached_group(self):
        self.select()
        for household_id, player_id in [("household-1", "player-2"), ("household-2", "player-2")]:
            with self.subTest(household_id=household_id, player_id=player_id):
                self.cache_group("old-group")
                self.assertEqual(
                    self.select(household_id, player_id),
                    {"household_id": household_id, "player_id": player_id, "group_id": None},
                )

    def test_losing_the_cached_group_keeps_the_selected_speaker(self):
        target = self.select()
        self.cache_group("old-group")
        self.cache_group(None)

        self.assertEqual(self.store.load_playback_target(), target)

    def test_selection_is_separate_from_other_users_and_subscriptions(self):
        subscription = self.store.save_playback_metadata_subscription("old-group")
        target = self.select()
        other_store = PostgresDataStore(self.db_url, uuid4().hex)
        self.assertIsNone(other_store.load_playback_target())
        other_store.save_playback_target("other-household", "other-player")

        self.assertEqual(self.store.load_playback_target(), target)
        self.assertEqual(self.store.list_playback_metadata_subscriptions(), [subscription])

    def test_invalid_selection_does_not_replace_the_saved_target(self):
        target = self.select()
        for field in ("household_id", "player_id"):
            for value in ("", " ", "has spaces", None):
                with self.subTest(field=field, value=value):
                    payload = {"household_id": "household-2", "player_id": "player-2"}
                    payload[field] = value
                    response = self.client.put("/sonos/playback-target", json=payload)
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(self.store.load_playback_target(), target)

    def test_subscription_discovers_membership_and_uses_the_full_current_group_id(self):
        self.select()
        self.cache_group("obsolete-group")
        for group_id in ("different-coordinator:123", "different-coordinator:456"):
            with self.subTest(group_id=group_id):
                self.sonos_get.return_value = {
                    "groups": [
                        {"id": "player-1:wrong-group", "playerIds": ["player-10"]},
                        {
                            "id": group_id,
                            "coordinatorId": "different-coordinator",
                            "playerIds": ["different-coordinator", "player-1"],
                        },
                    ]
                }

                response = self.client.post("/sonos/playback-target/subscribe")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["group_id"], group_id)
                self.assertEqual(response.json()["subscription"]["group_id"], group_id)
                self.sonos_get.assert_awaited_with(
                    f"{SONOS_CONTROL_BASE_URL}/households/household-1/groups"
                )
                self.sonos_post.assert_awaited_with(
                    f"{SONOS_CONTROL_BASE_URL}/groups/{group_id}/playbackMetadata/subscription"
                )
                self.assertEqual(self.store.load_playback_target()["group_id"], group_id)
        self.assertEqual(self.sonos_get.await_count, 2)
        self.assertEqual(self.sonos_post.await_count, 4)
        self.assertEqual(self.sonos_post.await_args_list[0], call(
            f"{SONOS_CONTROL_BASE_URL}/households/household-1/groups/subscription"
        ))
        self.assertEqual(response.json()["subscribed"], ["groups", "playbackMetadata"])

    def test_absent_player_clears_cached_group_without_changing_the_selection(self):
        target = self.select()
        for groups in ([], [{"id": "unrelated-group", "playerIds": ["player-2"]}]):
            with self.subTest(groups=groups):
                self.cache_group("obsolete-group")
                self.sonos_get.return_value = {"groups": groups}

                response = self.client.post("/sonos/playback-target/subscribe")

                self.assertEqual(response.status_code, 404)
                self.assertEqual(self.store.load_playback_target(), target)
                self.assertEqual(self.store.list_playback_metadata_subscriptions(), [])
                self.assert_only_household_subscriptions()

    def test_discovery_failure_preserves_the_cached_group(self):
        self.select()
        self.cache_group("last-known-group")
        for error in (SonosAPIError(503, "Unavailable"), httpx.ConnectError("Unavailable")):
            with self.subTest(error=error), patch.object(self.routes.logger, "exception"):
                self.sonos_get.side_effect = error

                response = self.client.post("/sonos/playback-target/subscribe")

                self.assertEqual(response.status_code, 502)
                self.assertEqual(self.store.load_playback_target()["group_id"], "last-known-group")
                self.assertEqual(self.store.list_playback_metadata_subscriptions(), [])
                self.assert_only_household_subscriptions()

    def test_failed_subscription_is_not_saved(self):
        self.select()
        self.sonos_get.return_value = {"groups": [{"id": "new-group", "playerIds": ["player-1"]}]}
        self.sonos_post.side_effect = [{}, SonosAPIError(503, "Unavailable")]

        with patch.object(self.routes.logger, "exception"):
            response = self.client.post("/sonos/playback-target/subscribe")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.store.load_playback_target()["group_id"], "new-group")
        self.assertEqual(self.store.list_playback_metadata_subscriptions(), [])

    def test_subscription_requires_a_selection(self):
        response = self.client.post("/sonos/playback-target/subscribe")

        self.assertEqual(response.status_code, 409)
        self.sonos_get.assert_not_awaited()
        self.sonos_post.assert_not_awaited()

    def test_subscription_reports_reauthorization_for_missing_or_rejected_tokens(self):
        self.select()
        self.load_tokens.return_value = None
        response = self.client.post("/sonos/playback-target/subscribe")
        self.assertEqual(response.status_code, 401)
        self.sonos_get.assert_not_awaited()
        self.sonos_post.assert_not_awaited()

        self.load_tokens.return_value = SonosToken("access-token", "refresh-token")
        self.sonos_get.return_value = {"groups": [{"id": "group-1", "playerIds": ["player-1"]}]}
        for request_mock in (self.sonos_get, self.sonos_post):
            with self.subTest(request=request_mock):
                request_mock.side_effect = SonosReauthorizationRequired("Start OAuth again.")
                response = self.client.post("/sonos/playback-target/subscribe")
                request_mock.side_effect = None

                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["reauthorize_path"], "/oauth/start")
                self.assertEqual(self.store.list_playback_metadata_subscriptions(), [])

    def test_discovery_cannot_overwrite_a_changed_selection(self):
        for household_id, player_id in [("household-1", "player-2"), ("household-2", "player-1")]:
            with self.subTest(household_id=household_id, player_id=player_id):
                self.select()

                async def change_target(url):
                    self.store.save_playback_target(household_id, player_id)
                    return {"groups": [{"id": "old-target-group", "playerIds": ["player-1"]}]}

                self.sonos_get.side_effect = change_target
                response = self.client.post("/sonos/playback-target/subscribe")

                self.assertEqual(response.status_code, 409)
                self.assertEqual(self.store.load_playback_target(), {
                    "household_id": household_id, "player_id": player_id, "group_id": None
                })
                self.assert_only_household_subscriptions()

    def test_cached_group_update_is_scoped_to_the_user(self):
        self.select()
        other_store = PostgresDataStore(self.db_url, uuid4().hex)
        other_target = other_store.save_playback_target("household-1", "player-1")

        self.cache_group("group-1")

        self.assertEqual(other_store.load_playback_target(), other_target)

    def test_group_event_uses_fresh_discovery_and_retires_previous_subscriptions(self):
        self.select()
        self.cache_group("old-group")
        for group_id in ("old-group", "historical-group"):
            self.store.save_playback_metadata_subscription(group_id)
        other_store = PostgresDataStore(self.db_url, uuid4().hex)
        other_subscription = other_store.save_playback_metadata_subscription("other-group")
        self.sonos_get.return_value = {"groups": [{"id": "new-group", "playerIds": ["player-1"]}]}

        response = self.client.post("/sonos/events", headers=self.event_headers(), json={
            "groups": [{"id": "stale-event-group", "playerIds": ["player-1"]}]
        })

        self.assertEqual(response.status_code, 200)
        self.sonos_post.assert_awaited_once_with(
            f"{SONOS_CONTROL_BASE_URL}/groups/new-group/playbackMetadata/subscription"
        )
        self.assertEqual(self.store.load_playback_target()["group_id"], "new-group")
        subscriptions = {row["group_id"]: row["active"] for row in self.store.list_playback_metadata_subscriptions()}
        self.assertEqual(subscriptions, {"old-group": False, "historical-group": False, "new-group": True})
        self.assertEqual(other_store.list_playback_metadata_subscriptions(), [other_subscription])
        self.routes.event_processor.process_metadata.assert_not_called()

    def test_group_event_sends_response_before_discovery_begins(self):
        self.select()
        messages = []

        async def discover(url):
            self.assertTrue(any(
                message["type"] == "http.response.body" and not message.get("more_body", False)
                for message in messages
            ))
            return {"groups": [{"id": "group-1", "playerIds": ["player-1"]}]}

        async def send(message):
            messages.append(message)

        self.sonos_get.side_effect = discover
        scope = {
            "type": "http", "http_version": "1.1", "method": "POST",
            "path": "/sonos/events", "raw_path": b"/sonos/events", "query_string": b"",
            "scheme": "https", "server": ("testserver", 443), "client": ("testclient", 123),
            "headers": [(key.lower().encode(), value.encode()) for key, value in self.event_headers().items()],
        }
        asyncio.run(self.routes.app(scope, AsyncMock(return_value={"type": "http.request", "body": b"{}"}), send))
        self.assertEqual(messages[0]["status"], 200)
        self.sonos_get.assert_awaited_once()

    def test_repeated_and_versioned_group_events_do_not_create_duplicate_records(self):
        self.select()
        self.sonos_get.return_value = {"groups": [{"id": "group-1", "playerIds": ["player-1"]}]}
        for namespace in ("groups", "groups:1"):
            response = self.client.post("/sonos/events", headers=self.event_headers(namespace=namespace), json={})
            self.assertEqual(response.status_code, 200)

        subscriptions = self.store.list_playback_metadata_subscriptions()
        self.assertEqual(len(subscriptions), 1)
        self.assertTrue(subscriptions[0]["active"])
        self.assertTrue(all("/households/" not in awaited.args[0] for awaited in self.sonos_post.await_args_list))

    def test_group_event_for_another_household_or_without_selection_is_ignored(self):
        response = self.client.post("/sonos/events", headers=self.event_headers(), json={})
        self.assertEqual(response.status_code, 200)
        self.select()
        response = self.client.post("/sonos/events", headers=self.event_headers(target_value="other-household"), json={})
        self.assertEqual(response.status_code, 200)
        self.sonos_get.assert_not_awaited()
        self.sonos_post.assert_not_awaited()

    def test_invalid_or_missing_signature_cannot_schedule_reconciliation(self):
        self.select()
        invalid = self.event_headers()
        invalid["X-Sonos-Event-Signature"] = "invalid"
        for headers in (invalid, {}):
            response = self.client.post("/sonos/events", headers=headers, json={})
            self.assertEqual(response.status_code, 401)
        self.sonos_get.assert_not_awaited()
        self.sonos_post.assert_not_awaited()

    def test_background_failure_is_logged_after_acknowledgment(self):
        self.select()
        self.cache_group("old-group")
        old_subscription = self.store.save_playback_metadata_subscription("old-group")
        self.sonos_get.side_effect = httpx.ConnectError("Unavailable")

        with patch.object(self.routes.logger, "exception") as log:
            response = self.client.post("/sonos/events", headers=self.event_headers(), json={})

        self.assertEqual(response.status_code, 200)
        log.assert_called_once()
        self.assertEqual(self.store.load_playback_target()["group_id"], "old-group")
        self.assertEqual(self.store.list_playback_metadata_subscriptions(), [old_subscription])

    def test_offline_player_is_preserved_and_recovers_on_a_later_group_event(self):
        target = self.select()
        self.cache_group("old-group")
        self.store.save_playback_metadata_subscription("old-group")

        response = self.client.post("/sonos/events", headers=self.event_headers(), json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.load_playback_target(), target)
        self.assertFalse(self.store.list_playback_metadata_subscriptions()[0]["active"])
        self.sonos_post.assert_not_awaited()
        self.sonos_get.return_value = {"groups": [{"id": "returned-group", "playerIds": ["player-1"]}]}
        self.client.post("/sonos/events", headers=self.event_headers(sequence="2"), json={})
        self.assertEqual(self.store.load_playback_target()["group_id"], "returned-group")
        self.sonos_post.assert_awaited_once()

    def test_old_metadata_is_ignored_and_current_metadata_is_processed(self):
        self.select()
        self.cache_group("new-group")
        body = {"currentItem": {"track": {"name": "Test song"}}}
        for group_id in ("old-group", "new-group"):
            response = self.client.post("/sonos/events", json=body, headers=self.event_headers(
                namespace="playbackMetadata", event_type="metadataStatus",
                target_type="groupId", target_value=group_id,
            ))
            self.assertEqual(response.status_code, 200)
        self.routes.event_processor.process_metadata.assert_called_once()
        self.assertEqual(self.routes.event_processor.process_metadata.call_args.args[0].group_id, "new-group")

    def test_selection_changed_during_subscription_is_not_recorded_for_the_new_target(self):
        self.select()
        self.sonos_get.return_value = {"groups": [{"id": "old-target-group", "playerIds": ["player-1"]}]}

        async def change_selection(url):
            self.store.save_playback_target("household-1", "player-2")
            return {}

        self.sonos_post.side_effect = change_selection
        self.client.post("/sonos/events", headers=self.event_headers(), json={})
        self.assertEqual(self.store.load_playback_target()["player_id"], "player-2")
        self.assertIsNone(self.store.load_playback_target()["group_id"])
        self.assertEqual(self.store.list_playback_metadata_subscriptions(), [])

    def test_renewal_cannot_reactivate_subscriptions_retired_by_reconciliation(self):
        self.select()
        self.cache_group("old-group")
        self.store.save_playback_metadata_subscription("old-group")
        with psycopg.connect(self.db_url) as conn:
            conn.execute("update sonos_subscriptions set last_subscribed_at = now() - interval '3 days' where user_key = %s", (self.store.user_key,))
        self.sonos_get.return_value = {"groups": [{"id": "new-group", "playerIds": ["player-1"]}]}

        async def overlap():
            self.routes.subscription_lock = asyncio.Lock()
            renewer = PlaybackMetadataSubscriptionRenewer(
                self.store, Mock(), lock=self.routes.subscription_lock
            )
            renewal_started = asyncio.Event()
            release_renewal = asyncio.Event()

            async def subscribe(url):
                if "/old-group/" in url:
                    renewal_started.set()
                    await release_renewal.wait()
                return {}

            self.sonos_post.side_effect = subscribe
            renewal = asyncio.create_task(renewer.renew_due())
            await renewal_started.wait()
            reconciliation = asyncio.create_task(self.routes.reconcile_household_groups("household-1"))
            await asyncio.sleep(0)
            self.sonos_get.assert_not_awaited()
            release_renewal.set()
            await asyncio.gather(renewal, reconciliation)

        asyncio.run(asyncio.wait_for(overlap(), timeout=5))
        subscriptions = {row["group_id"]: row["active"] for row in self.store.list_playback_metadata_subscriptions()}
        self.assertEqual(subscriptions, {"old-group": False, "new-group": True})
        self.assertEqual(self.store.list_due_playback_metadata_subscriptions(172800), [])

    def test_manual_subscription_recovers_once_from_a_gone_group(self):
        self.select()
        self.cache_group("old-group")
        self.store.save_playback_metadata_subscription("old-group")
        self.sonos_get.side_effect = [self.discovered_group("old-group"), self.discovered_group("new-group:456")]
        self.sonos_post.side_effect = [{}, self.gone_error(), {}]

        response = self.client.post("/sonos/playback-target/subscribe")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["group_id"], "new-group:456")
        self.assertEqual(self.sonos_get.await_count, 2)
        self.assertEqual(self.sonos_post.await_count, 3)
        self.sonos_post.assert_awaited_with(f"{SONOS_CONTROL_BASE_URL}/groups/new-group:456/playbackMetadata/subscription")
        self.assertEqual(self.store.load_playback_target()["group_id"], "new-group:456")
        self.assertEqual(
            {row["group_id"]: row["active"] for row in self.store.list_playback_metadata_subscriptions()},
            {"old-group": False, "new-group:456": True},
        )

    def test_group_event_uses_the_same_bounded_gone_group_recovery(self):
        self.select()
        self.sonos_get.side_effect = [self.discovered_group("old-group"), self.discovered_group("new-group")]
        self.sonos_post.side_effect = [self.gone_error(), {}]

        response = self.client.post("/sonos/events", headers=self.event_headers(), json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.load_playback_target()["group_id"], "new-group")
        self.assertEqual(self.sonos_post.await_count, 2)

    def test_renewal_recovers_the_selected_player_without_retrying_historical_records(self):
        self.select()
        self.cache_group("old-group")
        self.store.save_playback_metadata_subscription("old-group")
        self.store.save_playback_metadata_subscription("historical-group")
        self.make_subscriptions_due()
        self.sonos_get.return_value = self.discovered_group("new-group")
        self.sonos_post.side_effect = [self.gone_error(), {}]

        result = self.renew()

        self.assertTrue(result["ok"])
        self.assertFalse(result["reauthorization_required"])
        self.assertEqual([row["group_id"] for row in result["renewed"]], ["new-group"])
        self.assertEqual(result["failed"], [])
        self.sonos_get.assert_awaited_once()
        self.assertEqual(self.sonos_post.await_args_list, [
            call(f"{SONOS_CONTROL_BASE_URL}/groups/old-group/playbackMetadata/subscription"),
            call(f"{SONOS_CONTROL_BASE_URL}/groups/new-group/playbackMetadata/subscription"),
        ])
        self.assertEqual(
            {row["group_id"]: row["active"] for row in self.store.list_playback_metadata_subscriptions()},
            {"old-group": False, "historical-group": False, "new-group": True},
        )

    def test_a_second_gone_group_stops_recovery_and_clears_the_cache(self):
        target = self.select()
        for group_id in ("old-group", "new-group"):
            self.store.save_playback_metadata_subscription(group_id)
        self.sonos_get.side_effect = [self.discovered_group("old-group"), self.discovered_group("new-group")]
        self.sonos_post.side_effect = [{}, self.gone_error(), self.gone_error()]

        with patch.object(self.routes.logger, "exception"):
            response = self.client.post("/sonos/playback-target/subscribe")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.sonos_get.await_count, 2)
        self.assertEqual(self.sonos_post.await_count, 3)
        self.assertEqual(self.store.load_playback_target(), target)
        self.assertTrue(all(not row["active"] for row in self.store.list_playback_metadata_subscriptions()))

    def test_stale_discovery_never_retries_the_same_gone_group(self):
        self.select()
        self.store.save_playback_metadata_subscription("old-group")
        self.sonos_get.return_value = self.discovered_group("old-group")
        self.sonos_post.side_effect = [{}, self.gone_error()]

        with patch.object(self.routes.logger, "exception"):
            response = self.client.post("/sonos/playback-target/subscribe")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.sonos_get.await_count, 2)
        self.assertEqual(self.sonos_post.await_count, 2)
        self.assertIsNone(self.store.load_playback_target()["group_id"])
        self.assertFalse(self.store.list_playback_metadata_subscriptions()[0]["active"])

    def test_offline_recovery_retries_discovery_on_the_next_renewal_pass(self):
        target = self.select()
        self.store.save_playback_metadata_subscription("old-group")
        self.sonos_get.side_effect = [self.discovered_group("old-group"), self.discovered_group(None)]
        self.sonos_post.side_effect = [{}, self.gone_error()]

        response = self.client.post("/sonos/playback-target/subscribe")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.store.load_playback_target(), target)
        self.assertEqual(self.store.list_due_playback_metadata_subscriptions(172800), [])
        self.sonos_get.side_effect = None
        self.sonos_get.return_value = self.discovered_group("returned-group")
        self.sonos_post.side_effect = None
        self.sonos_get.reset_mock()
        self.sonos_post.reset_mock()

        result = self.renew()

        self.assertTrue(result["ok"])
        self.assertEqual(result["renewed"][0]["group_id"], "returned-group")
        self.sonos_get.assert_awaited_once()
        self.sonos_post.assert_awaited_once_with(f"{SONOS_CONTROL_BASE_URL}/groups/returned-group/playbackMetadata/subscription")

    def test_rediscovery_failure_keeps_the_gone_group_retired(self):
        self.select()
        self.store.save_playback_metadata_subscription("old-group")
        self.sonos_get.side_effect = [self.discovered_group("old-group"), SonosAPIError(503, "Unavailable")]
        self.sonos_post.side_effect = [{}, self.gone_error()]

        with patch.object(self.routes.logger, "exception"):
            response = self.client.post("/sonos/playback-target/subscribe")

        self.assertEqual(response.status_code, 502)
        self.assertIsNone(self.store.load_playback_target()["group_id"])
        self.assertFalse(self.store.list_playback_metadata_subscriptions()[0]["active"])
        self.assertEqual(self.sonos_post.await_count, 2)

    def test_non_gone_api_errors_do_not_trigger_recovery_or_retirement(self):
        self.select()
        self.cache_group("current-group")
        self.store.save_playback_metadata_subscription("current-group")
        self.sonos_get.return_value = self.discovered_group("current-group")
        for status_code in (403, 404, 429, 500, 503):
            with self.subTest(status_code=status_code), patch.object(self.routes.logger, "exception"):
                self.sonos_get.reset_mock()
                self.sonos_post.reset_mock()
                self.sonos_post.side_effect = [{}, SonosAPIError(status_code, "error")]

                response = self.client.post("/sonos/playback-target/subscribe")

                self.assertEqual(response.status_code, 502)
                self.sonos_get.assert_awaited_once()
                self.assertEqual(self.sonos_post.await_count, 2)
                self.assertEqual(self.store.load_playback_target()["group_id"], "current-group")
                self.assertTrue(self.store.list_playback_metadata_subscriptions()[0]["active"])

    def test_healthy_subscription_is_not_renewed_before_it_is_due(self):
        self.select()
        self.cache_group("current-group")
        self.store.save_playback_metadata_subscription("current-group")

        result = self.renew()

        self.assertTrue(result["ok"])
        self.assertEqual(result["due_count"], 0)
        self.sonos_get.assert_not_awaited()
        self.sonos_post.assert_not_awaited()

    def test_legacy_renewal_retires_gone_groups_without_guessing_a_speaker(self):
        self.store.save_playback_metadata_subscription("old-group")
        self.make_subscriptions_due()
        self.sonos_post.side_effect = self.gone_error()

        result = self.renew()

        self.assertFalse(result["ok"])
        self.assertFalse(result["reauthorization_required"])
        self.assertEqual(result["failed"][0]["status_code"], 410)
        self.assertEqual(result["failed"][0]["error_code"], "ERROR_RESOURCE_GONE")
        self.assertFalse(self.store.list_playback_metadata_subscriptions()[0]["active"])
        self.sonos_get.assert_not_awaited()
        self.assertEqual(self.renew()["due_count"], 0)
        self.sonos_post.assert_awaited_once()

    def test_explicit_group_endpoint_retires_a_gone_group_and_reports_410(self):
        self.store.save_playback_metadata_subscription("old-group")
        self.sonos_post.side_effect = self.gone_error()

        response = self.client.post("/sonos/subscribe/old-group")

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["detail"]["error_code"], "ERROR_RESOURCE_GONE")
        self.assertFalse(self.store.list_playback_metadata_subscriptions()[0]["active"])
        self.sonos_get.assert_not_awaited()

    def test_invalidation_is_scoped_to_the_user_and_failed_group(self):
        self.select()
        self.cache_group("current-group")
        self.store.save_playback_metadata_subscription("old-group")
        other_store = PostgresDataStore(self.db_url, uuid4().hex)
        other_store.save_playback_target("household-1", "player-2")
        other_store.update_playback_target_group("household-1", "player-2", "old-group")
        other_subscription = other_store.save_playback_metadata_subscription("old-group")

        self.store.invalidate_playback_metadata_subscription("old-group")

        self.assertEqual(self.store.load_playback_target()["group_id"], "current-group")
        self.assertEqual(other_store.load_playback_target()["group_id"], "old-group")
        self.assertEqual(other_store.list_playback_metadata_subscriptions(), [other_subscription])

    def test_reauthorization_during_recovery_is_not_reported_as_a_group_error(self):
        self.select()
        self.sonos_get.side_effect = [self.discovered_group("old-group"), SonosReauthorizationRequired("Start OAuth again.")]
        self.sonos_post.side_effect = [{}, self.gone_error()]

        response = self.client.post("/sonos/playback-target/subscribe")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["reauthorize_path"], "/oauth/start")
        self.assertIsNone(self.store.load_playback_target()["group_id"])
