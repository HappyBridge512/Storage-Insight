from __future__ import annotations

import asyncio
import sys

from storage_insight_backend.core.config import AppConfig
from storage_insight_backend.core.logging import configure_logging, get_logger
from storage_insight_backend.ipc.jsonl import JsonLineTransport
from storage_insight_backend.ipc.router import BackendRouter
from storage_insight_backend.services.alert_service import AlertService
from storage_insight_backend.services.drive_service import DriveService
from storage_insight_backend.services.folder_scanner import FolderScanner
from storage_insight_backend.services.monitor_service import MonitorService
from storage_insight_backend.services.smart_service import SmartService

logger = get_logger(__name__)


async def run() -> None:
    config = AppConfig.load()
    configure_logging(config)

    transport = JsonLineTransport(sys.stdin, sys.stdout)
    smart_service = SmartService()
    drive_service = DriveService(smart_service)
    alert_service = AlertService(
        config_dir=config.config_dir,
        monitoring_config=config.monitoring,
        alert_config=config.alerts,
        emit=transport.emit,
    )
    monitor_service = MonitorService(drive_service, alert_service, transport.emit, config.monitoring)
    folder_scanner = FolderScanner(transport.emit, config.scanner)
    router = BackendRouter(config, drive_service, monitor_service, folder_scanner, smart_service, alert_service)

    logger.info("Storage Insight backend starting")
    await transport.emit("backend.started", {"version": "0.1.0"})

    try:
        while True:
            message = await transport.read_message()
            if message is None:
                logger.info("stdin closed; shutting down backend")
                break

            if message.method == "shutdown":
                await transport.respond_ok(message.id, {"status": "shutting_down"})
                break

            try:
                result = await router.dispatch(message.method, message.payload)
                await transport.respond_ok(message.id, result)
            except Exception as exc:  # noqa: BLE001 - IPC boundary must not crash process.
                logger.exception("request failed: %s", message.method)
                await transport.respond_error(message.id, str(exc), exc.__class__.__name__)
    finally:
        await monitor_service.stop()
        await folder_scanner.shutdown()
        await alert_service.shutdown()
        logger.info("Storage Insight backend stopped")
