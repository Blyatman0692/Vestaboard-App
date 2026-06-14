from enum import Enum

class BoardState(Enum):
    WEATHER = "weather"
    COUNTDOWN = "countdown"
    FLIGHT = "flight"
    SONOS = "sonos"
    STOCK = "stock"
    UNKNOWN = "unknown"
