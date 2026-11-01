import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import psycopg
from psycopg.conninfo import make_conninfo

from sonos_app.data_store import PostgresDataStore
from sonos_app.config import SONOS_CONTROL_BASE_URL
from sonos_app.sonos_client import SonosClient, SonosReauthorizationRequired
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
        self.assertEqual(self.sonos_post.await_count, 2)

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
                self.sonos_post.assert_not_awaited()

    def test_discovery_failure_preserves_the_cached_group(self):
        self.select()
        self.cache_group("last-known-group")
        for error in (RuntimeError("Sonos API error 503"), httpx.ConnectError("Unavailable")):
            with self.subTest(error=error), patch.object(self.routes.logger, "exception"):
                self.sonos_get.side_effect = error

                response = self.client.post("/sonos/playback-target/subscribe")

                self.assertEqual(response.status_code, 502)
                self.assertEqual(self.store.load_playback_target()["group_id"], "last-known-group")
                self.assertEqual(self.store.list_playback_metadata_subscriptions(), [])
                self.sonos_post.assert_not_awaited()

    def test_failed_subscription_is_not_saved(self):
        self.select()
        self.sonos_get.return_value = {"groups": [{"id": "new-group", "playerIds": ["player-1"]}]}
        self.sonos_post.side_effect = RuntimeError("Sonos API error 410")

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
                self.sonos_post.assert_not_awaited()

    def test_cached_group_update_is_scoped_to_the_user(self):
        self.select()
        other_store = PostgresDataStore(self.db_url, uuid4().hex)
        other_target = other_store.save_playback_target("household-1", "player-1")

        self.cache_group("group-1")

        self.assertEqual(other_store.load_playback_target(), other_target)
