from typing import List, Dict, Any


def normalize_weather_results(results):
    """
    Accepts Dict[str, WeatherNow] or List[WeatherNow]
    Returns List[WeatherNow] in display order
    """
    if isinstance(results, dict):
        return list(results.values())
    return results

def format_weather_for_vestaboard(weather_list) -> str:
    """
    Formats multiple WeatherNow objects into Vestaboard text.
    One city per line.
    """
    lines = []

    for w in weather_list:
        # shorten common conditions
        condition = w.condition.replace("LIGHT ", "").replace("HEAVY ", "")
        line = f"{w.city[:8]:<8} {w.temperature}{w.unit} {condition[:8]}"
        lines.append(line)

    # Vestaboard supports max ~6 lines
    return "\n".join(lines[:6])




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