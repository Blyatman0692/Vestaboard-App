import logging
import sys

from dotenv import load_dotenv

from countdown_app.countdown import CountDown
from countdown_app.targets import TARGET_DATES

from datetime import datetime
from zoneinfo import ZoneInfo

import utils
from vestaboard import VestaboardMessenger


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
)

logger = logging.getLogger(__name__)

def run():
    load_dotenv(override=False)

    logger.info("Countdown job started")

    # Time gate: only run between 08:00–08:05 Pacific Time
    if not utils.time_gate(logger, 8, 0, 8, 5):
        return

    vb = VestaboardMessenger()
    ct = CountDown(TARGET_DATES)

    try:
        results = ct.calculate_date_delta()
        logger.info("Successfully calculated countdowns (%d targets)", len(results))
    except Exception:
        logger.exception("Error calculating countdowns")
        raise

    if not results:
        logger.warning("No countdown results returned; skipping message send.")
        return

    vbml_components = []

    vbml_components.append(
        utils.compose_vbml_component(
            "time until",
            height=1,
            width=11,
            justify="left",
            align="top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            "days",
            height=1,
            width=11,
            justify="right",
            align="top"
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            "{63}{64}{65}{66}{67}{68}{63}{64}{65}{66}{67}{68}{63}{64}{65}{66}{67}{68}",
            height=1,
            width=22,
            justify="center",
            align="top"
        )
    )


    for description, result in results.items():
        description_component = utils.compose_vbml_component(
            description,
            height=1,
            width=16,
            justify="left",
            align="top"
        )
        vbml_components.append(description_component)

        timedelta_component = utils.compose_vbml_component(
            str(CountDown.breakdown(result.delta)["days"]),
            height=1,
            width=6,
            justify="right",
            align="top"
        )
        vbml_components.append(timedelta_component)

    vbml_payload = utils.compose_vbml_payload(vbml_components)
    logger.debug("VBML payload prepared")

    vbml_layout = vb.vbml_compose_layout(vbml_payload)

    try:
        vb.send_layout(vbml_layout)
        logger.info("Countdown message sent successfully")
    except Exception:
        logger.exception("Error sending countdown message")
        raise

if __name__ == "__main__":
    run()
