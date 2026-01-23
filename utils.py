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