import logging
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
            position.flight_number, 1, 11, "right", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            position.aircraft_type_display, 1, 22, "left", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            "ROUTE", 1, 11, "left", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            position.route, 1, 11, "right", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            "SPEED", 1, 11, "left", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            f"{position.speed_kmh} kmh", 1, 11, "right", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            "ALTITUDE", 1, 11, "left", "top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            f"{position.altitude_meters} m", 1, 11, "right", "top"
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

    # Time gate: only run between 08:00–23:00 Pacific Time
    if not utils.time_gate(logger, 8, 0, 23, 0):
        return

    container = build_flight_container()
    bounds = container.config.bounds.to_fr24_bounds()

    logger.info("Checking FR24 light live positions: bounds=%s limit=1", bounds)
    light_positions = container.flight_radar_client.get_live_positions_light(
        bounds=bounds,
        limit=1,
    )

    logger.info("Retrieved %d light flight positions", len(light_positions))
    if not light_positions:
        logger.info("No flight positions retrieved; skipping full lookup and Vestaboard update")
        return

    logger.info("Fetching FR24 full live position details: bounds=%s limit=1", bounds)
    positions = container.flight_radar_client.get_live_positions_full(
        bounds=bounds,
        limit=1,
    )

    logger.info("Retrieved %d full flight positions", len(positions))
    if not positions:
        logger.info("Light lookup found a flight, but full lookup returned none; skipping Vestaboard update")
        return

    position = positions[0]
    logger.info("Selected flight for Vestaboard: %s", position.console_summary)
    print(position.console_summary)

    _send_position_to_vestaboard(container, position)
    logger.info("Flight message sent successfully")


if __name__ == "__main__":
    run()
