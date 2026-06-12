import unittest
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from stock_app.massive_client import AggregateBar
from stock_app.run_stock import format_stock_summary, run


class StockSummaryTests(unittest.TestCase):
    def test_format_stock_summary_includes_daily_market_data(self) -> None:
        bar = AggregateBar(
            open=200,
            high=205,
            low=198.5,
            close=204,
            volume=1234567,
            timestamp_ms=123456789,
        )

        summary = format_stock_summary("AAPL", bar)

        self.assertEqual(
            summary,
            "AAPL   close=$204.00 change=+4.00 (+2.00%) "
            "high=$205.00 low=$198.50 volume=1,234,567",
        )

    @patch("stock_app.run_stock.build_stock_container")
    def test_run_prints_each_available_ticker(self, build_container: Mock) -> None:
        bar = AggregateBar(
            open=100,
            high=105,
            low=99,
            close=102,
            volume=1000,
            timestamp_ms=123456789,
        )
        client = Mock()
        client.get_previous_day_bar.side_effect = [bar, None]
        build_container.return_value = SimpleNamespace(
            config=SimpleNamespace(tickers=("AAPL", "MSFT")),
            massive_client=client,
        )

        output = StringIO()
        with patch("sys.stdout", output):
            run()

        client.get_previous_day_bar.assert_any_call("AAPL")
        client.get_previous_day_bar.assert_any_call("MSFT")
        self.assertEqual(
            output.getvalue(),
            "AAPL   close=$102.00 change=+2.00 (+2.00%) "
            "high=$105.00 low=$99.00 volume=1,000\n",
        )
