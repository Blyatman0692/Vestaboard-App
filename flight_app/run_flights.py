import logging
import os
import sys

from app import build_flight_container
from flight_app.models import FlightInfo


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
)

logger = logging.getLogger(__name__)


def _railway_context() -> dict[str, str | None]:
    return {
        "RAILWAY_ENVIRONMENT_NAME": os.getenv("RAILWAY_ENVIRONMENT_NAME"),
        "RAILWAY_SERVICE_NAME": os.getenv("RAILWAY_SERVICE_NAME"),
        "RAILWAY_REPLICA_ID": os.getenv("RAILWAY_REPLICA_ID"),
    }


def _log_runtime_context() -> None:
    logger.info(
        "Flight runtime context: python=%s executable=%s cwd=%s module_file=%s "
        "log_level=%s railway=%s",
        sys.version.split()[0],
        sys.executable,
        os.getcwd(),
        __file__,
        LOG_LEVEL,
        _railway_context(),
    )


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
    _log_runtime_context()
    container = build_flight_container()
    logger.info(
        "Flight container built: bounds=%s opensky_timeout_s=%s "
        "opensky_token_timeout_s=%s opensky_retry_attempts=%s opensky_auth=%s "
        "anonymous_fallback_on_auth_network_error=%s",
        container.bounds.as_params(),
        container.opensky_client.timeout_s,
        container.opensky_client.token_timeout_s,
        container.opensky_client.retry_attempts,
        (
            "enabled"
            if container.opensky_client.client_id and container.opensky_client.client_secret
            else "disabled"
        ),
        container.opensky_client.anonymous_fallback_on_auth_network_error,
    )

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
    logger.info("Flight prototype job finished successfully")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        logger.exception("Flight prototype job failed")
        raise SystemExit(1)
