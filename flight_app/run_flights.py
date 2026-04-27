import logging
import sys

from app import build_flight_container
from flight_app.models import FlightInfo


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
)

logger = logging.getLogger(__name__)


def format_flight_info(flight: FlightInfo) -> str:
    altitude = f"{flight.altitude_ft} ft" if flight.altitude_ft is not None else "unknown"
    speed = f"{flight.speed_kt} kt" if flight.speed_kt is not None else "unknown"
    heading = flight.heading_cardinal or "unknown"
    callsign = flight.callsign or "unknown"
    last_contact = flight.last_contact.isoformat() if flight.last_contact else "unknown"

    return "\n".join(
        [
            "Current flight in configured area:",
            f"  callsign: {callsign}",
            f"  icao24: {flight.icao24}",
            f"  origin_country: {flight.origin_country or 'unknown'}",
            f"  latitude: {flight.latitude}",
            f"  longitude: {flight.longitude}",
            f"  altitude: {altitude}",
            f"  speed: {speed}",
            f"  heading: {heading}",
            f"  true_track_deg: {flight.true_track_deg}",
            f"  vertical_rate_mps: {flight.vertical_rate_mps}",
            f"  on_ground: {flight.on_ground}",
            f"  squawk: {flight.squawk or 'unknown'}",
            f"  last_contact_utc: {last_contact}",
        ]
    )


def run() -> None:
    logger.info("Flight prototype job started")
    container = build_flight_container()

    flights = container.opensky_client.get_flights_in_bounds(container.bounds)

    if not flights:
        logger.info("No flights found in configured area.")
        return

    if len(flights) > 1:
        logger.warning(
            "Expected one flight in configured area, but found %d. Printing the first result.",
            len(flights),
        )

    print(format_flight_info(flights[0]))


if __name__ == "__main__":
    run()
