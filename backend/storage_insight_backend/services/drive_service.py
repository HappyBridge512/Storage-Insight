from __future__ import annotations

import asyncio
import platform
import threading
import time
from dataclasses import dataclass
from typing import Any

import psutil

from storage_insight_backend.core.logging import get_logger
from storage_insight_backend.models.disk import DiskPartitionInfo, PhysicalDiskInfo
from storage_insight_backend.models.drive import DriveInfo
from storage_insight_backend.services.smart_service import SmartService
from storage_insight_backend.services.windows_disk_detector import WindowsDiskDetector

logger = get_logger(__name__)


@dataclass(frozen=True)
class DriveMountMetadata:
    disk: PhysicalDiskInfo
    partition: DiskPartitionInfo


class DriveService:
    def __init__(self, smart_service: SmartService, disk_detector: WindowsDiskDetector | None = None) -> None:
        self._smart_service = smart_service
        self._disk_detector = disk_detector or WindowsDiskDetector(logger)
        self._metadata_cache: dict[str, DriveMountMetadata] = {}
        self._metadata_cache_at = 0.0
        self._metadata_lock = threading.Lock()

    async def list_drives(self) -> list[dict[str, object]]:
        return await asyncio.to_thread(self._list_drives_sync)

    def _list_drives_sync(self) -> list[dict[str, object]]:
        windows_metadata = self._windows_disk_metadata_cached() if platform.system() == "Windows" else {}
        drives: list[DriveInfo] = []

        for partition in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except OSError as exc:
                logger.debug("disk usage unavailable for %s: %s", partition.mountpoint, exc)
                continue

            metadata = windows_metadata.get(partition.mountpoint.rstrip("\\").upper())
            disk = metadata.disk if metadata else None
            partition_info = metadata.partition if metadata else None

            smart = self._smart_service.read_for_drive(
                disk.id if disk else None,
                disk.model if disk else None,
                disk.serial_number if disk else None,
            )

            drives.append(
                DriveInfo(
                    id=partition.mountpoint.rstrip("\\/") or partition.device,
                    mount_point=partition.mountpoint,
                    device=partition.device,
                    file_system=partition_info.filesystem if partition_info else partition.fstype,
                    drive_type=partition_info.drive_type if partition_info else self._infer_drive_type(partition),
                    total_bytes=int(usage.total),
                    free_bytes=int(usage.free),
                    used_bytes=int(usage.used),
                    percent_used=round(float(usage.percent), 2),
                    volume_label=partition_info.volume_label if partition_info else None,
                    physical_device=disk.id if disk else None,
                    model=disk.model if disk else None,
                    serial=disk.serial_number if disk else None,
                    interface_type=disk.interface_type if disk else None,
                    storage_bus_type=disk.storage_bus_type if disk else None,
                    storage_type=disk.device_type if disk else "unknown",
                    smart=smart,
                )
            )

        return [drive.to_dict() for drive in drives]

    def _infer_drive_type(self, partition: Any) -> str:
        opts = set(str(partition.opts).lower().split(","))
        if "cdrom" in opts:
            return "optical"
        if "remote" in opts:
            return "network"
        return "fixed"

    def _windows_disk_metadata_cached(self) -> dict[str, DriveMountMetadata]:
        with self._metadata_lock:
            now = time.monotonic()
            if self._metadata_cache and now - self._metadata_cache_at < 60:
                return self._metadata_cache

            self._metadata_cache = self._windows_disk_metadata()
            self._metadata_cache_at = now
            return self._metadata_cache

    def _windows_disk_metadata(self) -> dict[str, DriveMountMetadata]:
        result = self._disk_detector.detect()
        if result.errors:
            for error in result.errors:
                logger.info("Windows disk detector warning: %s", error)

        metadata: dict[str, DriveMountMetadata] = {}
        for disk in result.disks:
            for partition in disk.partitions:
                if partition.mount_point:
                    metadata[partition.mount_point.rstrip("\\").upper()] = DriveMountMetadata(
                        disk=disk,
                        partition=partition,
                    )
        return metadata
