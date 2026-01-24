import logging
import sys


from vestaboard import VestaboardMessenger
from .countdown import CountDown
from .targets import TARGET_DATES
import utils


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
)

logger = logging.getLogger()

def run():
    vb = VestaboardMessenger()
    ct = CountDown(TARGET_DATES)
    results = ct.calculate_date_delta()

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
    print(vbml_payload)
    vbml_layout = vb.vbml_compose_layout(vbml_payload)
    vb.send_layout(vbml_layout)

if __name__ == "__main__":
    run()
