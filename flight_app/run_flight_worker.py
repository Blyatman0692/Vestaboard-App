import logging
import os
import signal
import sys
import time

from flight_app.run_flight import run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)
_shutdown_requested = False


def _get_poll_interval_s() -> int:
    raw_value = os.environ.get("FLIGHT_WORKER_POLL_INTERVAL_S", "60")
    try:
        poll_interval_s = int(raw_value)
    except ValueError as exc:
        raise ValueError("FLIGHT_WORKER_POLL_INTERVAL_S must be an integer.") from exc

    if poll_interval_s <= 0:
        raise ValueError("FLIGHT_WORKER_POLL_INTERVAL_S must be greater than 0.")

    return poll_interval_s


def _request_shutdown(signum, _frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Received signal %s; stopping after current iteration", signum)


def worker() -> None:
    poll_interval_s = _get_poll_interval_s()
    logger.info("Flight worker started with poll interval %d seconds", poll_interval_s)

    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    while not _shutdown_requested:
        started_at = time.monotonic()

        try:
            run()
        except Exception:
            logger.exception("Flight worker iteration failed")

        elapsed_s = time.monotonic() - started_at
        sleep_s = max(0.0, poll_interval_s - elapsed_s)

        if sleep_s:
            logger.info("Sleeping %.1f seconds before next flight check", sleep_s)
            time.sleep(sleep_s)

    logger.info("Flight worker stopped")


if __name__ == "__main__":
    worker()
