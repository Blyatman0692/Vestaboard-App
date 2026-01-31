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
    if not (start_hour <= now_pt.hour <= end_hour
            and start_minute <= now_pt.minute <= end_minute):
        logger.info(
            "Outside allowed PT window (08–23). Current PT time: %s. Skipping run.",
            now_pt.strftime("%Y-%m-%d %H:%M:%S")
        )
        return False

    return True