import logging
import sys

from app import build_stock_container
from stock_app.massive_client import AggregateBar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def _format_money(value: float | None) -> str:
    return "N/A" if value is None else f"${value:,.2f}"


def _format_volume(value: float | None) -> str:
    return "N/A" if value is None else f"{value:,.0f}"


def _format_day_change(bar: AggregateBar) -> str:
    if bar.open is None or bar.close is None:
        return "N/A"

    change = bar.close - bar.open
    if bar.open == 0:
        return f"{change:+,.2f}"

    change_percent = (change / bar.open) * 100
    return f"{change:+,.2f} ({change_percent:+.2f}%)"


def format_stock_summary(ticker: str, bar: AggregateBar) -> str:
    return (
        f"{ticker:<6} "
        f"close={_format_money(bar.close)} "
        f"change={_format_day_change(bar)} "
        f"high={_format_money(bar.high)} "
        f"low={_format_money(bar.low)} "
        f"volume={_format_volume(bar.volume)}"
    )


def run() -> None:
    logger.info("Stock job started")

    container = build_stock_container()

    for ticker in container.config.tickers:
        logger.info("Fetching Massive previous-day bar: ticker=%s", ticker)
        try:
            bar = container.massive_client.get_previous_day_bar(ticker)
        except Exception:
            logger.exception("Error retrieving stock info: ticker=%s", ticker)
            raise

        if bar is None:
            logger.warning("No previous-day stock data returned: ticker=%s", ticker)
            continue

        summary = format_stock_summary(ticker, bar)
        logger.info("Retrieved stock info: %s", summary)


if __name__ == "__main__":
    run()
