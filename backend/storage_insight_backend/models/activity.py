from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DiskUsageSnapshot:
    mount_point: str
    device: str
    filesystem: str
    total_bytes: int
    free_bytes: int
    used_bytes: int
    percent_used: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiskActivitySample:
    disk_name: str
    read_bytes_per_second: float | None
    write_bytes_per_second: float | None
    read_iops: float | None
    write_iops: float | None
    total_iops: float | None
    active_time_percent: float | None
    active_time_source: str | None
    read_bytes_total: int
    write_bytes_total: int
    read_count_total: int
    write_count_total: int
    read_time_ms_total: int | None
    write_time_ms_total: int | None
    busy_time_ms_total: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiskActivitySnapshot:
    timestamp: float
    interval_seconds: float
    disks: list[DiskActivitySample]
    usage: list[DiskUsageSnapshot] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "interval_seconds": self.interval_seconds,
            "disks": [disk.to_dict() for disk in self.disks],
            "usage": [usage.to_dict() for usage in self.usage],
            "errors": list(self.errors),
        }
