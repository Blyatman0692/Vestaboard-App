from datetime import datetime
from logging import Logger
from zoneinfo import ZoneInfo

from typing import List, Dict, Any

def compose_vbml_payload(components: List[dict]) -> Dict[str, Any]:
    return {
        "style": {
            "height": 6,
            "width": 22,
        },
        "components": components
    }

def compose_vbml_component(template: str,
                           height: int = 1,
                           width:int = 22,
                           justify: str = "left",
                           align: str = "top"
                           ):
    return {
        "style": {
            "height": height,
            "width": width,
            "justify": justify,
            "align": align,
        },
        "template": template
    }

def time_gate(logger: Logger, start_hour: int, start_minute: int, end_hour: int, end_minute: int):
    now_pt = datetime.now(ZoneInfo("America/Los_Angeles"))

    now_m = now_pt.hour * 60 + now_pt.minute
    start_m = start_hour * 60 + start_minute
    end_m = end_hour * 60 + end_minute

    allowed = start_m <= now_m <= end_m

    if not allowed:
        logger.info(
            "Outside allowed PT window (%02d:%02d-%02d:%02d). Current PT time: %s. Skipping run.",
            start_hour, start_minute, end_hour, end_minute,
            now_pt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        )
        return False

    return True