from dataclasses import dataclass
from typing import Optional, List
from vestaboard.board_state import BoardState

@dataclass
class BoardMessage:
    state: BoardState
    source: str
    layout: Optional[List[List[int]]] = None
    text: Optional[str] = None

    def __post_init__(self) -> None:
        has_text = self.text is not None
        has_layout = self.layout is not None

        if has_text == has_layout:
            raise ValueError("BoardMessage must have exactly one of text or layout.")