from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class GeoBounds:
    lamin: float
    lomin: float
    lamax: float
    lomax: float

    def as_params(self) -> dict[str, float]:
        return {
            "lamin": self.lamin,
            "lomin": self.lomin,
            "lamax": self.lamax,
            "lomax": self.lomax,
        }


@dataclass(frozen=True)
class FlightInfo:
    icao24: str
    callsign: Optional[str]
    origin_country: Optional[str]
    longitude: Optional[float]
    latitude: Optional[float]
    baro_altitude_m: Optional[float]
    geo_altitude_m: Optional[float]
    on_ground: bool
    velocity_mps: Optional[float]
    true_track_deg: Optional[float]
    vertical_rate_mps: Optional[float]
    squawk: Optional[str]
    last_contact: Optional[datetime]
    category: Optional[int]

    @property
    def altitude_ft(self) -> Optional[int]:
        altitude_m = self.geo_altitude_m if self.geo_altitude_m is not None else self.baro_altitude_m
        if altitude_m is None:
            return None
        return round(altitude_m * 3.28084)

    @property
    def speed_kt(self) -> Optional[int]:
        if self.velocity_mps is None:
            return None
        return round(self.velocity_mps * 1.94384)

    @property
    def heading_cardinal(self) -> Optional[str]:
        if self.true_track_deg is None:
            return None

        directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        index = round(self.true_track_deg / 45) % len(directions)
        return directions[index]


def unix_to_utc(value: Optional[int]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)
