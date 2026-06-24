from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import sys

PROJECT_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_BACKEND))

from storage_insight_backend.services.disk_activity_monitor import DiskActivityMonitor


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    monitor = DiskActivityMonitor(interval_seconds=1.0)

    async def print_event(_: str, payload: object) -> None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    await monitor.event_bus.subscribe("disk.activity", print_event)
    await monitor.start()
    try:
        await asyncio.sleep(5)
    finally:
        await monitor.stop()


if __name__ == "__main__":
    asyncio.run(main())
