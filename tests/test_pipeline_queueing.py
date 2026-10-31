import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
from app.config import BoardConfig
from app.container import build_board_container
from countdown_app import run_countdown
from flight_app import run_flight
from redis_data_store import RedisDataStore
from sonos_app.event_processor import EventProcessor
from vestaboard.board_state import BoardState
from vestaboard.message_queue import RedisMessageQueue
from vestaboard.queued_message import QueuedMessage
from vestaboard.vestaboard import VestaboardMessenger
from weather_app import run_detailed_weather, run_weather
from weather_app.weather import (
    CurrentConditions,
    DailyForecast,
    DetailedWeather,
    WeatherNow,
)


class PipelineQueueingTests(unittest.TestCase):
    def setUp(self) -> None:
        time_gate = patch("vestaboard.utils.time_gate", return_value=True)
        time_gate.start()
        self.addCleanup(time_gate.stop)
        self.layout = [[0] * 22 for _ in range(6)]
        self.messenger = Mock(spec=VestaboardMessenger)
        self.messenger.vbml_compose_layout.return_value = self.layout
        self.store = Mock(spec=RedisDataStore)
        self.board = SimpleNamespace(
            vestaboard_messenger=self.messenger,
            redis_data_store=self.store,
            message_queue=RedisMessageQueue(self.store),
            display_manager=Mock(),
        )

    def assert_queued(self, state: BoardState, source: str) -> None:
        self.store.enqueue_message.assert_called_once()
        queued_message = QueuedMessage.from_json(
            self.store.enqueue_message.call_args.args[0]
        )
        self.assertEqual(queued_message.message.state, state)
        self.assertEqual(queued_message.message.source, source)
        self.assertEqual(queued_message.message.layout, self.layout)
        self.assert_no_display_changes()

    def assert_no_display_changes(self) -> None:
        self.board.display_manager.send.assert_not_called()
        self.messenger.send_message.assert_not_called()
        self.messenger.send_layout.assert_not_called()
        self.messenger.set_transition.assert_not_called()
        self.store.set_current_record.assert_not_called()

    def test_weather_enqueues_serialized_layout(self) -> None:
        client = Mock()
        client.get_current_weather_multi_cities.return_value = [
            WeatherNow("WOODINVILLE", 15.5, "C", 5, "kmh")
        ]
        container = SimpleNamespace(board=self.board, weather_client=client)

        with patch.object(run_weather, "build_weather_container", return_value=container):
            run_weather.run()

        self.assert_queued(BoardState.WEATHER, "weather_app")

    def test_detailed_weather_enqueues_serialized_layout(self) -> None:
        client = Mock()
        sunrise = datetime(2026, 10, 8, 7, tzinfo=timezone.utc)
        client.get_detailed_weather.return_value = DetailedWeather(
            city="WOODINVILLE",
            current=CurrentConditions(15.5, 14.5, "CLEAR", 2.0, 30),
            today=DailyForecast(
                maximum_temperature=20,
                minimum_temperature=10,
                maximum_uv_index=3,
                maximum_precipitation_probability=10,
                sunrise=sunrise,
                sunset=sunrise + timedelta(hours=12),
                next_sunrise=sunrise + timedelta(days=1),
            ),
            temperature_unit="C",
        )
        container = SimpleNamespace(board=self.board, weather_client=client)

        with patch.object(run_detailed_weather, "build_weather_container", return_value=container):
            run_detailed_weather.run()

        self.assert_queued(BoardState.WEATHER, "detailed_weather_app")

    def test_countdown_enqueues_serialized_layout(self) -> None:
        results = {"HOLIDAY": SimpleNamespace(delta=timedelta(days=30))}
        with (
            patch.object(run_countdown, "build_board_container", return_value=self.board),
            patch.object(run_countdown.CountDown, "calculate_date_delta", return_value=results),
        ):
            run_countdown.run()

        self.assert_queued(BoardState.COUNTDOWN, "countdown_app")

    def test_flight_is_marked_seen_after_queue_accepts_it(self) -> None:
        container = self.flight_container()

        def accept_message(payload_json: str) -> None:
            self.store.mark_flight_seen.assert_not_called()

        self.store.enqueue_message.side_effect = accept_message
        with patch.object(run_flight, "build_flight_container", return_value=container):
            run_flight.run()

        self.assert_queued(BoardState.FLIGHT, "flight_app")
        self.store.mark_flight_seen.assert_called_once_with("flight-1")

    def test_failed_flight_enqueue_does_not_mark_flight_seen(self) -> None:
        container = self.flight_container()
        self.store.enqueue_message.side_effect = ConnectionError("Redis unavailable")

        with patch.object(run_flight, "build_flight_container", return_value=container):
            with self.assertRaises(ConnectionError):
                run_flight.run()

        self.store.mark_flight_seen.assert_not_called()
        self.assert_no_display_changes()

    def test_sonos_enqueues_serialized_layout(self) -> None:
        processor = EventProcessor(self.messenger, self.board.message_queue)

        processor.process_metadata(self.playback_metadata())

        self.assert_queued(BoardState.SONOS, "sonos_app")

    def test_sonos_queue_failure_propagates_to_webhook_caller(self) -> None:
        processor = EventProcessor(self.messenger, self.board.message_queue)
        self.store.enqueue_message.side_effect = ConnectionError("Redis unavailable")

        with self.assertRaises(ConnectionError):
            processor.process_metadata(self.playback_metadata())

        self.assert_no_display_changes()

    def test_irrelevant_sonos_metadata_does_not_enqueue(self) -> None:
        processor = EventProcessor(self.messenger, self.board.message_queue)

        processor.process_metadata(None)

        self.store.enqueue_message.assert_not_called()
        self.messenger.vbml_compose_layout.assert_not_called()

    def flight_container(self) -> SimpleNamespace:
        position = SimpleNamespace(
            fr24_id="flight-1",
            flight_number="AB123",
            aircraft_type_board_display="BOEING 737",
            route="SEA-SFO",
            speed_kmh=800,
            altitude_meters=10000,
            console_summary="AB123 SEA-SFO",
        )
        self.store.has_seen_flight.return_value = False
        client = Mock()
        client.get_live_positions_light.return_value = [position]
        client.get_live_positions_full.return_value = [position]
        return SimpleNamespace(
            board=self.board,
            config=Mock(),
            flight_radar_client=client,
        )

    @staticmethod
    def playback_metadata() -> SimpleNamespace:
        return SimpleNamespace(
            group_id="group-1",
            track_name="JOGA",
            artist_name="BJORK",
            album_name="HOMOGENIC",
        )


class QueueWiringTests(unittest.TestCase):
    def test_board_container_queue_uses_shared_redis_store(self) -> None:
        with (
            patch("app.container.VestaboardMessenger"),
            patch("app.container.RedisDataStore") as store_class,
        ):
            board = build_board_container(BoardConfig("test-key", "redis://example.test"))

        self.assertIsInstance(board.message_queue, RedisMessageQueue)
        self.assertIs(board.message_queue.redis_data_store, store_class.return_value)
        self.assertIs(board.redis_data_store, store_class.return_value)

    def test_legacy_entry_point_uses_weather_pipeline(self) -> None:
        with patch.object(main, "run") as run:
            self.assertEqual(main.main(), 0)

        run.assert_called_once_with()

    def test_legacy_entry_point_reports_enqueue_failure(self) -> None:
        with (
            patch.object(main, "run", side_effect=ConnectionError("Redis unavailable")),
            patch("sys.stderr"),
        ):
            self.assertEqual(main.main(), 1)
