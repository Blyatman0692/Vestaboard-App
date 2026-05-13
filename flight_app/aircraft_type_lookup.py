import json
from functools import lru_cache
from pathlib import Path


# Generated from public aircraft type-code snapshots:
# - OpenFlights planes.dat for common airline-friendly names.
# - A public ICAO Doc 8643 designator snapshot for broader fallback coverage.
AIRCRAFT_TYPES_PATH = Path(__file__).with_name("aircraft_types.json")


@lru_cache(maxsize=1)
def _aircraft_type_names() -> dict[str, str]:
    with AIRCRAFT_TYPES_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def aircraft_type_name(type_code: str | None) -> str | None:
    if not type_code:
        return None

    return _aircraft_type_names().get(type_code.upper())
