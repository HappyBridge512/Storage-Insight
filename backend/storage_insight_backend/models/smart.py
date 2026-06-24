from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SmartAttribute:
    id: int | None
    name: str
    value: int | str | None = None
    worst: int | None = None
    threshold: int | None = None
    raw: str | None = None
    raw_int: int | None = None
    when_failed: str | None = None
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SmartMetrics:
    temperature_celsius: int | None = None
    power_on_hours: int | None = None
    wear_level_percent: int | None = None
    life_remaining_percent: int | None = None
    available_spare_percent: int | None = None
    reallocated_sectors: int | None = None
    read_errors: int | None = None
    write_errors: int | None = None
    media_errors: int | None = None
    unsafe_shutdowns: int | None = None
    bytes_read: int | None = None
    bytes_written: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SmartDeviceSnapshot:
    device_id: str
    model: str | None
    serial: str | None
    interface: str | None
    protocol: str | None
    supported: bool
    health: str
    source: str
    reason: str | None
    metrics: SmartMetrics
    attributes: list[SmartAttribute] = field(default_factory=list)
    updated_at: float | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metrics"] = self.metrics.to_dict()
        data["attributes"] = [attribute.to_dict() for attribute in self.attributes]
        return data


@dataclass(frozen=True)
class SmartMonitorSnapshot:
    devices: list[SmartDeviceSnapshot]
    errors: list[str]
    polling_interval_seconds: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "devices": [device.to_dict() for device in self.devices],
            "errors": list(self.errors),
            "polling_interval_seconds": self.polling_interval_seconds,
            "updated_at": self.updated_at,
        }
