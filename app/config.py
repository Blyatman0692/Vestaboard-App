from dataclasses import dataclass
import logging
import os
from typing import Optional

from dotenv import load_dotenv


logger = logging.getLogger(__name__)


def _load_dotenv_if_needed(load_env: bool) -> bool:
    if load_env:
        return load_dotenv(override=False)
    return False


def _env_state(name: str, *, secret: bool = False) -> str:
    if name not in os.environ:
        return "missing"

    value = os.environ.get(name, "")
    if value == "":
        return "empty"

    if secret:
        return "set"

    return f"set(len={len(value)})"


def _required_float_env(name: str) -> float:
    if name not in os.environ:
        logger.error("Required environment variable %s is missing", name)
        raise KeyError(name)

    raw_value = os.environ[name]
    try:
        return float(raw_value)
    except ValueError:
        logger.exception(
            "Required environment variable %s must be a float; raw_length=%d",
            name,
            len(raw_value),
        )
        raise


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
class FlightConfig:
    lamin: float
    lomin: float
    lamax: float
    lomax: float
    opensky_client_id: Optional[str] = None
    opensky_client_secret: Optional[str] = None

    @classmethod
    def from_env(cls, *, load_env: bool = True) -> "FlightConfig":
        dotenv_loaded = _load_dotenv_if_needed(load_env)

        logger.info(
            "Loading flight config: load_env=%s dotenv_loaded=%s env_state=%s",
            load_env,
            dotenv_loaded,
            {
                "FLIGHT_LAMIN": _env_state("FLIGHT_LAMIN"),
                "FLIGHT_LOMIN": _env_state("FLIGHT_LOMIN"),
                "FLIGHT_LAMAX": _env_state("FLIGHT_LAMAX"),
                "FLIGHT_LOMAX": _env_state("FLIGHT_LOMAX"),
                "OPENSKY_CLIENT_ID": _env_state("OPENSKY_CLIENT_ID", secret=True),
                "OPENSKY_CLIENT_SECRET": _env_state("OPENSKY_CLIENT_SECRET", secret=True),
            },
        )

        opensky_client_id = os.getenv("OPENSKY_CLIENT_ID")
        opensky_client_secret = os.getenv("OPENSKY_CLIENT_SECRET")
        if bool(opensky_client_id) != bool(opensky_client_secret):
            logger.warning(
                "Only one OpenSky credential variable is populated; "
                "OpenSky requests will be anonymous."
            )

        config = cls(
            lamin=_required_float_env("FLIGHT_LAMIN"),
            lomin=_required_float_env("FLIGHT_LOMIN"),
            lamax=_required_float_env("FLIGHT_LAMAX"),
            lomax=_required_float_env("FLIGHT_LOMAX"),
            opensky_client_id=opensky_client_id,
            opensky_client_secret=opensky_client_secret,
        )

        logger.info(
            "Flight config loaded: bounds=%s opensky_auth=%s",
            {
                "lamin": config.lamin,
                "lomin": config.lomin,
                "lamax": config.lamax,
                "lomax": config.lomax,
            },
            "enabled" if config.opensky_client_id and config.opensky_client_secret else "disabled",
        )
        return config


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
