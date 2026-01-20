from datetime import datetime
from . import utils

class WeatherHeader():
    def __init__(self):
        self.now = datetime.now()
        self.month = self.now.month
        self.day = self.now.day
        self.hour = self.now.hour
        self.minute = self.now.minute

    def compose_header_components(self):
        date_string = self.month.__str__() + "-" + self.day.__str__()
        date_component = utils.compose_vbml_component(
            date_string,
            height=1,
            width=5,
            justify="left",
            align="top"
        )

        filler_component = utils.compose_vbml_component(
            "{63}{64}{65}{66}{67}{68}",
            height=1,
            width=12,
            justify="center",
            align="top"
        )

        time_string = self.hour.__str__() + ":" + self.minute.__str__()
        time_component = utils.compose_vbml_component(
            time_string,
            height=1,
            width=5,
            justify="right",
            align="top"
        )

        return [date_component, filler_component, time_component]





