import logging
import os
import sys
from typing import List, Optional

from dotenv import load_dotenv

from weather_app.weather_header import WeatherHeader
from weather_app.weather import WeatherNow, WeatherClient, format_weather_line

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

def format_string(label: str, value: float, unit: Optional[str] = None) -> str:
    """
    Fixed-width 10 chars:
    - label column: 5 chars (fits 'LIKE:')
    - value column: 5 chars (right-aligned)
    """
    total_width = 10
    label_width = 5
    value_width = total_width - label_width

    # Ensure label fits exactly in label column
    label_fixed = f"{label:<{label_width}}"[:label_width]

    # 1-decimal value
    rounded = round(float(value), 1)
    value_core = f"{rounded:.1f}"

    # Append unit only if provided
    value_str = f"{value_core}{unit}" if unit else value_core

    # Right-align value in its column (truncate from left if somehow too long)
    if len(value_str) > value_width:
        value_str = value_str[-value_width:]

    return f"{label_fixed}{value_str:>{value_width}}"



def run():
    logger.info("Detailed weather job started")

    load_dotenv(override=False)

    # Time gate: only run between 08:00–23:00 Pacific Time
    if not utils.time_gate(logger, 8, 0, 23, 0):
        return

    wc = WeatherClient()
    weather_header = WeatherHeader()
    vb = VestaboardMessenger()

    detailed = wc.get_detailed_weather("WOODINVILLE", 47.75, -122.16)

    vbml_components = []
    for hc in weather_header.compose_header_components():
        vbml_components.append(hc)

    vbml_components.append(
        utils.compose_vbml_component(
            detailed.city,
            justify="left",
            align="top",
            height=1,
            width=11
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            detailed.condition,
            justify="right",
            align="top",
            height=1,
            width=11
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            format_string("NOW:", detailed.temp_now, detailed.unit),
            justify="left",
            align="top",
            height=1,
            width=11
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            format_string("UVI:", detailed.uv_idx),
            justify="right",
            align="top",
            height=1,
            width=11
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            format_string("MAX:", detailed.temp_max, detailed.unit),
            justify="left",
            align="top",
            height=1,
            width=11
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            format_string("RAIN:", detailed.rain_chance_today, "%"),
            justify="right",
            align="top",
            height=1,
            width=11
        )
    )


    vbml_components.append(
        utils.compose_vbml_component(
            format_string("MIN:", detailed.temp_min, detailed.unit),
            justify="left",
            align="top",
            height=1,
            width=22
        )
    )

    vbml_components.append(
        utils.compose_vbml_component(
            format_string("LIKE:", detailed.feels_like, detailed.unit),
            justify="left",
            align="top",
            height=1,
            width=22
        )
    )

    vbml_payload = utils.compose_vbml_payload(vbml_components)
    logger.debug("VBML payload prepared")
    vbml_layout = vb.vbml_compose_layout(vbml_payload)

    try:
        vb.send_layout(vbml_layout)
        logger.info("Message sent successfully")
    except Exception:
        logger.exception("Error sending message")
        raise

    print(detailed)

if __name__ == "__main__":
    run()
