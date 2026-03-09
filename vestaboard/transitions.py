from enum import Enum

class Transition(Enum):
    CLASSIC = "classic"
    WAVE = "wave"
    DRIFT = "drift"
    CURTAIN = "curtain"


class TransitionSpeed(Enum):
    GENTLE = "gentle"
    FAST = "fast"