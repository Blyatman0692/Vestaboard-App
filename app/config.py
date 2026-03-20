from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    vb_rw_api_key: str
    redis_url: str
    sonos_client_id: str
    sonos_client_secret: str
    sonos_redirect_uri: str
    database_url: str

    @classmethod
    def from_env(cls, *, load_env: bool = True) -> "AppConfig":
        if load_env:
            load_dotenv(override=False)

        return cls(
            vb_rw_api_key=os.environ["VB_RW_API_KEY"],
            redis_url=os.environ["REDIS_URL"],
            sonos_client_id=os.environ["SONOS_CLIENT_ID"],
            sonos_client_secret=os.environ["SONOS_CLIENT_SECRET"],
            sonos_redirect_uri=os.environ["SONOS_REDIRECT_URI"],
            database_url=os.environ["DATABASE_URL"],
        )
