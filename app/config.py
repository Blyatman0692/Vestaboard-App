from dataclasses import dataclass
import os
from typing import Optional

from dotenv import load_dotenv


def _load_dotenv_if_needed(load_env: bool) -> None:
    if load_env:
        load_dotenv(override=False)


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
        _load_dotenv_if_needed(load_env)

        return cls(
            lamin=float(os.environ["FLIGHT_LAMIN"]),
            lomin=float(os.environ["FLIGHT_LOMIN"]),
            lamax=float(os.environ["FLIGHT_LAMAX"]),
            lomax=float(os.environ["FLIGHT_LOMAX"]),
            opensky_client_id=os.getenv("OPENSKY_CLIENT_ID"),
            opensky_client_secret=os.getenv("OPENSKY_CLIENT_SECRET"),
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
