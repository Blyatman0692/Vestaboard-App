import logging
import sys
from datetime import date, timedelta

from app import build_stock_container
from stock_app.massive_client import (
    MassiveApiError,
    StockPrice,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def _get_latest_daily_price(container, ticker: str) -> StockPrice | None:
    to_date = date.today()
    from_date = to_date - timedelta(days=14)
    bars = container.massive_client.get_daily_bars(
        ticker,
        from_date=from_date.isoformat(),
        to_date=to_date.isoformat(),
        sort="desc",
        limit=2,
    )
    return StockPrice.from_daily_bars(ticker, bars)


def _get_stock_price(container, ticker: str) -> StockPrice | None:
    try:
        snapshot = container.massive_client.get_ticker_snapshot(ticker)
        return StockPrice.from_snapshot(snapshot)
    except MassiveApiError as exc:
        if exc.status_code != 403:
            raise

        logger.warning(
            "Ticker snapshot unavailable for %s; using latest available daily bars",
            ticker,
        )
        return _get_latest_daily_price(container, ticker)


def run() -> None:
    logger.info("Stock job started")

    container = build_stock_container()

    for ticker in container.config.tickers:
        logger.info("Fetching latest Massive stock price: ticker=%s", ticker)
        try:
            stock_price = _get_stock_price(container, ticker)
        except Exception:
            logger.exception("Error retrieving stock info: ticker=%s", ticker)
            raise

        if stock_price is None:
            logger.warning("No stock price data returned: ticker=%s", ticker)
            continue

        logger.info("Retrieved stock info: %s", stock_price.console_summary)


if __name__ == "__main__":
    run()
