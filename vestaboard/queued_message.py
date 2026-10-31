"""Versioned wire format for board messages awaiting display.

Version 1 contains message_id, created_at (an ISO 8601 UTC timestamp),
schema_version, and message (state, source, and either text or layout).
Redis and display scheduling are deliberately outside this module.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from vestaboard.board_message import BoardMessage


@dataclass(frozen=True)
class QueuedMessage:
    message: BoardMessage
    message_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError(f"Unsupported queue schema version: {self.schema_version!r}")
        if not isinstance(self.message_id, str) or not self.message_id.strip():
            raise ValueError("QueuedMessage message_id must be a nonempty string.")
        if not isinstance(self.created_at, datetime) or self.created_at.utcoffset() is None:
            raise ValueError("QueuedMessage created_at must be a timezone-aware datetime.")
        if not isinstance(self.message, BoardMessage):
            raise ValueError("QueuedMessage message must be a BoardMessage.")

    def to_json(self) -> str:
        """Serialize without changing this message's identity or creation time."""
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "message_id": self.message_id,
                "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
                "message": self.message.to_dict(),
            },
            ensure_ascii=False,
            allow_nan=False,
        )

    @classmethod
    def from_json(cls, value: str | bytes) -> "QueuedMessage":
        """Restore a queued message; invalid payloads raise ValueError.

        Metadata is required rather than regenerated so decoding preserves the
        original message ID and timestamp. Bytes support Redis clients with
        response decoding disabled.
        """
        data = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError("QueuedMessage must be a JSON object.")
        required = {"schema_version", "message_id", "created_at", "message"}
        missing = required - data.keys()
        if missing:
            raise ValueError(f"QueuedMessage missing required fields: {', '.join(sorted(missing))}")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError(f"Unsupported queue schema version: {data['schema_version']!r}")
        if not isinstance(data["created_at"], str):
            raise ValueError("QueuedMessage created_at must be an ISO 8601 timestamp string.")

        return cls(
            message=BoardMessage.from_dict(data["message"]),
            message_id=data["message_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            schema_version=data["schema_version"],
        )
