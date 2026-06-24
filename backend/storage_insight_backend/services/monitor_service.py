from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from storage_insight_backend.core.config import MonitoringConfig
from storage_insight_backend.core.logging import get_logger
from storage_insight_backend.services.alert_service import AlertService
from storage_insight_backend.services.disk_activity_monitor import DiskActivityMonitor
from storage_insight_backend.services.drive_service import DriveService

logger = get_logger(__name__)

Emit = Callable[[str, Any], Awaitable[None]]


class MonitorService:
    def __init__(
        self,
        drive_service: DriveService,
        alert_service: AlertService,
        emit: Emit,
        config: MonitoringConfig,
    ) -> None:
        self._drive_service = drive_service
        self._alert_service = alert_service
        self._emit = emit
        self._config = config
        self._activity_monitor = DiskActivityMonitor(interval_seconds=1.0, emit=emit)
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        await self._activity_monitor.start()
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="storage-monitor")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self._activity_monitor.stop()

    async def snapshot(self) -> dict[str, Any]:
        drives = await self._drive_service.list_drives()
        activity = await self._activity_monitor.snapshot()
        io = self._legacy_io_from_activity(activity)
        alerts = await self._alert_service.evaluate(drives, activity)
        return {"drives": drives, "io": io, "activity": activity, "alerts": alerts}

    async def activity_snapshot(self, *, force_poll: bool = False) -> dict[str, Any]:
        return await self._activity_monitor.snapshot(force_poll=force_poll)

    async def activity_start(self) -> None:
        await self._activity_monitor.start()

    async def activity_stop(self) -> None:
        await self._activity_monitor.stop()

    async def _run(self) -> None:
        logger.info("monitoring loop started")
        while not self._stop_event.is_set():
            try:
                await self._emit("monitoring.snapshot", await self.snapshot())
            except Exception:
                logger.exception("monitoring snapshot failed")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._config.interval_seconds)
            except TimeoutError:
                continue
        logger.info("monitoring loop stopped")

    def _legacy_io_from_activity(self, activity: dict[str, Any]) -> dict[str, Any]:
        return {
            str(disk["disk_name"]): {
                "read_bytes": int(disk["read_bytes_total"]),
                "write_bytes": int(disk["write_bytes_total"]),
                "read_count": int(disk["read_count_total"]),
                "write_count": int(disk["write_count_total"]),
                "read_bytes_per_second": disk["read_bytes_per_second"],
                "write_bytes_per_second": disk["write_bytes_per_second"],
                "read_iops": disk["read_iops"],
                "write_iops": disk["write_iops"],
                "total_iops": disk["total_iops"],
                "active_time_percent": disk["active_time_percent"],
            }
            for disk in activity.get("disks", [])
        }
