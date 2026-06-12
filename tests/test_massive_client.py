import unittest
from unittest.mock import Mock

from stock_app.massive_client import MassiveApiError, MassiveClient


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
