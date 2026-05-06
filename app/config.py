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


def _optional_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default

    try:
        return int(raw_value)
    except ValueError:
        logger.exception(
            "Optional environment variable %s must be an integer; raw_length=%d",
            name,
            len(raw_value),
        )
        raise


def _optional_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False

    logger.warning(
        "Optional environment variable %s has unrecognized boolean value; "
        "using default=%s raw_length=%d",
        name,
        default,
        len(raw_value),
    )
    return default


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
    opensky_token_timeout_s: int = 10
    opensky_anonymous_fallback_on_auth_network_error: bool = True

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
                "OPENSKY_TOKEN_TIMEOUT_S": _env_state("OPENSKY_TOKEN_TIMEOUT_S"),
                "OPENSKY_ANONYMOUS_FALLBACK_ON_AUTH_NETWORK_ERROR": _env_state(
                    "OPENSKY_ANONYMOUS_FALLBACK_ON_AUTH_NETWORK_ERROR"
                ),
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
            opensky_token_timeout_s=_optional_int_env("OPENSKY_TOKEN_TIMEOUT_S", 10),
            opensky_anonymous_fallback_on_auth_network_error=_optional_bool_env(
                "OPENSKY_ANONYMOUS_FALLBACK_ON_AUTH_NETWORK_ERROR",
                True,
            ),
        )

        logger.info(
            "Flight config loaded: bounds=%s opensky_auth=%s token_timeout_s=%s "
            "anonymous_fallback_on_auth_network_error=%s",
            {
                "lamin": config.lamin,
                "lomin": config.lomin,
                "lamax": config.lamax,
                "lomax": config.lomax,
            },
            "enabled" if config.opensky_client_id and config.opensky_client_secret else "disabled",
            config.opensky_token_timeout_s,
            config.opensky_anonymous_fallback_on_auth_network_error,
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
