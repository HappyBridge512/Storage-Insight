from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import psutil

from storage_insight_backend.models.activity import (
    DiskActivitySample,
    DiskActivitySnapshot,
    DiskUsageSnapshot,
)
from storage_insight_backend.services.event_bus import AsyncEventBus

logger = logging.getLogger(__name__)

Emit = Callable[[str, Any], Awaitable[None]]


@dataclass(frozen=True)
class _CounterPoint:
    disk_name: str
    timestamp: float
    read_count: int
    write_count: int
    read_bytes: int
    write_bytes: int
    read_time_ms: int | None
    write_time_ms: int | None
    busy_time_ms: int | None


class DiskActivityMonitor:
    def __init__(
        self,
        *,
        interval_seconds: float = 1.0,
        emit: Emit | None = None,
        event_bus: AsyncEventBus | None = None,
    ) -> None:
        self._interval_seconds = max(0.25, float(interval_seconds))
        self._emit = emit
        self._event_bus = event_bus or AsyncEventBus()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._state_lock = threading.Lock()
        self._previous: dict[str, _CounterPoint] = {}
        self._last_snapshot: DiskActivitySnapshot | None = None

    @property
    def event_bus(self) -> AsyncEventBus:
        return self._event_bus

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="disk-activity-monitor")
        logger.info("disk activity monitor started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        logger.info("disk activity monitor stopped")

    async def snapshot(self, *, force_poll: bool = False) -> dict[str, Any]:
        if force_poll or self._last_snapshot is None:
            return (await self._poll()).to_dict()
        return self._last_snapshot.to_dict()

    async def _run(self) -> None:
        await self._poll()
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                pass

            if self._stop_event.is_set():
                break

            try:
                snapshot = await self._poll()
                payload = snapshot.to_dict()
                await self._event_bus.publish("disk.activity", payload)
                if self._emit:
                    await self._emit("disk.activity", payload)
            except Exception:
                logger.exception("disk activity polling failed")

    async def _poll(self) -> DiskActivitySnapshot:
        return await asyncio.to_thread(self._poll_sync)

    def _poll_sync(self) -> DiskActivitySnapshot:
        timestamp = time.time()
        errors: list[str] = []
        points = self._read_counter_points(timestamp, errors)
        usage = self._read_usage(errors)

        samples: list[DiskActivitySample] = []
        with self._state_lock:
            previous_points = self._previous
            for disk_name, point in points.items():
                previous = previous_points.get(disk_name)
                samples.append(self._sample_from_points(point, previous))
            interval = self._snapshot_interval(points, previous_points)
            self._previous = points

        snapshot = DiskActivitySnapshot(
            timestamp=timestamp,
            interval_seconds=interval,
            disks=sorted(samples, key=lambda sample: sample.disk_name.lower()),
            usage=usage,
            errors=errors,
        )
        self._last_snapshot = snapshot
        return snapshot

    def _read_counter_points(self, timestamp: float, errors: list[str]) -> dict[str, _CounterPoint]:
        try:
            counters = psutil.disk_io_counters(perdisk=True)
        except Exception as exc:  # noqa: BLE001 - psutil boundary.
            errors.append(f"disk_io_counters failed: {exc}")
            logger.exception("disk_io_counters failed")
            return {}

        if not counters:
            errors.append("psutil.disk_io_counters returned no disk counters")
            return {}

        return {
            disk_name: _CounterPoint(
                disk_name=disk_name,
                timestamp=timestamp,
                read_count=int(counter.read_count),
                write_count=int(counter.write_count),
                read_bytes=int(counter.read_bytes),
                write_bytes=int(counter.write_bytes),
                read_time_ms=_optional_int(getattr(counter, "read_time", None)),
                write_time_ms=_optional_int(getattr(counter, "write_time", None)),
                busy_time_ms=_optional_int(getattr(counter, "busy_time", None)),
            )
            for disk_name, counter in counters.items()
        }

    def _read_usage(self, errors: list[str]) -> list[DiskUsageSnapshot]:
        usage: list[DiskUsageSnapshot] = []
        try:
            partitions = psutil.disk_partitions(all=False)
        except Exception as exc:  # noqa: BLE001 - psutil boundary.
            errors.append(f"disk_partitions failed: {exc}")
            logger.exception("disk_partitions failed")
            return usage

        for partition in partitions:
            try:
                disk_usage = psutil.disk_usage(partition.mountpoint)
            except OSError as exc:
                logger.debug("disk usage unavailable for %s: %s", partition.mountpoint, exc)
                continue

            usage.append(
                DiskUsageSnapshot(
                    mount_point=partition.mountpoint,
                    device=partition.device,
                    filesystem=partition.fstype,
                    total_bytes=int(disk_usage.total),
                    free_bytes=int(disk_usage.free),
                    used_bytes=int(disk_usage.used),
                    percent_used=round(float(disk_usage.percent), 2),
                )
            )

        return usage

    def _sample_from_points(
        self,
        current: _CounterPoint,
        previous: _CounterPoint | None,
    ) -> DiskActivitySample:
        if previous is None:
            return DiskActivitySample(
                disk_name=current.disk_name,
                read_bytes_per_second=None,
                write_bytes_per_second=None,
                read_iops=None,
                write_iops=None,
                total_iops=None,
                active_time_percent=None,
                active_time_source=None,
                read_bytes_total=current.read_bytes,
                write_bytes_total=current.write_bytes,
                read_count_total=current.read_count,
                write_count_total=current.write_count,
                read_time_ms_total=current.read_time_ms,
                write_time_ms_total=current.write_time_ms,
                busy_time_ms_total=current.busy_time_ms,
            )

        elapsed = max(current.timestamp - previous.timestamp, 0.001)
        read_iops = _rate(current.read_count, previous.read_count, elapsed)
        write_iops = _rate(current.write_count, previous.write_count, elapsed)
        active_time_percent, active_time_source = self._active_time(current, previous, elapsed)

        return DiskActivitySample(
            disk_name=current.disk_name,
            read_bytes_per_second=_rate(current.read_bytes, previous.read_bytes, elapsed),
            write_bytes_per_second=_rate(current.write_bytes, previous.write_bytes, elapsed),
            read_iops=read_iops,
            write_iops=write_iops,
            total_iops=round(read_iops + write_iops, 2),
            active_time_percent=active_time_percent,
            active_time_source=active_time_source,
            read_bytes_total=current.read_bytes,
            write_bytes_total=current.write_bytes,
            read_count_total=current.read_count,
            write_count_total=current.write_count,
            read_time_ms_total=current.read_time_ms,
            write_time_ms_total=current.write_time_ms,
            busy_time_ms_total=current.busy_time_ms,
        )

    def _active_time(
        self,
        current: _CounterPoint,
        previous: _CounterPoint,
        elapsed: float,
    ) -> tuple[float | None, str | None]:
        if current.busy_time_ms is not None and previous.busy_time_ms is not None:
            delta_ms = max(0, current.busy_time_ms - previous.busy_time_ms)
            return min(100.0, round((delta_ms / (elapsed * 1000)) * 100, 2)), "busy_time"

        if (
            current.read_time_ms is not None
            and current.write_time_ms is not None
            and previous.read_time_ms is not None
            and previous.write_time_ms is not None
        ):
            delta_ms = max(
                0,
                (current.read_time_ms - previous.read_time_ms)
                + (current.write_time_ms - previous.write_time_ms),
            )
            return min(100.0, round((delta_ms / (elapsed * 1000)) * 100, 2)), "read_write_time"

        return None, None

    def _snapshot_interval(self, points: dict[str, _CounterPoint], previous: dict[str, _CounterPoint]) -> float:
        if not points:
            return 0.0
        intervals = [point.timestamp - previous[name].timestamp for name, point in points.items() if name in previous]
        if intervals:
            return round(max(intervals), 3)
        return 0.0


def _rate(current: int, previous: int, elapsed: float) -> float:
    return round(max(0, current - previous) / elapsed, 2)


def _optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
