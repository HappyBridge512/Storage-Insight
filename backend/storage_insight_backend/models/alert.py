from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


AlertSeverity = str


@dataclass(frozen=True)
class AlertCandidate:
    code: str
    severity: AlertSeverity
    title: str
    message: str
    source: str
    drive_id: str | None = None
    disk_name: str | None = None
    value: int | float | str | None = None
    threshold: int | float | str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def fingerprint_parts(self) -> list[str]:
        return [
            self.code,
            self.source,
            self.drive_id or "",
            self.disk_name or "",
            str(self.metadata.get("metric") or ""),
        ]


@dataclass(frozen=True)
class AlertRecord:
    id: str
    fingerprint: str
    code: str
    severity: AlertSeverity
    title: str
    message: str
    source: str
    drive_id: str | None
    disk_name: str | None
    value: int | float | str | None
    threshold: int | float | str | None
    metadata: dict[str, Any]
    created_at: float
    last_seen_at: float
    count: int
    active: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
