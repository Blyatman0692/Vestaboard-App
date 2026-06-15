import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


@dataclass(frozen=True)
class AggregateBar:
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    timestamp_ms: int | None
    vwap: float | None = None
    transactions: int | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "AggregateBar":
        return cls(
            open=_optional_float(data.get("o")),
            high=_optional_float(data.get("h")),
            low=_optional_float(data.get("l")),
            close=_optional_float(data.get("c")),
            volume=_optional_float(data.get("v")),
            timestamp_ms=_optional_int(data.get("t")),
            vwap=_optional_float(data.get("vw")),
            transactions=_optional_int(data.get("n")),
        )


@dataclass(frozen=True)
class TickerSnapshot:
    ticker: str
    day: AggregateBar | None
    previous_day: AggregateBar | None
    minute: AggregateBar | None
    last_trade_price: float | None
    todays_change: float | None
    todays_change_percent: float | None
    updated_ns: int | None

    @classmethod
    def from_api(
        cls,
        data: dict[str, Any],
        *,
        ticker: str,
    ) -> "TickerSnapshot":
        last_trade = data.get("lastTrade") or {}
        return cls(
            ticker=str(data.get("ticker") or ticker),
            day=AggregateBar.from_api(data["day"]) if data.get("day") else None,
            previous_day=(
                AggregateBar.from_api(data["prevDay"]) if data.get("prevDay") else None
            ),
            minute=AggregateBar.from_api(data["min"]) if data.get("min") else None,
            last_trade_price=_optional_float(last_trade.get("p")),
            todays_change=_optional_float(data.get("todaysChange")),
            todays_change_percent=_optional_float(data.get("todaysChangePerc")),
            updated_ns=_optional_int(data.get("updated")),
        )

    @property
    def latest_price(self) -> float | None:
        if self.last_trade_price is not None:
            return self.last_trade_price
        if self.minute is not None and self.minute.close is not None:
            return self.minute.close
        if self.day is not None:
            return self.day.close
        return None


@dataclass(frozen=True)
class StockPrice:
    ticker: str
    latest_price: float | None
    previous_close: float | None
    day: AggregateBar | None
    as_of_timestamp_ms: int | None
    is_end_of_day: bool = False

    @classmethod
    def from_snapshot(cls, snapshot: TickerSnapshot) -> "StockPrice":
        return cls(
            ticker=snapshot.ticker,
            latest_price=snapshot.latest_price,
            previous_close=(
                snapshot.previous_day.close
                if snapshot.previous_day is not None
                else None
            ),
            day=snapshot.day,
            as_of_timestamp_ms=cls._snapshot_timestamp_ms(snapshot),
        )

    @classmethod
    def from_daily_bars(
        cls,
        ticker: str,
        bars: list[AggregateBar],
    ) -> "StockPrice | None":
        if not bars:
            return None

        latest_bar = bars[0]
        previous_close = bars[1].close if len(bars) > 1 else None
        return cls(
            ticker=ticker,
            latest_price=latest_bar.close,
            previous_close=previous_close,
            day=latest_bar,
            as_of_timestamp_ms=latest_bar.timestamp_ms,
            is_end_of_day=True,
        )

    @property
    def price_change(self) -> float | None:
        if self.latest_price is None or self.previous_close is None:
            return None
        return self.latest_price - self.previous_close

    @property
    def price_change_percent(self) -> float | None:
        if self.price_change is None or self.previous_close in {None, 0}:
            return None
        return (self.price_change / self.previous_close) * 100

    @property
    def console_summary(self) -> str:
        return (
            f"{self.ticker:<6} "
            f"price={self._format_money(self.latest_price)} "
            f"change={self._format_price_change()} "
            f"prev_close={self._format_money(self.previous_close)} "
            f"high={self._format_money(self.day.high if self.day else None)} "
            f"low={self._format_money(self.day.low if self.day else None)} "
            f"volume={self._format_volume(self.day.volume if self.day else None)} "
            f"as_of={self._format_as_of()}"
        )

    @staticmethod
    def _snapshot_timestamp_ms(snapshot: TickerSnapshot) -> int | None:
        if snapshot.updated_ns is not None:
            return snapshot.updated_ns // 1_000_000
        if snapshot.minute is not None:
            return snapshot.minute.timestamp_ms
        if snapshot.day is not None:
            return snapshot.day.timestamp_ms
        return None

    def _format_price_change(self) -> str:
        if self.price_change is None:
            return "NA"
        if self.price_change_percent is None:
            return f"{self.price_change:+,.2f}"
        return f"{self.price_change:+,.2f} ({self.price_change_percent:+.2f}%)"

    def _format_as_of(self) -> str:
        if self.as_of_timestamp_ms is None:
            return "NA"

        as_of = datetime.fromtimestamp(
            self.as_of_timestamp_ms / 1000,
            ZoneInfo("America/New_York"),
        )
        if self.is_end_of_day:
            return as_of.strftime("%Y-%m-%d EOD ET")
        return as_of.strftime("%Y-%m-%d %H:%M ET")

    @staticmethod
    def _format_money(value: float | None) -> str:
        return "NA" if value is None else f"${value:,.2f}"

    @staticmethod
    def _format_volume(value: float | None) -> str:
        return "NA" if value is None else f"{value:,.0f}"


class MassiveApiError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        request_id: str | None = None,
    ):
        self.status_code = status_code
        self.message = message
        self.request_id = request_id

        error = f"Massive API error {status_code}: {message}"
        if request_id:
            error = f"{error} (request_id={request_id})"
        super().__init__(error)


class MassiveClient:
    BASE_URL = "https://api.massive.com"
    SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
    PREVIOUS_DAY_PATH = "/v2/aggs/ticker/{ticker}/prev"
    DAILY_BARS_PATH = "/v2/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout_s: int = 10,
        retry_attempts: int = 3,
        retry_base_delay_s: float = 0.8,
        retry_max_delay_s: float = 10.0,
        session: requests.Session | None = None,
    ):
        if not api_key:
            raise ValueError(
                "Missing Massive API key. Set MASSIVE_API_KEY or pass api_key=..."
            )
        if retry_attempts < 1:
            raise ValueError("Massive retry_attempts must be at least 1.")

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.retry_attempts = retry_attempts
        self.retry_base_delay_s = retry_base_delay_s
        self.retry_max_delay_s = retry_max_delay_s
        self._session = session or requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def get_ticker_snapshot(self, ticker: str) -> TickerSnapshot:
        ticker = self._normalize_ticker(ticker)
        payload = self._get_json(
            self.SNAPSHOT_PATH.format(ticker=quote(ticker, safe=""))
        )
        snapshot = payload.get("ticker")
        if not isinstance(snapshot, dict):
            raise MassiveApiError(
                200,
                f"Snapshot response did not include ticker data for {ticker}.",
                request_id=payload.get("request_id"),
            )
        return TickerSnapshot.from_api(snapshot, ticker=ticker)

    def get_previous_day_bar(
        self,
        ticker: str,
        *,
        adjusted: bool = True,
    ) -> AggregateBar | None:
        ticker = self._normalize_ticker(ticker)
        payload = self._get_json(
            self.PREVIOUS_DAY_PATH.format(ticker=quote(ticker, safe="")),
            params={"adjusted": str(adjusted).lower()},
        )
        results = payload.get("results") or []
        if not isinstance(results, list):
            raise MassiveApiError(
                200,
                f"Previous-day response had invalid results for {ticker}.",
                request_id=payload.get("request_id"),
            )
        return AggregateBar.from_api(results[0]) if results else None

    def get_daily_bars(
        self,
        ticker: str,
        *,
        from_date: str,
        to_date: str,
        adjusted: bool = True,
        sort: str = "desc",
        limit: int = 2,
    ) -> list[AggregateBar]:
        ticker = self._normalize_ticker(ticker)
        if sort not in {"asc", "desc"}:
            raise ValueError("Massive daily bars sort must be 'asc' or 'desc'.")
        if limit < 1 or limit > 50000:
            raise ValueError("Massive daily bars limit must be between 1 and 50000.")

        payload = self._get_json(
            self.DAILY_BARS_PATH.format(
                ticker=quote(ticker, safe=""),
                from_date=quote(from_date, safe=""),
                to_date=quote(to_date, safe=""),
            ),
            params={
                "adjusted": str(adjusted).lower(),
                "sort": sort,
                "limit": limit,
            },
        )
        results = payload.get("results") or []
        if not isinstance(results, list):
            raise MassiveApiError(
                200,
                f"Daily bars response had invalid results for {ticker}.",
                request_id=payload.get("request_id"),
            )
        return [AggregateBar.from_api(result) for result in results]

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("Massive ticker must not be empty.")
        return normalized

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                response = self._session.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=self.timeout_s,
                )

                if response.status_code >= 400:
                    if (
                        self._is_retryable_status(response.status_code)
                        and attempt < self.retry_attempts
                    ):
                        self._sleep_backoff(attempt, response=response)
                        continue
                    raise self._api_error(response)

                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Massive API response must be a JSON object.")
                return payload

            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt >= self.retry_attempts:
                    break
                self._sleep_backoff(attempt)
            except ValueError as exc:
                last_error = exc
                break

        assert last_error is not None
        raise last_error

    def _sleep_backoff(
        self,
        attempt: int,
        *,
        response: requests.Response | None = None,
    ) -> None:
        retry_after_s = None
        if response is not None and "Retry-After" in response.headers:
            try:
                retry_after_s = float(response.headers["Retry-After"])
            except ValueError:
                retry_after_s = None

        if retry_after_s is not None:
            time.sleep(max(0.0, retry_after_s))
            return

        backoff = min(
            self.retry_max_delay_s,
            self.retry_base_delay_s * (2 ** (attempt - 1)),
        )
        time.sleep(backoff + random.uniform(0.0, 0.5))

    @staticmethod
    def _api_error(response: requests.Response) -> MassiveApiError:
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        message = (
            payload.get("error")
            or payload.get("message")
            or response.reason
            or "Request failed"
        )
        return MassiveApiError(
            response.status_code,
            str(message),
            request_id=payload.get("request_id"),
        )
