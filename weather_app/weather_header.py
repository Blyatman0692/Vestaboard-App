from datetime import datetime
from zoneinfo import ZoneInfo
import utils


class WeatherHeader():
    def __init__(self):
        self.now = datetime.now(ZoneInfo("America/Los_Angeles"))
        self.month = self.now.strftime("%b")
        self.day = self.now.day.__str__()
        self.hour = self.now.hour
        self.hour_in_12 = self.hour % 12 or 12
        self.ampm = "AM" if self.hour < 12 else "PM"

    def compose_header_components(self):
        date_string = self.month + " " + self.day
        date_component = utils.compose_vbml_component(
            date_string,
            height=1,
            width=6,
            justify="left",
            align="top"
        )

        filler_component = utils.compose_vbml_component(
            "{63}{64}{65}{66}{67}{68}",
            height=1,
            width=10,
            justify="center",
            align="top"
        )

        time_string = str(self.hour_in_12) + self.ampm
        time_component = utils.compose_vbml_component(
            time_string,
            height=1,
            width=6,
            justify="right",
            align="top"
        )

        return [date_component, filler_component, time_component]





