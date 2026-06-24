from __future__ import annotations

from typing import Any

from storage_insight_backend.core.config import AppConfig
from storage_insight_backend.services.alert_service import AlertService
from storage_insight_backend.services.drive_service import DriveService
from storage_insight_backend.services.folder_scanner import FolderScanner
from storage_insight_backend.services.monitor_service import MonitorService
from storage_insight_backend.services.smart_service import SmartService


class BackendRouter:
    def __init__(
        self,
        config: AppConfig,
        drive_service: DriveService,
        monitor_service: MonitorService,
        folder_scanner: FolderScanner,
        smart_service: SmartService,
        alert_service: AlertService,
    ) -> None:
        self._config = config
        self._drive_service = drive_service
        self._monitor_service = monitor_service
        self._folder_scanner = folder_scanner
        self._smart_service = smart_service
        self._alert_service = alert_service

    async def dispatch(self, method: str, payload: dict[str, Any]) -> Any:
        match method:
            case "config.get":
                return self._config.to_public_dict()
            case "drives.list":
                return {"drives": await self._drive_service.list_drives()}
            case "monitoring.start":
                await self._monitor_service.start()
                return {"status": "started"}
            case "monitoring.stop":
                await self._monitor_service.stop()
                return {"status": "stopped"}
            case "monitoring.snapshot":
                return await self._monitor_service.snapshot()
            case "activity.start":
                await self._monitor_service.activity_start()
                return {"status": "started"}
            case "activity.stop":
                await self._monitor_service.activity_stop()
                return {"status": "stopped"}
            case "activity.snapshot":
                force = bool(payload.get("force", False))
                return await self._monitor_service.activity_snapshot(force_poll=force)
            case "smart.snapshot":
                force = bool(payload.get("force", False))
                return self._smart_service.snapshot_dict(force=force)
            case "alerts.active":
                return {"alerts": await self._alert_service.active()}
            case "alerts.history":
                return {
                    "alerts": await self._alert_service.history(
                        limit=payload.get("limit"),
                        include_resolved=bool(payload.get("includeResolved", True)),
                    )
                }
            case "scanner.scanFolder":
                path = str(payload.get("path") or "")
                if not path:
                    raise ValueError("path is required")
                max_depth = payload.get("maxDepth")
                return await self._folder_scanner.scan(path, max_depth=max_depth)
            case "scanner.start":
                path = str(payload.get("path") or "")
                if not path:
                    raise ValueError("path is required")
                return await self._folder_scanner.start_scan(
                    path,
                    max_depth=payload.get("maxDepth"),
                    scan_id=payload.get("scanId"),
                )
            case "scanner.cancel":
                scan_id = payload.get("scanId")
                return await self._folder_scanner.cancel(str(scan_id) if scan_id else None)
            case "scanner.result":
                scan_id = str(payload.get("scanId") or "")
                if not scan_id:
                    raise ValueError("scanId is required")
                return await self._folder_scanner.result(scan_id)
            case _:
                raise KeyError(f"Unknown backend method: {method}")
