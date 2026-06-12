import unittest
from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from stock_app.massive_client import (
    AggregateBar,
    MassiveApiError,
    MassiveClient,
    StockPrice,
    TickerSnapshot,
)


class MassiveClientTests(unittest.TestCase):
    def test_get_ticker_snapshot_returns_typed_snapshot(self) -> None:
        session = Mock()
        session.get.return_value = self._response(
            {
                "status": "OK",
                "ticker": {
                    "day": {"o": 200, "h": 205, "l": 199, "c": 204, "v": 1000},
                    "prevDay": {"c": 198},
                    "lastTrade": {"p": 204.25},
                    "todaysChange": 6.25,
                    "todaysChangePerc": 3.1566,
                    "updated": 123456789,
                },
            }
        )
        client = MassiveClient("secret", session=session)

        snapshot = client.get_ticker_snapshot(" aapl ")

        self.assertEqual(snapshot.ticker, "AAPL")
        self.assertEqual(snapshot.latest_price, 204.25)
        self.assertEqual(snapshot.previous_day.close, 198)
        session.get.assert_called_once_with(
            "https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers/AAPL",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer secret",
            },
            params=None,
            timeout=10,
        )

    def test_get_previous_day_bar_returns_none_when_no_results(self) -> None:
        session = Mock()
        session.get.return_value = self._response({"status": "OK", "results": []})
        client = MassiveClient("secret", session=session)

        result = client.get_previous_day_bar("MSFT", adjusted=False)

        self.assertIsNone(result)
        self.assertEqual(
            session.get.call_args.kwargs["params"],
            {"adjusted": "false"},
        )

    def test_get_daily_bars_returns_typed_bars(self) -> None:
        session = Mock()
        session.get.return_value = self._response(
            {
                "status": "OK",
                "results": [
                    {"o": 200, "h": 205, "l": 199, "c": 204, "v": 1000},
                    {"o": 195, "h": 200, "l": 194, "c": 198, "v": 900},
                ],
            }
        )
        client = MassiveClient("secret", session=session)

        bars = client.get_daily_bars(
            " aapl ",
            from_date="2026-06-01",
            to_date="2026-06-12",
        )

        self.assertEqual([bar.close for bar in bars], [204, 198])
        session.get.assert_called_once_with(
            "https://api.massive.com/v2/aggs/ticker/AAPL/range/1/day/2026-06-01/2026-06-12",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer secret",
            },
            params={
                "adjusted": "true",
                "sort": "desc",
                "limit": 2,
            },
            timeout=10,
        )

    def test_http_error_raises_massive_api_error(self) -> None:
        session = Mock()
        session.get.return_value = self._response(
            {"status": "ERROR", "error": "Not authorized", "request_id": "abc"},
            status_code=401,
            reason="Unauthorized",
        )
        client = MassiveClient("secret", retry_attempts=1, session=session)

        with self.assertRaises(MassiveApiError) as context:
            client.get_ticker_snapshot("AAPL")

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.request_id, "abc")

    @staticmethod
    def _response(
        payload: dict,
        *,
        status_code: int = 200,
        reason: str = "OK",
    ) -> Mock:
        response = Mock()
        response.status_code = status_code
        response.reason = reason
        response.headers = {}
        response.json.return_value = payload
        return response


class StockPriceTests(unittest.TestCase):
    def test_from_snapshot_calculates_change_and_formats_summary(self) -> None:
        stock_price = StockPrice.from_snapshot(self._snapshot())

        self.assertEqual(stock_price.price_change, 6.25)
        self.assertAlmostEqual(stock_price.price_change_percent, 3.1565656565)
        self.assertEqual(
            stock_price.console_summary,
            "AAPL   price=$204.25 change=+6.25 (+3.16%) "
            "prev_close=$198.00 high=$205.00 low=$198.50 volume=1,234,567 "
            "as_of=2026-06-12 15:28 ET",
        )

    def test_from_daily_bars_uses_latest_two_closes(self) -> None:
        snapshot = self._snapshot()

        stock_price = StockPrice.from_daily_bars(
            "AAPL",
            [snapshot.day, snapshot.previous_day],
        )

        self.assertIsNotNone(stock_price)
        self.assertEqual(stock_price.latest_price, 204)
        self.assertEqual(stock_price.previous_close, 198)
        self.assertTrue(stock_price.is_end_of_day)
        self.assertEqual(stock_price._format_as_of(), "2026-06-11 EOD ET")

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
