from __future__ import annotations

import json
import logging
import platform
import re
import time
import gc
import threading
from pathlib import Path
from typing import Any

import psutil
import wmi  # type: ignore

from storage_insight_backend.models.disk import (
    DiskDetectionResult,
    DiskPartitionInfo,
    PhysicalDiskInfo,
)

logger = logging.getLogger(__name__)
_COM_STATE = threading.local()

DRIVE_TYPE_MAP = {
    0: "unknown",
    1: "no-root-directory",
    2: "removable",
    3: "fixed",
    4: "network",
    5: "optical",
    6: "ramdisk",
}

MSFT_MEDIA_TYPE_MAP = {
    0: "unknown",
    3: "hdd",
    4: "ssd",
    5: "scm",
}

MSFT_BUS_TYPE_MAP = {
    0: "unknown",
    1: "scsi",
    2: "atapi",
    3: "ata",
    4: "ieee1394",
    5: "ssa",
    6: "fibre-channel",
    7: "usb",
    8: "raid",
    9: "iscsi",
    10: "sas",
    11: "sata",
    12: "sd",
    13: "mmc",
    14: "virtual",
    15: "file-backed-virtual",
    16: "storage-spaces",
    17: "nvme",
    18: "scm",
    19: "ufs",
}


class WindowsDiskDetectionError(RuntimeError):
    pass


class WindowsDiskDetector:
    def __init__(self, logger_: logging.Logger | None = None) -> None:
        self._logger = logger_ or logger

    def detect(self) -> DiskDetectionResult:
        if platform.system() != "Windows":
            raise WindowsDiskDetectionError("WindowsDiskDetector supports Windows only")

        started = time.perf_counter()
        com_context = _ComContext()

        try:
            com_context.initialize()
            result = self._detect_inner()
        except Exception as exc:  # noqa: BLE001 - detector boundary returns structured errors.
            self._logger.exception("Windows disk detection failed")
            return DiskDetectionResult(platform="Windows", disks=[], errors=[str(exc)])
        finally:
            com_context.close()

        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        self._logger.info("Detected %s physical Windows disks in %sms", len(result.disks), elapsed_ms)
        return result

    def _detect_inner(self) -> DiskDetectionResult:
        errors: list[str] = []
        cimv2 = wmi.WMI(namespace=r"root\cimv2")
        logical_disks = self._logical_disks_by_id(cimv2)
        storage_disks = self._storage_disks(errors)
        disks = self._physical_disks(cimv2, logical_disks, storage_disks, errors)
        return DiskDetectionResult(platform="Windows", disks=disks, errors=errors)

    def detect_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.detect().to_dict(), ensure_ascii=False, indent=indent)

    def _logical_disks_by_id(self, cimv2: Any) -> dict[str, Any]:
        return {
            str(logical.DeviceID).upper(): logical
            for logical in cimv2.Win32_LogicalDisk()
            if getattr(logical, "DeviceID", None)
        }

    def _storage_disks(self, errors: list[str]) -> list[Any]:
        try:
            storage = wmi.WMI(namespace=r"root\Microsoft\Windows\Storage")
            return list(storage.MSFT_PhysicalDisk())
        except Exception as exc:  # noqa: BLE001 - class can be blocked on older systems.
            message = f"MSFT_PhysicalDisk unavailable: {exc}"
            errors.append(message)
            self._logger.info(message)
            return []

    def _physical_disks(
        self,
        cimv2: Any,
        logical_disks: dict[str, Any],
        storage_disks: list[Any],
        errors: list[str],
    ) -> list[PhysicalDiskInfo]:
        disks: list[PhysicalDiskInfo] = []

        for disk in cimv2.Win32_DiskDrive():
            disk_index = _safe_int(getattr(disk, "Index", None), default=-1)
            disk_id = str(getattr(disk, "DeviceID", None) or f"PHYSICALDRIVE{disk_index}")
            storage_disk = self._match_storage_disk(disk, storage_disks)

            try:
                partitions = self._partitions_for_disk(disk, logical_disks)
            except Exception as exc:  # noqa: BLE001 - keep one bad disk from killing detection.
                message = f"Partition detection failed for {disk_id}: {exc}"
                errors.append(message)
                self._logger.warning(message)
                partitions = []

            media_type = self._media_type(storage_disk)
            bus_type = self._bus_type(storage_disk)
            device_type, device_type_source = self._device_type(disk, media_type, bus_type)

            disks.append(
                PhysicalDiskInfo(
                    id=disk_id,
                    index=disk_index,
                    model=_clean_text(getattr(disk, "Model", None)),
                    serial_number=_clean_text(getattr(disk, "SerialNumber", None)),
                    interface_type=_clean_text(getattr(disk, "InterfaceType", None)),
                    storage_bus_type=bus_type,
                    media_type=media_type,
                    device_type=device_type,
                    device_type_source=device_type_source,
                    total_bytes=_safe_int(getattr(disk, "Size", None)),
                    partitions=partitions,
                )
            )

        disks.sort(key=lambda item: item.index)
        return disks

    def _partitions_for_disk(
        self,
        disk: Any,
        logical_disks: dict[str, Any],
    ) -> list[DiskPartitionInfo]:
        partitions: list[DiskPartitionInfo] = []

        for partition in disk.associators("Win32_DiskDriveToDiskPartition"):
            logical_mounts = list(partition.associators("Win32_LogicalDiskToPartition"))
            if not logical_mounts:
                partitions.append(self._partition_info(disk, partition, None))
                continue

            for logical_ref in logical_mounts:
                logical_id = str(getattr(logical_ref, "DeviceID", "")).upper()
                logical = logical_disks.get(logical_id, logical_ref)
                partitions.append(self._partition_info(disk, partition, logical))

        partitions.sort(key=lambda item: (item.partition_index is None, item.partition_index or 0))
        return partitions

    def _partition_info(self, disk: Any, partition: Any, logical: Any | None) -> DiskPartitionInfo:
        disk_index = _safe_int(getattr(disk, "Index", None), default=-1)
        partition_index = _safe_int(getattr(partition, "Index", None))
        mount_point = _mount_point(logical)
        filesystem = _clean_text(getattr(logical, "FileSystem", None)) if logical else None
        volume_label = _clean_text(getattr(logical, "VolumeName", None)) if logical else None
        drive_type = DRIVE_TYPE_MAP.get(_safe_int(getattr(logical, "DriveType", None), 0), "unknown")

        total_bytes = _safe_int(getattr(logical, "Size", None)) if logical else _safe_int(getattr(partition, "Size", None))
        free_bytes = _free_bytes(mount_point, logical)
        used_bytes = total_bytes - free_bytes if total_bytes is not None and free_bytes is not None else None
        percent_used = (
            round((used_bytes / total_bytes) * 100, 2)
            if used_bytes is not None and total_bytes and total_bytes > 0
            else None
        )

        partition_name = _clean_text(getattr(partition, "Name", None)) or f"Disk {disk_index} partition"
        partition_id = f"{disk_index}:{partition_index}" if partition_index is not None else partition_name

        return DiskPartitionInfo(
            id=partition_id,
            disk_index=disk_index,
            partition_index=partition_index,
            name=partition_name,
            device_id=_clean_text(getattr(partition, "DeviceID", None)) or partition_name,
            mount_point=mount_point,
            volume_label=volume_label,
            filesystem=filesystem,
            drive_type=drive_type,
            total_bytes=total_bytes,
            free_bytes=free_bytes,
            used_bytes=used_bytes,
            percent_used=percent_used,
        )

    def _match_storage_disk(self, disk: Any, storage_disks: list[Any]) -> Any | None:
        serial = _normalize_identifier(getattr(disk, "SerialNumber", None))
        model = (_clean_text(getattr(disk, "Model", None)) or "").lower()
        size = _safe_int(getattr(disk, "Size", None))

        for storage_disk in storage_disks:
            storage_serial = _normalize_identifier(getattr(storage_disk, "SerialNumber", None))
            if serial and serial == storage_serial:
                return storage_disk

        for storage_disk in storage_disks:
            friendly_name = (_clean_text(getattr(storage_disk, "FriendlyName", None)) or "").lower()
            storage_size = _safe_int(getattr(storage_disk, "Size", None))
            name_matches = bool(model and (model in friendly_name or friendly_name in model))
            size_matches = size is not None and storage_size is not None and abs(size - storage_size) < 2_000_000
            if name_matches and size_matches:
                return storage_disk

        return None

    def _media_type(self, storage_disk: Any | None) -> str:
        if storage_disk is None:
            return "unknown"
        media_type = _safe_int(getattr(storage_disk, "MediaType", None), 0)
        return MSFT_MEDIA_TYPE_MAP.get(media_type, "unknown")

    def _bus_type(self, storage_disk: Any | None) -> str | None:
        if storage_disk is None:
            return None
        bus_type = _safe_int(getattr(storage_disk, "BusType", None), 0)
        return MSFT_BUS_TYPE_MAP.get(bus_type, "unknown")

    def _device_type(self, disk: Any, media_type: str, bus_type: str | None) -> tuple[str, str]:
        model = (_clean_text(getattr(disk, "Model", None)) or "").lower()
        interface_type = (_clean_text(getattr(disk, "InterfaceType", None)) or "").lower()

        if bus_type == "nvme" or interface_type == "nvme":
            return "nvme", "MSFT_PhysicalDisk.BusType"
        if media_type in {"ssd", "hdd", "scm"}:
            return media_type, "MSFT_PhysicalDisk.MediaType"
        if "nvme" in model:
            return "nvme", "model_heuristic"
        if "ssd" in model or "solid state" in model:
            return "ssd", "model_heuristic"
        if "hdd" in model or "hard disk" in model:
            return "hdd", "model_heuristic"
        return "unknown", "unavailable"


def _free_bytes(mount_point: str | None, logical: Any | None) -> int | None:
    if logical is not None:
        value = _safe_int(getattr(logical, "FreeSpace", None))
        if value is not None:
            return value

    if mount_point:
        try:
            return int(psutil.disk_usage(mount_point).free)
        except OSError:
            return None
    return None


def _mount_point(logical: Any | None) -> str | None:
    if logical is None:
        return None
    device_id = _clean_text(getattr(logical, "DeviceID", None))
    if not device_id:
        return None
    return str(Path(f"{device_id}\\"))


def _safe_int(value: Any, default: int | None = None) -> int | None:
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


class _ComContext:
    def initialize(self) -> None:
        if getattr(_COM_STATE, "initialized", False):
            return
        try:
            import pythoncom  # type: ignore

            pythoncom.CoInitialize()
            _COM_STATE.initialized = True
        except ImportError:
            return

    def close(self) -> None:
        gc.collect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print(WindowsDiskDetector().detect_json(indent=2))
