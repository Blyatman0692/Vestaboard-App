from dataclasses import dataclass
from typing import Optional, List
from vestaboard.board_state import BoardState


@dataclass
class BoardMessage:
    state: BoardState
    layout: List[List[int]]
    source: str
    text: Optional[str] = None