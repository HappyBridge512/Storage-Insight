from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DiskPartitionInfo:
    id: str
    disk_index: int
    partition_index: int | None
    name: str
    device_id: str
    mount_point: str | None
    volume_label: str | None
    filesystem: str | None
    drive_type: str
    total_bytes: int | None
    free_bytes: int | None
    used_bytes: int | None
    percent_used: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PhysicalDiskInfo:
    id: str
    index: int
    model: str | None
    serial_number: str | None
    interface_type: str | None
    storage_bus_type: str | None
    media_type: str
    device_type: str
    device_type_source: str
    total_bytes: int | None
    partitions: list[DiskPartitionInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["partitions"] = [partition.to_dict() for partition in self.partitions]
        return data


@dataclass(frozen=True)
class DiskDetectionResult:
    platform: str
    disks: list[PhysicalDiskInfo]
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "disks": [disk.to_dict() for disk in self.disks],
            "errors": list(self.errors),
        }
