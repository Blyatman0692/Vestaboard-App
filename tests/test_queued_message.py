import json
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID

from vestaboard.board_message import BoardMessage
from vestaboard.board_state import BoardState
from vestaboard.queued_message import QueuedMessage


class QueuedMessageTests(unittest.TestCase):
    def test_text_wire_format_preserves_content_and_metadata(self) -> None:
        message = QueuedMessage(
            message=BoardMessage(BoardState.SONOS, "sonos_app", text='BJÖRK\n"JÓGA"'),
            message_id="c2bb759b-919a-4687-b53a-ddeef40fda97",
            created_at=datetime(2026, 9, 23, 12, 30, 45, 123456, tzinfo=timezone.utc),
        )

        serialized = message.to_json()

        self.assertEqual(
            json.loads(serialized),
            {
                "schema_version": 1,
                "message_id": "c2bb759b-919a-4687-b53a-ddeef40fda97",
                "created_at": "2026-09-23T12:30:45.123456+00:00",
                "message": {
                    "state": "sonos",
                    "source": "sonos_app",
                    "text": 'BJÖRK\n"JÓGA"',
                },
            },
        )
        self.assertEqual(QueuedMessage.from_json(serialized), message)
        self.assertEqual(QueuedMessage.from_json(serialized.encode("utf-8")), message)

    def test_all_pipeline_layouts_round_trip(self) -> None:
        pipelines = (
            (BoardState.WEATHER, "weather_app"),
            (BoardState.WEATHER, "detailed_weather_app"),
            (BoardState.FLIGHT, "flight_app"),
            (BoardState.SONOS, "sonos_app"),
            (BoardState.STOCK, "stock_app"),
            (BoardState.COUNTDOWN, "countdown_app"),
        )
        layout = [[(row * 22 + column) % 70 for column in range(22)] for row in range(6)]
        for state, source in pipelines:
            with self.subTest(source=source):
                message = QueuedMessage(BoardMessage(state, source, layout=layout))

                restored = QueuedMessage.from_json(message.to_json())

                self.assertEqual(restored, message)
                self.assertIs(restored.message.state, state)
                self.assertIsNone(restored.message.text)
                self.assertNotIn("text", json.loads(message.to_json())["message"])

    def test_new_envelopes_get_distinct_ids_and_current_utc_timestamps(self) -> None:
        content = BoardMessage(BoardState.WEATHER, "weather_app", text="SUNNY")
        before = datetime.now(timezone.utc)
        first = QueuedMessage(content)
        second = QueuedMessage(content)
        after = datetime.now(timezone.utc)

        self.assertNotEqual(first.message_id, second.message_id)
        for message in (first, second):
            self.assertEqual(UUID(message.message_id).version, 4)
            self.assertIs(message.created_at.tzinfo, timezone.utc)
            self.assertLessEqual(before, message.created_at)
            self.assertLessEqual(message.created_at, after)

    def test_serialization_normalizes_timestamp_to_utc(self) -> None:
        message = QueuedMessage(
            BoardMessage(BoardState.FLIGHT, "flight_app", text="FLIGHT"),
            created_at=datetime(2026, 9, 23, 9, tzinfo=timezone(timedelta(hours=-7))),
        )

        self.assertEqual(json.loads(message.to_json())["created_at"], "2026-09-23T16:00:00+00:00")
        self.assertEqual(QueuedMessage.from_json(message.to_json()), message)

    def test_empty_text_is_preserved_as_text(self) -> None:
        message = QueuedMessage(BoardMessage(BoardState.UNKNOWN, "test", text=""))

        self.assertEqual(QueuedMessage.from_json(message.to_json()), message)

    def test_missing_envelope_fields_are_rejected_without_new_defaults(self) -> None:
        for field in ("schema_version", "message_id", "created_at", "message"):
            with self.subTest(field=field):
                payload = self._payload()
                del payload[field]
                with self.assertRaisesRegex(ValueError, "missing required fields"):
                    QueuedMessage.from_json(json.dumps(payload))

    def test_invalid_envelope_metadata_is_rejected(self) -> None:
        invalid_values = {
            "schema_version": [0, 2, "1", 1.0, True, None],
            "message_id": ["", " ", 123, None],
            "created_at": ["yesterday", "2026-09-23T09:00:00", 123, None],
            "message": [None, [], "SUNNY"],
        }
        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    payload = self._payload()
                    payload[field] = value
                    with self.assertRaises(ValueError):
                        QueuedMessage.from_json(json.dumps(payload))

    def test_malformed_content_is_rejected(self) -> None:
        invalid_messages = [
            {},
            {"state": "weather", "text": "SUNNY"},
            {"source": "weather_app", "text": "SUNNY"},
            {"state": "invalid", "source": "test", "text": "SUNNY"},
            {"state": "weather", "source": 123, "text": "SUNNY"},
            {"state": "weather", "source": "test"},
            {"state": "weather", "source": "test", "text": None, "layout": None},
            {"state": "weather", "source": "test", "text": "SUNNY", "layout": [[1]]},
            {"state": "weather", "source": "test", "text": 123},
        ]
        for layout in ("[[1]]", [1, 2], [["1"]], [[1.5]], [[True]], [None]):
            invalid_messages.append({"state": "weather", "source": "test", "layout": layout})

        for content in invalid_messages:
            with self.subTest(content=content):
                payload = self._payload()
                payload["message"] = content
                with self.assertRaises(ValueError):
                    QueuedMessage.from_json(json.dumps(payload))

    def test_invalid_json_and_non_object_payloads_are_rejected(self) -> None:
        for value in ("{", "null", "[]", '"message"', "42"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    QueuedMessage.from_json(value)

    @staticmethod
    def _payload() -> dict:
        return {
            "schema_version": 1,
            "message_id": "c2bb759b-919a-4687-b53a-ddeef40fda97",
            "created_at": "2026-09-23T12:30:45+00:00",
            "message": {"state": "weather", "source": "weather_app", "text": "SUNNY"},
        }
