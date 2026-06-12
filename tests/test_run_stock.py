import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from stock_app.massive_client import AggregateBar, MassiveApiError, TickerSnapshot
from stock_app.run_stock import run


class RunStockTests(unittest.TestCase):
    @patch("stock_app.run_stock.logger")
    @patch("stock_app.run_stock.build_stock_container")
    def test_run_logs_each_ticker_snapshot(
        self,
        build_container: Mock,
        logger: Mock,
    ) -> None:
        snapshot = self._snapshot()
        client = Mock()
        client.get_ticker_snapshot.return_value = snapshot
        build_container.return_value = SimpleNamespace(
            config=SimpleNamespace(tickers=("AAPL",)),
            massive_client=client,
        )

        run()

        client.get_ticker_snapshot.assert_called_once_with("AAPL")
        logger.info.assert_any_call(
            "Retrieved stock info: %s",
            "AAPL   price=$204.25 change=+6.25 (+3.16%) "
            "prev_close=$198.00 high=$205.00 low=$198.50 volume=1,234,567 "
            "as_of=2026-06-12 15:28 ET",
        )

    @patch("stock_app.run_stock.logger")
    @patch("stock_app.run_stock.build_stock_container")
    def test_run_falls_back_to_latest_daily_bars(
        self,
        build_container: Mock,
        logger: Mock,
    ) -> None:
        snapshot_error = MassiveApiError(403, "Not entitled")
        latest_bar = self._snapshot().day
        previous_bar = self._snapshot().previous_day
        client = Mock()
        client.get_ticker_snapshot.side_effect = snapshot_error
        client.get_daily_bars.return_value = [latest_bar, previous_bar]
        build_container.return_value = SimpleNamespace(
            config=SimpleNamespace(tickers=("AAPL",)),
            massive_client=client,
        )

        run()

        logger.info.assert_any_call(
            "Retrieved stock info: %s",
            "AAPL   price=$204.00 change=+6.00 (+3.03%) "
            "prev_close=$198.00 high=$205.00 low=$198.50 volume=1,234,567 "
            "as_of=2026-06-11 EOD ET",
        )
        self.assertEqual(client.get_daily_bars.call_args.kwargs["sort"], "desc")
        self.assertEqual(client.get_daily_bars.call_args.kwargs["limit"], 2)

    @staticmethod
    def _snapshot() -> TickerSnapshot:
        return TickerSnapshot(
            ticker="AAPL",
            day=AggregateBar(
                open=200,
                high=205,
                low=198.5,
                close=204,
                volume=1234567,
                timestamp_ms=_timestamp_ms(2026, 6, 11),
            ),
            previous_day=AggregateBar(
                open=195,
                high=200,
                low=194,
                close=198,
                volume=1000000,
                timestamp_ms=_timestamp_ms(2026, 6, 10),
            ),
            minute=None,
            last_trade_price=204.25,
            todays_change=-999,
            todays_change_percent=-999,
            updated_ns=_timestamp_ms(2026, 6, 12, 15, 28) * 1_000_000,
        )


def _timestamp_ms(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
) -> int:
    timestamp = datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=ZoneInfo("America/New_York"),
    ).timestamp()
    return int(timestamp * 1000)
