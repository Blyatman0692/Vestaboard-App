from enum import Enum

class BoardState(Enum):
    WEATHER = "weather"
    COUNTDOWN = "countdown"
    SONOS = "sonos"
    UNKNOWN = "unknown"