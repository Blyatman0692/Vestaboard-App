import logging
import os
import sys

from app import build_flight_container
from flight_app.flight_radar_client import FlightPosition

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def _get_limit() -> int:
    raw_limit = os.environ.get("FLIGHT_LIMIT", "10")
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise ValueError("FLIGHT_LIMIT must be an integer.") from exc

    if limit <= 0:
        raise ValueError("FLIGHT_LIMIT must be greater than 0.")

    return limit


def _format_position(position: FlightPosition) -> str:
    return (
        f"{position.display_name:<8} "
        f"{position.route:<7} "
        f"{position.aircraft_type or '?':<4} "
        f"alt={position.alt:<5} "
        f"speed={position.gspeed:<3}kt "
        f"src={position.source}"
    )


def run() -> None:
    logger.info("Flight job started")

    container = build_flight_container()
    bounds = container.config.bounds.to_fr24_bounds()
    limit = _get_limit()

    logger.info("Fetching FR24 live positions: bounds=%s limit=%d", bounds, limit)
    positions = container.flight_radar_client.get_live_positions_full(
        bounds=bounds,
        limit=limit,
    )

    logger.info("Retrieved %d flight positions", len(positions))
    for position in positions:
        print(_format_position(position))


if __name__ == "__main__":
    run()
