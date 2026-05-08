import logging
import os
import sys

from app import build_flight_container
from vestaboard import utils
from vestaboard.board_message import BoardMessage
from vestaboard.board_state import BoardState
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


def _flight_number(position: FlightPosition) -> str:
    return position.flight or position.callsign or position.fr24_id


def _flight_route(position: FlightPosition) -> str:
    origin = position.orig_iata or position.orig_icao or "?"
    destination = position.dest_iata or position.dest_icao or "?"
    return f"{origin} TO {destination}"


def _speed_kmh(position: FlightPosition) -> int:
    return round(position.gspeed * 1.852)


def _altitude_meters(position: FlightPosition) -> int:
    return round(position.alt * 0.3048)


def _compose_flight_vbml_payload(position: FlightPosition) -> dict:
    vbml_components = []
    
    vbml_components.append(
        utils.compose_vbml_component(
            "Flying over now", 1, 22, "left", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            "FLIGHT", 1, 11, "left", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            _flight_number(position), 1, 11, "right", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            position.aircraft_type or "?", 1, 22, "left", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            "ROUTE", 1, 11, "left", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            _flight_route(position), 1, 11, "right", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            "SPEED", 1, 11, "left", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            f"{_speed_kmh(position)} kmh", 1, 11, "right", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            "ALTITUDE", 1, 11, "left", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            f"{_altitude_meters(position)} m", 1, 11, "right", "top"
        )
    )

    return utils.compose_vbml_payload(vbml_components)


def _send_position_to_vestaboard(container, position: FlightPosition) -> None:
    vbml_payload = _compose_flight_vbml_payload(position)
    vbml_layout = container.board.vestaboard_messenger.vbml_compose_layout(vbml_payload)

    msg = BoardMessage(BoardState.FLIGHT, "flight_app", layout=vbml_layout)
    container.board.display_manager.send(msg)


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
    if not positions:
        logger.info("No flight positions retrieved; skipping Vestaboard update")
        return

    position = positions[0]
    logger.info("Selected flight for Vestaboard: %s", _format_position(position))
    print(_format_position(position))

    _send_position_to_vestaboard(container, position)
    logger.info("Flight message sent successfully")


if __name__ == "__main__":
    run()
