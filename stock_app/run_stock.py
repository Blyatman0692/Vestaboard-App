import logging
import sys
from datetime import date, timedelta

from app import build_stock_container
from stock_app.massive_client import (
    MassiveApiError,
    StockPrice,
)
from vestaboard import utils
from vestaboard.board_message import BoardMessage
from vestaboard.board_state import BoardState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def _compose_stock_vbml_payload(stock_prices: list[StockPrice]) -> dict:
    vbml_components = []

    vbml_components.append(
        utils.compose_vbml_component(
            "{68}{68}MOST RECENT MARKET{68}{68}",
            justify="center",
            align="top",
            width=22,
            height=1
        )
    )

    for _stock_price in stock_prices:
        # Placeholder until the stock row content and layout parameters are defined.
        vbml_components.append(
            utils.compose_vbml_component(
                f"{_stock_price.ticker}", 1, 4, "left", "top"
            )
        )

        vbml_components.append(
            utils.compose_vbml_component(
                f"{_stock_price._format_money(_stock_price.latest_price)}", 1, 10, "right", "top"
            )
        )

        vbml_components.append(
            utils.compose_vbml_component(
                f"{_stock_price._format_price_change()}", 1, 8, "right", "top"
            )
        )

    return utils.compose_vbml_payload(vbml_components)


def _send_prices_to_vestaboard(
    container,
    stock_prices: list[StockPrice],
) -> None:
    vbml_payload = _compose_stock_vbml_payload(stock_prices)
    vbml_layout = container.board.vestaboard_messenger.vbml_compose_layout(
        vbml_payload
    )

    message = BoardMessage(BoardState.STOCK, "stock_app", layout=vbml_layout)
    container.board.display_manager.send(message)


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

    # Time gate: only run between 13:00–20:00 Pacific Time
    if not utils.time_gate(logger, 13, 0, 20, 0):
        return

    container = build_stock_container()
    stock_prices: list[StockPrice] = []

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
        stock_prices.append(stock_price)

    if not stock_prices:
        logger.warning("No stock prices retrieved; skipping Vestaboard update")
        return

    try:
        _send_prices_to_vestaboard(container, stock_prices)
        logger.info("Stock message sent successfully")
    except Exception:
        logger.exception("Error sending stock message")
        raise


if __name__ == "__main__":
    run()
