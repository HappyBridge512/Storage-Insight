from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

import wmi  # type: ignore

from storage_insight_backend.models.drive import SmartStatus
from storage_insight_backend.models.smart import (
    SmartAttribute,
    SmartDeviceSnapshot,
    SmartMetrics,
    SmartMonitorSnapshot,
)

logger = logging.getLogger(__name__)

ATTRIBUTE_NAMES = {
    1: "Raw_Read_Error_Rate",
    5: "Reallocated_Sector_Ct",
    9: "Power_On_Hours",
    170: "Available_Reserved_Space",
    171: "Program_Fail_Count",
    172: "Erase_Fail_Count",
    173: "Wear_Leveling_Count",
    177: "Wear_Leveling_Count",
    179: "Used_Rsvd_Blk_Cnt_Tot",
    181: "Program_Fail_Cnt_Total",
    182: "Erase_Fail_Count_Total",
    183: "Runtime_Bad_Block",
    184: "End-to-End_Error",
    187: "Reported_Uncorrect",
    188: "Command_Timeout",
    190: "Airflow_Temperature_Cel",
    194: "Temperature_Celsius",
    196: "Reallocated_Event_Count",
    197: "Current_Pending_Sector",
    198: "Offline_Uncorrectable",
    199: "UDMA_CRC_Error_Count",
    200: "Write_Error_Rate",
    202: "Percent_Lifetime_Remain",
    231: "SSD_Life_Left",
    233: "Media_Wearout_Indicator",
    241: "Total_LBAs_Written",
    242: "Total_LBAs_Read",
}

READ_ERROR_ATTRIBUTE_IDS = {1, 187, 197, 198}
WRITE_ERROR_ATTRIBUTE_IDS = {199, 200}
REALLOCATED_ATTRIBUTE_IDS = {5, 196}
WEAR_ATTRIBUTE_IDS = {170, 173, 177, 202, 231, 233}
TEMPERATURE_ATTRIBUTE_IDS = {190, 194}


class SmartProvider:
    name = "unknown"

    def collect(self) -> tuple[list[SmartDeviceSnapshot], list[str]]:
        raise NotImplementedError


class PySmartProvider(SmartProvider):
    name = "pySMART"

    def collect(self) -> tuple[list[SmartDeviceSnapshot], list[str]]:
        try:
            from pySMART import DeviceList  # type: ignore

            devices = list(DeviceList(catch_errors=True).devices)
        except Exception as exc:  # noqa: BLE001 - optional smartctl boundary.
            message = f"pySMART unavailable: {exc}"
            logger.info(message)
            return [], [message]

        snapshots: list[SmartDeviceSnapshot] = []
        errors: list[str] = []
        for device in devices:
            try:
                snapshots.append(self._snapshot_from_device(device))
            except Exception as exc:  # noqa: BLE001 - one device must not kill polling.
                message = f"pySMART parse failed for {getattr(device, 'name', 'unknown')}: {exc}"
                logger.exception(message)
                errors.append(message)
        return snapshots, errors

    def _snapshot_from_device(self, device: Any) -> SmartDeviceSnapshot:
        attributes = _pySMART_attributes(device)
        metrics = _metrics_from_pySMART(device, attributes)
        health = _health_from_assessment(getattr(device, "assessment", None), attributes, metrics)
        reason = None if health != "unknown" else "SMART assessment was not reported"
        device_id = str(getattr(device, "dev_reference", None) or getattr(device, "name", "unknown"))

        return SmartDeviceSnapshot(
            device_id=device_id,
            model=_clean_text(getattr(device, "model", None)),
            serial=_clean_text(getattr(device, "serial", None)),
            interface=_clean_text(getattr(device, "interface", None)),
            protocol=_clean_text(getattr(device, "dev_interface", None)),
            supported=bool(getattr(device, "smart_capable", True)),
            health=health,
            source=self.name,
            reason=reason,
            metrics=metrics,
            attributes=attributes,
            updated_at=time.time(),
            errors=list(getattr(device, "messages", []) or []),
        )


class WmiSmartProvider(SmartProvider):
    name = "wmi_ms_storage_driver"

    def collect(self) -> tuple[list[SmartDeviceSnapshot], list[str]]:
        com_context = _ComContext()
        try:
            com_context.initialize()
            namespace = wmi.WMI(namespace=r"root\wmi")
            statuses = {
                str(item.InstanceName): item
                for item in namespace.MSStorageDriver_FailurePredictStatus()
                if getattr(item, "InstanceName", None)
            }
            data_items = namespace.MSStorageDriver_FailurePredictData()
            snapshots = self._snapshots_from_wmi(data_items, statuses)
        except Exception as exc:  # noqa: BLE001 - not available on every controller.
            message = f"WMI SMART fallback unavailable: {exc}"
            logger.info(message)
            return [], [message]
        finally:
            com_context.close()

        return snapshots, []

    def _snapshots_from_wmi(
        self,
        data_items: Any,
        statuses: dict[str, Any],
    ) -> list[SmartDeviceSnapshot]:
        snapshots: list[SmartDeviceSnapshot] = []
        for data in data_items:
            instance_name = str(getattr(data, "InstanceName", "unknown"))
            status = statuses.get(instance_name)
            attributes = _wmi_vendor_attributes(getattr(data, "VendorSpecific", None))
            metrics = _metrics_from_attributes(attributes)
            health = "critical" if bool(getattr(status, "PredictFailure", False)) else "ok"
            reason = "WMI PredictFailure is true" if health == "critical" else None

            snapshots.append(
                SmartDeviceSnapshot(
                    device_id=instance_name,
                    model=None,
                    serial=None,
                    interface=None,
                    protocol="ata",
                    supported=True,
                    health=health,
                    source=self.name,
                    reason=reason,
                    metrics=metrics,
                    attributes=attributes,
                    updated_at=time.time(),
                    errors=[],
                )
            )

        return snapshots


class WmiStorageReliabilityProvider(SmartProvider):
    name = "wmi_storage_reliability"

    def collect(self) -> tuple[list[SmartDeviceSnapshot], list[str]]:
        com_context = _ComContext()
        try:
            com_context.initialize()
            storage = wmi.WMI(namespace=r"root\Microsoft\Windows\Storage")
            physical_disks = {
                str(getattr(disk, "DeviceId", "")): disk
                for disk in storage.MSFT_PhysicalDisk()
                if getattr(disk, "DeviceId", None) is not None
            }
            counters = list(storage.MSFT_StorageReliabilityCounter())
            snapshots = self._snapshots_from_storage(counters, physical_disks)
        except Exception as exc:  # noqa: BLE001 - often requires elevation on Windows.
            message = f"MSFT_StorageReliabilityCounter unavailable: {exc}"
            logger.info(message)
            return [], [message]
        finally:
            com_context.close()

        return snapshots, []

    def _snapshots_from_storage(
        self,
        counters: list[Any],
        physical_disks: dict[str, Any],
    ) -> list[SmartDeviceSnapshot]:
        snapshots: list[SmartDeviceSnapshot] = []
        for counter in counters:
            device_id = str(getattr(counter, "DeviceId", "") or "")
            physical = physical_disks.get(device_id)
            metrics = SmartMetrics(
                temperature_celsius=_first_int(getattr(counter, "Temperature", None)),
                power_on_hours=_first_int(getattr(counter, "PowerOnHours", None)),
                wear_level_percent=_first_int(getattr(counter, "Wear", None)),
                read_errors=_sum_known(
                    getattr(counter, "ReadErrorsTotal", None),
                    getattr(counter, "ReadErrorsUncorrected", None),
                ),
                write_errors=_sum_known(
                    getattr(counter, "WriteErrorsTotal", None),
                    getattr(counter, "WriteErrorsUncorrected", None),
                ),
            )
            health = _health_from_msft_physical_disk(physical)

            snapshots.append(
                SmartDeviceSnapshot(
                    device_id=f"MSFT_PhysicalDisk:{device_id or 'unknown'}",
                    model=_clean_text(getattr(physical, "FriendlyName", None)) if physical else None,
                    serial=_clean_text(getattr(physical, "SerialNumber", None)) if physical else None,
                    interface=_clean_text(getattr(physical, "BusType", None)) if physical else None,
                    protocol=None,
                    supported=True,
                    health=health,
                    source=self.name,
                    reason=None if health != "unknown" else "MSFT_PhysicalDisk did not report a known HealthStatus",
                    metrics=metrics,
                    attributes=[],
                    updated_at=time.time(),
                    errors=[],
                )
            )

        return snapshots


class SmartService:
    def __init__(self, polling_interval_seconds: float = 30.0) -> None:
        self._polling_interval_seconds = polling_interval_seconds
        self._providers: list[SmartProvider] = [
            PySmartProvider(),
            WmiStorageReliabilityProvider(),
            WmiSmartProvider(),
        ]
        self._lock = threading.Lock()
        self._cached: SmartMonitorSnapshot | None = None

    def snapshot(self, *, force: bool = False) -> SmartMonitorSnapshot:
        with self._lock:
            now = time.time()
            if (
                not force
                and self._cached is not None
                and now - self._cached.updated_at < self._polling_interval_seconds
            ):
                return self._cached

            devices: list[SmartDeviceSnapshot] = []
            errors: list[str] = []
            for provider in self._providers:
                provider_devices, provider_errors = provider.collect()
                errors.extend(provider_errors)
                devices.extend(self._merge_devices(devices, provider_devices))

                if devices:
                    break

            self._cached = SmartMonitorSnapshot(
                devices=devices,
                errors=errors,
                polling_interval_seconds=self._polling_interval_seconds,
                updated_at=now,
            )
            return self._cached

    def snapshot_dict(self, *, force: bool = False) -> dict[str, Any]:
        return self.snapshot(force=force).to_dict()

    def read_for_drive(self, physical_device: str | None, model: str | None, serial: str | None) -> SmartStatus:
        snapshot = self.snapshot()
        match = self._match_device(snapshot.devices, physical_device, model, serial)
        if match is None:
            reason = "; ".join(snapshot.errors) if snapshot.errors else "No SMART device matched this drive"
            return SmartStatus.from_metrics(
                health="unknown",
                supported=False,
                source=None,
                reason=reason,
                metrics=SmartMetrics(),
                attributes=[],
            )

        return SmartStatus.from_metrics(
            health=match.health,
            supported=match.supported,
            source=match.source,
            reason=match.reason,
            metrics=match.metrics,
            attributes=match.attributes,
        )

    def _merge_devices(
        self,
        existing: list[SmartDeviceSnapshot],
        incoming: list[SmartDeviceSnapshot],
    ) -> list[SmartDeviceSnapshot]:
        existing_keys = {_device_key(device) for device in existing}
        return [device for device in incoming if _device_key(device) not in existing_keys]

    def _match_device(
        self,
        devices: list[SmartDeviceSnapshot],
        physical_device: str | None,
        model: str | None,
        serial: str | None,
    ) -> SmartDeviceSnapshot | None:
        normalized_serial = _normalize_identifier(serial)
        normalized_model = (_clean_text(model) or "").lower()
        normalized_physical = (_clean_text(physical_device) or "").lower()

        for device in devices:
            if normalized_serial and normalized_serial == _normalize_identifier(device.serial):
                return device

        for device in devices:
            device_id = (device.device_id or "").lower()
            if normalized_physical and normalized_physical in device_id:
                return device

        for device in devices:
            device_model = (device.model or "").lower()
            if normalized_model and (normalized_model in device_model or device_model in normalized_model):
                return device

        return None


def _pySMART_attributes(device: Any) -> list[SmartAttribute]:
    attributes: list[SmartAttribute] = []
    for attr in getattr(device, "attributes", []) or []:
        if attr is None:
            continue
        attributes.append(
            SmartAttribute(
                id=_safe_int(getattr(attr, "num", None)),
                name=str(getattr(attr, "name", None) or "Unknown"),
                value=_safe_int(getattr(attr, "value", None), getattr(attr, "value", None)),
                worst=_safe_int(getattr(attr, "worst", None)),
                threshold=_safe_int(getattr(attr, "thresh", None)),
                raw=_clean_text(getattr(attr, "raw", None)),
                raw_int=_safe_int(getattr(attr, "raw_int", None)),
                when_failed=_clean_text(getattr(attr, "when_failed", None)),
                source="pySMART",
            )
        )
    return attributes


def _metrics_from_pySMART(device: Any, attributes: list[SmartAttribute]) -> SmartMetrics:
    if_attributes = getattr(device, "if_attributes", None)
    diagnostics = getattr(device, "diagnostics", None)
    attribute_metrics = _metrics_from_attributes(attributes)

    return SmartMetrics(
        temperature_celsius=_first_int(
            getattr(device, "temperature", None),
            getattr(if_attributes, "temperature", None) if if_attributes else None,
            attribute_metrics.temperature_celsius,
        ),
        power_on_hours=_first_int(
            getattr(if_attributes, "powerOnHours", None) if if_attributes else None,
            getattr(diagnostics, "Power_On_Hours", None) if diagnostics else None,
            attribute_metrics.power_on_hours,
        ),
        wear_level_percent=_first_int(
            _wear_from_nvme(if_attributes),
            attribute_metrics.wear_level_percent,
        ),
        life_remaining_percent=_first_int(
            getattr(diagnostics, "Life_Left", None) if diagnostics else None,
            attribute_metrics.life_remaining_percent,
        ),
        available_spare_percent=_first_int(
            getattr(if_attributes, "availableSpare", None) if if_attributes else None,
            attribute_metrics.available_spare_percent,
        ),
        reallocated_sectors=_first_int(
            getattr(diagnostics, "Reallocated_Sector_Ct", None) if diagnostics else None,
            attribute_metrics.reallocated_sectors,
        ),
        read_errors=_first_int(
            getattr(if_attributes, "integrityErrors", None) if if_attributes else None,
            getattr(diagnostics, "Uncorrected_Reads", None) if diagnostics else None,
            attribute_metrics.read_errors,
        ),
        write_errors=_first_int(
            getattr(diagnostics, "Uncorrected_Writes", None) if diagnostics else None,
            attribute_metrics.write_errors,
        ),
        media_errors=_first_int(getattr(if_attributes, "errorEntries", None) if if_attributes else None),
        unsafe_shutdowns=_first_int(getattr(if_attributes, "unsafeShutdowns", None) if if_attributes else None),
        bytes_read=_first_int(getattr(if_attributes, "bytesRead", None) if if_attributes else None),
        bytes_written=_first_int(getattr(if_attributes, "bytesWritten", None) if if_attributes else None),
    )


def _metrics_from_attributes(attributes: list[SmartAttribute]) -> SmartMetrics:
    by_id = {attribute.id: attribute for attribute in attributes if attribute.id is not None}
    return SmartMetrics(
        temperature_celsius=_first_raw(by_id, TEMPERATURE_ATTRIBUTE_IDS),
        power_on_hours=_first_raw(by_id, {9}),
        wear_level_percent=_wear_from_attributes(by_id),
        life_remaining_percent=_life_remaining_from_attributes(by_id),
        available_spare_percent=_first_raw(by_id, {170}),
        reallocated_sectors=_sum_raw(by_id, REALLOCATED_ATTRIBUTE_IDS),
        read_errors=_sum_raw(by_id, READ_ERROR_ATTRIBUTE_IDS),
        write_errors=_sum_raw(by_id, WRITE_ERROR_ATTRIBUTE_IDS),
    )


def _wmi_vendor_attributes(vendor_specific: Any) -> list[SmartAttribute]:
    if vendor_specific is None:
        return []

    raw_bytes = [int(value) for value in vendor_specific]
    attributes: list[SmartAttribute] = []
    for offset in range(2, min(len(raw_bytes), 362), 12):
        attribute_id = raw_bytes[offset]
        if attribute_id == 0:
            continue

        raw_value = 0
        for index, byte in enumerate(raw_bytes[offset + 5 : offset + 11]):
            raw_value |= byte << (index * 8)

        attributes.append(
            SmartAttribute(
                id=attribute_id,
                name=ATTRIBUTE_NAMES.get(attribute_id, f"SMART_{attribute_id}"),
                value=raw_bytes[offset + 3],
                worst=raw_bytes[offset + 4],
                threshold=None,
                raw=str(raw_value),
                raw_int=raw_value,
                when_failed=None,
                source="wmi",
            )
        )
    return attributes


def _health_from_assessment(
    assessment: Any,
    attributes: list[SmartAttribute],
    metrics: SmartMetrics,
) -> str:
    value = str(assessment or "").upper()
    if value == "PASS":
        return "ok"
    if value in {"FAIL", "FAILED"}:
        return "critical"
    if value == "WARN":
        return "warning"
    if any((attribute.when_failed or "-") not in {"", "-"} for attribute in attributes):
        return "warning"
    if metrics.reallocated_sectors is not None and metrics.reallocated_sectors > 0:
        return "warning"
    return "unknown"


def _health_from_msft_physical_disk(physical: Any | None) -> str:
    if physical is None:
        return "unknown"
    health = _safe_int(getattr(physical, "HealthStatus", None))
    if health == 0:
        return "ok"
    if health == 1:
        return "warning"
    if health == 2:
        return "critical"
    return "unknown"


def _wear_from_nvme(if_attributes: Any | None) -> int | None:
    if if_attributes is None:
        return None
    percentage_used = _safe_int(getattr(if_attributes, "percentageUsed", None))
    if percentage_used is None:
        return None
    return max(0, percentage_used)


def _wear_from_attributes(by_id: dict[int | None, SmartAttribute]) -> int | None:
    for attribute_id in WEAR_ATTRIBUTE_IDS:
        attribute = by_id.get(attribute_id)
        if attribute is None:
            continue
        raw = attribute.raw_int
        if raw is not None and 0 <= raw <= 100:
            return raw
        value = _safe_int(attribute.value)
        if value is not None and 0 <= value <= 100:
            return value
    return None


def _life_remaining_from_attributes(by_id: dict[int | None, SmartAttribute]) -> int | None:
    for attribute_id in {202, 231, 233}:
        attribute = by_id.get(attribute_id)
        if attribute is None:
            continue
        raw = attribute.raw_int
        if raw is not None and 0 <= raw <= 100:
            return raw
        value = _safe_int(attribute.value)
        if value is not None and 0 <= value <= 100:
            return value
    return None


def _first_raw(by_id: dict[int | None, SmartAttribute], ids: set[int]) -> int | None:
    for attribute_id in ids:
        attribute = by_id.get(attribute_id)
        if attribute and attribute.raw_int is not None:
            return attribute.raw_int
    return None


def _sum_raw(by_id: dict[int | None, SmartAttribute], ids: set[int]) -> int | None:
    values = [by_id[attribute_id].raw_int for attribute_id in ids if attribute_id in by_id]
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _sum_known(*values: Any) -> int | None:
    known = [_safe_int(value) for value in values]
    filtered = [value for value in known if value is not None]
    return sum(filtered) if filtered else None


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _safe_int(value)
        if parsed is not None:
            return parsed
    return None


def _safe_int(value: Any, default: Any = None) -> Any:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _normalize_identifier(value: Any) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", cleaned).upper()


def _device_key(device: SmartDeviceSnapshot) -> str:
    return _normalize_identifier(device.serial) or device.device_id.lower()


class _ComContext:
    def __init__(self) -> None:
        self._pythoncom: Any | None = None
        self._initialized = False

    def initialize(self) -> None:
        try:
            import pythoncom  # type: ignore

            pythoncom.CoInitialize()
            self._pythoncom = pythoncom
            self._initialized = True
        except ImportError:
            return

    def close(self) -> None:
        return
