from dataclasses import dataclass
import os

from dotenv import load_dotenv


def _load_dotenv_if_needed(load_env: bool) -> None:
    if load_env:
        load_dotenv(override=False)


def _get_float_env(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float.") from exc


def _get_csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    values = tuple(
        dict.fromkeys(
            value.strip().upper()
            for value in raw_value.split(",")
            if value.strip()
        )
    )
    if not values:
        raise ValueError(f"{name} must include at least one value.")
    return values


@dataclass(frozen=True)
class BoardConfig:
    vb_rw_api_key: str
    redis_url: str

    @classmethod
    def from_env(cls, *, load_env: bool = True) -> "BoardConfig":
        _load_dotenv_if_needed(load_env)

        return cls(
            vb_rw_api_key=os.environ["VB_RW_API_KEY"],
            redis_url=os.environ["REDIS_URL"],
        )


@dataclass(frozen=True)
class SonosConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    database_url: str

    @classmethod
    def from_env(cls, *, load_env: bool = True) -> "SonosConfig":
        _load_dotenv_if_needed(load_env)

        return cls(
            client_id=os.environ["SONOS_CLIENT_ID"],
            client_secret=os.environ["SONOS_CLIENT_SECRET"],
            redirect_uri=os.environ["SONOS_REDIRECT_URI"],
            database_url=os.environ["DATABASE_URL"],
        )


@dataclass(frozen=True)
class FlightBounds:
    lat_min: float
    lon_min: float
    lat_max: float
    lon_max: float

    def __post_init__(self) -> None:
        if self.lat_min > self.lat_max:
            raise ValueError("FLIGHT_LAMIN must be less than or equal to FLIGHT_LAMAX.")
        if self.lon_min > self.lon_max:
            raise ValueError("FLIGHT_LOMIN must be less than or equal to FLIGHT_LOMAX.")

    def to_fr24_bounds(self) -> str:
        return f"{self.lat_max:.6f},{self.lat_min:.6f},{self.lon_min:.6f},{self.lon_max:.6f}"


@dataclass(frozen=True)
class FlightRadarConfig:
    api_token: str
    bounds: FlightBounds
    base_url: str = "https://fr24api.flightradar24.com"
    api_version: str = "v1"

    @classmethod
    def from_env(cls, *, load_env: bool = True) -> "FlightRadarConfig":
        _load_dotenv_if_needed(load_env)

        return cls(
            api_token=os.environ["FR24_API_TOKEN"],
            bounds=FlightBounds(
                lat_min=_get_float_env("FLIGHT_LAMIN", 47.725046),
                lon_min=_get_float_env("FLIGHT_LOMIN", -122.184747),
                lat_max=_get_float_env("FLIGHT_LAMAX", 47.751995),
                lon_max=_get_float_env("FLIGHT_LOMAX", -122.144675),
            ),
            base_url=os.environ.get("FR24_BASE_URL", cls.base_url),
            api_version=os.environ.get("FR24_API_VERSION", cls.api_version),
        )


@dataclass(frozen=True)
class MassiveConfig:
    api_key: str
    base_url: str = "https://api.massive.com"
    tickers: tuple[str, ...] = ("MSFT", "TQQQ", "RIVN")

    @classmethod
    def from_env(cls, *, load_env: bool = True) -> "MassiveConfig":
        _load_dotenv_if_needed(load_env)

        return cls(
            api_key=os.environ["MASSIVE_API_KEY"],
            tickers=_get_csv_env("STOCK_TICKERS", cls.tickers),
            base_url=os.environ.get("MASSIVE_BASE_URL", cls.base_url),
        )
