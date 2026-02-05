import datetime
from dataclasses import dataclass


@dataclass
class SonosToken:
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    scope: str | None = None
    updated_at: datetime.datetime | None = None

