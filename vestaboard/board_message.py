from dataclasses import dataclass
from typing import Optional, List
from vestaboard.board_state import BoardState


@dataclass
class BoardMessage:
    state: BoardState
    source: str
    layout: Optional[List[List[int]]] = None
    text: Optional[str] = None