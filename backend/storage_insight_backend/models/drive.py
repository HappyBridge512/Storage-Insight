from __future__ import annotations

from dataclasses import asdict, dataclass

from storage_insight_backend.models.smart import SmartAttribute, SmartMetrics


@dataclass(frozen=True)
class SmartStatus:
    health: str
    temperature_celsius: int | None
    supported: bool
    source: str | None
    reason: str | None = None
    power_on_hours: int | None = None
    wear_level_percent: int | None = None
    life_remaining_percent: int | None = None
    available_spare_percent: int | None = None
    reallocated_sectors: int | None = None
    read_errors: int | None = None
    write_errors: int | None = None
    media_errors: int | None = None
    unsafe_shutdowns: int | None = None
    attributes: list[SmartAttribute] | None = None

    @classmethod
    def from_metrics(
        cls,
        *,
        health: str,
        supported: bool,
        source: str | None,
        reason: str | None,
        metrics: SmartMetrics,
        attributes: list[SmartAttribute] | None = None,
    ) -> "SmartStatus":
        return cls(
            health=health,
            temperature_celsius=metrics.temperature_celsius,
            supported=supported,
            source=source,
            reason=reason,
            power_on_hours=metrics.power_on_hours,
            wear_level_percent=metrics.wear_level_percent,
            life_remaining_percent=metrics.life_remaining_percent,
            available_spare_percent=metrics.available_spare_percent,
            reallocated_sectors=metrics.reallocated_sectors,
            read_errors=metrics.read_errors,
            write_errors=metrics.write_errors,
            media_errors=metrics.media_errors,
            unsafe_shutdowns=metrics.unsafe_shutdowns,
            attributes=attributes,
        )

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["attributes"] = [attribute.to_dict() for attribute in self.attributes or []]
        return data


@dataclass(frozen=True)
class DriveInfo:
    id: str
    mount_point: str
    device: str
    file_system: str
    drive_type: str
    total_bytes: int
    free_bytes: int
    used_bytes: int
    percent_used: float
    volume_label: str | None
    physical_device: str | None
    model: str | None
    serial: str | None
    interface_type: str | None
    storage_bus_type: str | None
    storage_type: str
    smart: SmartStatus

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["smart"] = self.smart.to_dict()
        return data
