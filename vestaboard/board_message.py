from dataclasses import dataclass
from typing import Any, Optional, List
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

    def to_dict(self) -> dict[str, Any]:
        """Return the content in its JSON-compatible wire format."""
        data: dict[str, Any] = {"state": self.state.value, "source": self.source}
        if self.text is not None:
            data["text"] = self.text
        else:
            data["layout"] = self.layout
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BoardMessage":
        """Decode queue content, rejecting malformed field types."""
        if not isinstance(data, dict):
            raise ValueError("BoardMessage must be a JSON object.")
        if "state" not in data or "source" not in data:
            raise ValueError("BoardMessage requires state and source.")
        if not isinstance(data["source"], str):
            raise ValueError("BoardMessage source must be a string.")

        text = data.get("text")
        layout = data.get("layout")
        if text is not None and not isinstance(text, str):
            raise ValueError("BoardMessage text must be a string.")
        if layout is not None and (
            not isinstance(layout, list)
            or any(
                not isinstance(row, list)
                or any(type(cell) is not int for cell in row)
                for row in layout
            )
        ):
            raise ValueError("BoardMessage layout must be an array of integer arrays.")

        return cls(
            state=BoardState(data["state"]),
            source=data["source"],
            text=text,
            layout=layout,
        )
