from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import Any

from storage_insight_backend.core.config import ScannerConfig
from storage_insight_backend.models.folder import FileTypeStat, FolderNode

Emit = Callable[[str, Any], Awaitable[None]]
logger = getLogger(__name__)


@dataclass
class ScanProgress:
    scan_id: str
    path: str
    current_path: str
    scanned_files: int = 0
    scanned_dirs: int = 0
    bytes_scanned: int = 0
    inaccessible_count: int = 0
    cancelled: bool = False
    started_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        elapsed_ms = round((time.perf_counter() - self.started_at) * 1000, 2)
        return {
            "scan_id": self.scan_id,
            "path": self.path,
            "current_path": self.current_path,
            "scanned_files": self.scanned_files,
            "scanned_dirs": self.scanned_dirs,
            "bytes_scanned": self.bytes_scanned,
            "inaccessible_count": self.inaccessible_count,
            "cancelled": self.cancelled,
            "elapsed_ms": elapsed_ms,
        }


@dataclass
class ScanJob:
    scan_id: str
    path: Path
    cancel_event: threading.Event
    task: asyncio.Task[None]


class ProgressReporter:
    def __init__(self, loop: asyncio.AbstractEventLoop, emit: Emit, interval_ms: int) -> None:
        self._loop = loop
        self._emit = emit
        self._interval_seconds = max(0.05, interval_ms / 1000)
        self._last_emit = 0.0
        self._pending: Future[None] | None = None

    def maybe_emit(self, progress: ScanProgress) -> None:
        now = time.perf_counter()
        if now - self._last_emit < self._interval_seconds:
            return
        self._last_emit = now
        self.emit(progress)

    def emit(self, progress: ScanProgress, *, force: bool = False) -> None:
        if self._loop.is_closed():
            return
        if not force and self._pending is not None and not self._pending.done():
            return

        future = asyncio.run_coroutine_threadsafe(
            self._emit("scanner.progress", progress.to_dict()),
            self._loop,
        )
        self._pending = future
        future.add_done_callback(_consume_progress_emit_error)


class BoundedChildren:
    def __init__(self, max_children: int, parent_path: Path, max_file_types: int) -> None:
        self._max_children = max(1, max_children)
        self._max_file_types = max_file_types
        self._children: list[FolderNode] = []
        self._other = FolderNode(name="Other", path=str(parent_path / "*"))

    def add(self, child: FolderNode) -> None:
        if child.size_bytes <= 0 and not child.children:
            return

        self._children.append(child)
        self._children.sort(key=lambda item: item.size_bytes, reverse=True)
        if len(self._children) <= self._max_children:
            return

        overflow = self._children.pop()
        self._other.size_bytes += overflow.size_bytes
        self._other.file_count += overflow.file_count
        self._other.dir_count += overflow.dir_count + 1
        self._other.inaccessible_count += overflow.inaccessible_count
        self._other.merge_file_types(overflow, max_file_types=self._max_file_types)

    def finalize(self) -> list[FolderNode]:
        children = list(self._children)
        if self._other.size_bytes > 0 or self._other.file_count > 0 or self._other.dir_count > 0:
            children.append(self._other)
        return children


class FolderScanner:
    def __init__(self, emit: Emit, config: ScannerConfig) -> None:
        self._emit = emit
        self._config = config
        self._active_jobs: dict[str, ScanJob] = {}
        self._completed: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def start_scan(
        self,
        path: str,
        max_depth: int | None = None,
        scan_id: str | None = None,
    ) -> dict[str, Any]:
        resolved = self._resolve_scan_path(path)
        scan_id = scan_id or uuid.uuid4().hex
        cancel_event = threading.Event()

        async with self._lock:
            active_jobs = list(self._active_jobs.values())
            if len(active_jobs) >= max(1, self._config.max_active_scans):
                for job in active_jobs:
                    job.cancel_event.set()

        task = asyncio.create_task(
            self._run_background_scan(scan_id, resolved, max_depth, cancel_event),
            name=f"folder-scan-{scan_id}",
        )

        async with self._lock:
            self._active_jobs[scan_id] = ScanJob(scan_id, resolved, cancel_event, task)

        await self._emit("scanner.started", {"scan_id": scan_id, "path": str(resolved)})
        return {"scan_id": scan_id, "path": str(resolved), "status": "started"}

    async def scan(self, path: str, max_depth: int | None = None) -> dict[str, Any]:
        resolved = self._resolve_scan_path(path)
        scan_id = uuid.uuid4().hex
        result = await self._scan_async(scan_id, resolved, max_depth, threading.Event())
        return result

    async def cancel(self, scan_id: str | None = None) -> dict[str, Any]:
        async with self._lock:
            jobs = list(self._active_jobs.values()) if not scan_id else []
            if scan_id and scan_id in self._active_jobs:
                jobs = [self._active_jobs[scan_id]]

        for job in jobs:
            job.cancel_event.set()

        return {"status": "cancelling", "scan_ids": [job.scan_id for job in jobs]}

    async def result(self, scan_id: str) -> dict[str, Any]:
        async with self._lock:
            result = self._completed.get(scan_id)
        if result is None:
            raise KeyError(f"Scan result is not available: {scan_id}")
        return result

    async def shutdown(self) -> None:
        async with self._lock:
            jobs = list(self._active_jobs.values())
        for job in jobs:
            job.cancel_event.set()
        if jobs:
            await asyncio.gather(*(job.task for job in jobs), return_exceptions=True)

    async def _run_background_scan(
        self,
        scan_id: str,
        path: Path,
        max_depth: int | None,
        cancel_event: threading.Event,
    ) -> None:
        try:
            result = await self._scan_async(scan_id, path, max_depth, cancel_event)
            await self._store_result(scan_id, result)
            event_name = "scanner.cancelled" if result.get("cancelled") else "scanner.completed"
            await self._emit(
                event_name,
                {
                    "scan_id": scan_id,
                    "path": str(path),
                    "size_bytes": result["root"]["size_bytes"],
                    "file_count": result["root"]["file_count"],
                    "dir_count": result["root"]["dir_count"],
                    "elapsed_ms": result["elapsed_ms"],
                    "cancelled": result["cancelled"],
                },
            )
        except Exception as exc:  # noqa: BLE001 - scan failures must not kill the backend process.
            logger.exception("folder scan failed: %s", path)
            await self._emit(
                "scanner.failed",
                {
                    "scan_id": scan_id,
                    "path": str(path),
                    "message": str(exc),
                    "error_type": exc.__class__.__name__,
                },
            )
        finally:
            async with self._lock:
                self._active_jobs.pop(scan_id, None)

    async def _store_result(self, scan_id: str, result: dict[str, Any]) -> None:
        async with self._lock:
            self._completed[scan_id] = result
            self._completed.move_to_end(scan_id)
            while len(self._completed) > max(1, self._config.completed_result_limit):
                self._completed.popitem(last=False)

    async def _scan_async(
        self,
        scan_id: str,
        path: Path,
        max_depth: int | None,
        cancel_event: threading.Event,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        requested_depth = int(max_depth) if max_depth is not None else self._config.max_depth
        depth = max(0, min(requested_depth, self._config.max_depth))
        loop = asyncio.get_running_loop()
        reporter = ProgressReporter(loop, self._emit, self._config.progress_interval_ms)
        progress = ScanProgress(
            scan_id=scan_id,
            path=str(path),
            current_path=str(path),
            started_at=started,
        )

        root = await asyncio.to_thread(self._scan_sync, path, depth, cancel_event, progress, reporter)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        progress.cancelled = cancel_event.is_set()
        reporter.emit(progress, force=True)

        max_nodes = self._config.max_result_nodes if self._config.max_result_nodes > 0 else None
        root_dict = root.to_dict(
            max_nodes=max_nodes,
            max_file_types=self._config.max_file_types,
            include_nested_file_types=True,
        )
        return {
            "scan_id": scan_id,
            "root": root_dict,
            "file_types": root_dict["file_types"],
            "elapsed_ms": elapsed_ms,
            "cancelled": cancel_event.is_set(),
            "progress": progress.to_dict(),
        }

    def _scan_sync(
        self,
        root_path: Path,
        max_depth: int,
        cancel_event: threading.Event,
        progress: ScanProgress,
        reporter: ProgressReporter,
    ) -> FolderNode:
        file_types: dict[str, FileTypeStat] = {}

        def record_file_type(extension: str, size_bytes: int) -> None:
            stat = file_types.setdefault(extension, FileTypeStat())
            stat.count += 1
            stat.size_bytes += size_bytes

        def walk(path: Path, depth: int) -> FolderNode:
            node = FolderNode(name=path.name or str(path), path=str(path))
            bounded_children = BoundedChildren(
                self._config.max_children_per_node,
                path,
                self._config.max_file_types,
            )

            if cancel_event.is_set() or depth > max_depth:
                return node

            progress.current_path = str(path)
            reporter.maybe_emit(progress)

            try:
                with os.scandir(path) as entries:
                    for entry in entries:
                        if cancel_event.is_set():
                            progress.cancelled = True
                            break

                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_file(follow_symlinks=False):
                                size = entry.stat(follow_symlinks=False).st_size
                                extension = _extension_for(entry.name)
                                node.size_bytes += size
                                node.file_count += 1
                                node.record_file_type(extension, size)
                                node.trim_file_types(self._config.max_file_types)
                                record_file_type(extension, size)
                                progress.scanned_files += 1
                                progress.bytes_scanned += size
                                reporter.maybe_emit(progress)
                            elif entry.is_dir(follow_symlinks=False):
                                progress.scanned_dirs += 1
                                child = walk(Path(entry.path), depth + 1)
                                node.size_bytes += child.size_bytes
                                node.file_count += child.file_count
                                node.dir_count += child.dir_count + 1
                                node.inaccessible_count += child.inaccessible_count
                                node.merge_file_types(child, max_file_types=self._config.max_file_types)
                                bounded_children.add(child)
                                reporter.maybe_emit(progress)
                        except OSError:
                            node.inaccessible_count += 1
                            progress.inaccessible_count += 1
                            reporter.maybe_emit(progress)
            except OSError:
                node.inaccessible_count += 1
                progress.inaccessible_count += 1
                reporter.maybe_emit(progress)

            node.children = bounded_children.finalize()
            return node

        root = walk(root_path, 0)
        root.file_types = file_types
        return root

    def _resolve_scan_path(self, path: str) -> Path:
        if not path:
            raise ValueError("path is required")
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"Folder does not exist: {path}")
        return resolved


def _extension_for(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix or "[no extension]"


def _consume_progress_emit_error(future: Future[None]) -> None:
    try:
        future.result()
    except Exception as exc:  # noqa: BLE001 - progress events are best-effort telemetry.
        logger.debug("scanner progress event was dropped: %s", exc)
