from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from storage_insight_backend.core.config import AlertConfig, MonitoringConfig
from storage_insight_backend.core.logging import get_logger
from storage_insight_backend.models.alert import AlertCandidate, AlertRecord

logger = get_logger(__name__)

Emit = Callable[[str, Any], Awaitable[None]]


class AlertService:
    def __init__(
        self,
        *,
        config_dir: str,
        monitoring_config: MonitoringConfig,
        alert_config: AlertConfig,
        emit: Emit,
    ) -> None:
        self._monitoring_config = monitoring_config
        self._alert_config = alert_config
        self._emit = emit
        self._db_path = Path(config_dir) / "alerts.db"
        self._lock = threading.Lock()
        self._connection: sqlite3.Connection | None = None
        self._activity_high_since: dict[str, float] = {}

    async def evaluate(self, drives: list[dict[str, Any]], activity: dict[str, Any]) -> list[dict[str, Any]]:
        now = time.time()
        candidates = self._build_candidates(drives, activity, now)
        active, events = await asyncio.to_thread(self._evaluate_sync, candidates, now)

        for event_name, record in events:
            try:
                await self._emit(event_name, record)
            except Exception:
                logger.exception("failed to emit alert event %s", event_name)

        return [record.to_dict() for record in active]

    async def active(self) -> list[dict[str, Any]]:
        records = await asyncio.to_thread(self._select_records_sync, True, self._alert_config.history_limit)
        return [record.to_dict() for record in records]

    async def history(self, *, limit: int | None = None, include_resolved: bool = True) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit or self._alert_config.history_limit), 1000))
        records = await asyncio.to_thread(self._select_records_sync, None if include_resolved else True, safe_limit)
        return [record.to_dict() for record in records]

    async def shutdown(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _build_candidates(
        self,
        drives: list[dict[str, Any]],
        activity: dict[str, Any],
        now: float,
    ) -> list[AlertCandidate]:
        candidates: list[AlertCandidate] = []
        low_space_threshold = float(self._monitoring_config.low_space_percent)

        for drive in drives:
            drive_id = _clean_text(drive.get("id"))
            mount = _clean_text(drive.get("mount_point")) or drive_id or "drive"
            free_percent = 100.0 - float(drive.get("percent_used") or 0.0)
            if free_percent <= low_space_threshold:
                candidates.append(
                    AlertCandidate(
                        code="low_space",
                        severity="warning" if free_percent > 3 else "critical",
                        title="Low disk space",
                        message=f"{mount} has {free_percent:.1f}% free space remaining.",
                        source="capacity",
                        drive_id=drive_id,
                        value=round(free_percent, 2),
                        threshold=low_space_threshold,
                        metadata={"metric": "free_percent", "mount_point": mount},
                    )
                )

            smart = drive.get("smart") if isinstance(drive.get("smart"), dict) else {}
            temperature = _number_or_none(smart.get("temperature_celsius"))
            if temperature is not None and temperature >= self._monitoring_config.high_temperature_celsius:
                candidates.append(
                    AlertCandidate(
                        code="high_temperature",
                        severity="critical" if temperature >= self._monitoring_config.high_temperature_celsius + 10 else "warning",
                        title="High disk temperature",
                        message=f"{mount} temperature is {temperature:.0f} C.",
                        source="smart",
                        drive_id=drive_id,
                        value=temperature,
                        threshold=self._monitoring_config.high_temperature_celsius,
                        metadata={"metric": "temperature_celsius", "mount_point": mount},
                    )
                )

            health = str(smart.get("health") or "unknown").lower()
            if health in {"warning", "critical"}:
                candidates.append(
                    AlertCandidate(
                        code="smart_health",
                        severity="critical" if health == "critical" else "warning",
                        title="SMART health warning",
                        message=f"{mount} SMART health is {health}.",
                        source="smart",
                        drive_id=drive_id,
                        value=health,
                        threshold="ok",
                        metadata={
                            "metric": "health",
                            "mount_point": mount,
                            "reason": smart.get("reason"),
                            "source": smart.get("source"),
                        },
                    )
                )

            self._smart_metric_alert(candidates, drive_id, mount, smart, "reallocated_sectors", "Reallocated sectors")
            self._smart_metric_alert(candidates, drive_id, mount, smart, "read_errors", "SMART read errors")
            self._smart_metric_alert(candidates, drive_id, mount, smart, "write_errors", "SMART write errors")
            self._smart_metric_alert(candidates, drive_id, mount, smart, "media_errors", "SMART media errors")

        self._add_activity_alerts(candidates, activity, now)
        return candidates

    def _smart_metric_alert(
        self,
        candidates: list[AlertCandidate],
        drive_id: str | None,
        mount: str,
        smart: dict[str, Any],
        metric: str,
        title: str,
    ) -> None:
        value = _number_or_none(smart.get(metric))
        if value is None or value <= 0:
            return

        candidates.append(
            AlertCandidate(
                code=f"smart_{metric}",
                severity="warning",
                title=title,
                message=f"{mount} reports {value:.0f} {metric.replace('_', ' ')}.",
                source="smart",
                drive_id=drive_id,
                value=value,
                threshold=0,
                metadata={"metric": metric, "mount_point": mount, "source": smart.get("source")},
            )
        )

    def _add_activity_alerts(self, candidates: list[AlertCandidate], activity: dict[str, Any], now: float) -> None:
        high_activity_percent = float(self._monitoring_config.high_activity_percent)
        sustain_seconds = float(getattr(self._monitoring_config, "abnormal_activity_sustain_seconds", 15.0))
        min_iops = float(getattr(self._monitoring_config, "abnormal_activity_min_iops", 100.0))
        min_bytes = float(getattr(self._monitoring_config, "abnormal_activity_min_bytes_per_second", 10_000_000.0))
        currently_high: set[str] = set()

        for disk in activity.get("disks", []) or []:
            if not isinstance(disk, dict):
                continue
            disk_name = _clean_text(disk.get("disk_name"))
            active_time = _number_or_none(disk.get("active_time_percent"))
            total_iops = _number_or_none(disk.get("total_iops")) or 0.0
            throughput = (_number_or_none(disk.get("read_bytes_per_second")) or 0.0) + (
                _number_or_none(disk.get("write_bytes_per_second")) or 0.0
            )

            if not disk_name or active_time is None:
                continue

            is_high = active_time >= high_activity_percent and (total_iops >= min_iops or throughput >= min_bytes)
            if not is_high:
                self._activity_high_since.pop(disk_name, None)
                continue

            currently_high.add(disk_name)
            high_since = self._activity_high_since.setdefault(disk_name, now)
            if now - high_since < sustain_seconds:
                continue

            candidates.append(
                AlertCandidate(
                    code="abnormal_activity",
                    severity="info" if active_time < 98 else "warning",
                    title="Sustained disk activity",
                    message=f"{disk_name} active time is {active_time:.1f}%.",
                    source="activity",
                    disk_name=disk_name,
                    value=active_time,
                    threshold=high_activity_percent,
                    metadata={
                        "metric": "active_time_percent",
                        "total_iops": total_iops,
                        "throughput_bytes_per_second": throughput,
                    },
                )
            )

        stale_names = set(self._activity_high_since) - currently_high
        for disk_name in stale_names:
            self._activity_high_since.pop(disk_name, None)

    def _evaluate_sync(
        self,
        candidates: list[AlertCandidate],
        now: float,
    ) -> tuple[list[AlertRecord], list[tuple[str, dict[str, Any]]]]:
        with self._lock:
            connection = self._connection_sync()
            active_rows = {
                str(row["fingerprint"]): row
                for row in connection.execute("SELECT * FROM alerts WHERE active = 1")
            }
            seen: set[str] = set()
            active_records: list[AlertRecord] = []
            events: list[tuple[str, dict[str, Any]]] = []

            for candidate in candidates:
                fingerprint = _fingerprint(candidate)
                seen.add(fingerprint)
                existing = active_rows.get(fingerprint) or self._row_by_fingerprint(connection, fingerprint)
                record, event_name = self._upsert_candidate(connection, candidate, fingerprint, existing, now)
                active_records.append(record)
                if event_name:
                    events.append((event_name, record.to_dict()))

            for fingerprint, row in active_rows.items():
                if fingerprint in seen:
                    continue
                resolved = _record_from_row(row, active=False, last_seen_at=now)
                connection.execute(
                    "UPDATE alerts SET active = 0, last_seen_at = ? WHERE id = ?",
                    (now, resolved.id),
                )
                events.append(("alerts.resolved", resolved.to_dict()))

            self._cleanup_history_locked(connection)
            connection.commit()
            return sorted(active_records, key=lambda record: _severity_rank(record.severity), reverse=True), events

    def _upsert_candidate(
        self,
        connection: sqlite3.Connection,
        candidate: AlertCandidate,
        fingerprint: str,
        existing: sqlite3.Row | None,
        now: float,
    ) -> tuple[AlertRecord, str | None]:
        if existing is None:
            record = _record_from_candidate(candidate, fingerprint, now)
            self._insert_record(connection, record)
            return record, "alerts.raised"

        previous = _record_from_row(existing)
        event_name: str | None = None
        next_count = previous.count + 1
        record = _record_from_candidate(
            candidate,
            fingerprint,
            now,
            record_id=previous.id,
            created_at=previous.created_at,
            count=next_count,
        )

        was_inactive = not bool(previous.active)
        cooldown_elapsed = now - previous.last_seen_at >= float(self._alert_config.cooldown_seconds)
        update_elapsed = now - previous.last_seen_at >= float(self._alert_config.active_update_interval_seconds)
        changed = (
            previous.severity != record.severity
            or previous.message != record.message
            or previous.value != record.value
            or was_inactive
        )

        if was_inactive and cooldown_elapsed:
            event_name = "alerts.raised"
        if changed or update_elapsed:
            self._update_record(connection, record)
        else:
            record = _record_from_candidate(
                candidate,
                fingerprint,
                now,
                record_id=previous.id,
                created_at=previous.created_at,
                count=previous.count,
            )

        return record, event_name

    def _select_records_sync(self, active: bool | None, limit: int) -> list[AlertRecord]:
        with self._lock:
            connection = self._connection_sync()
            if active is None:
                rows = connection.execute(
                    "SELECT * FROM alerts ORDER BY last_seen_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM alerts WHERE active = ? ORDER BY last_seen_at DESC LIMIT ?",
                    (1 if active else 0, limit),
                ).fetchall()
            return [_record_from_row(row) for row in rows]

    def _insert_record(self, connection: sqlite3.Connection, record: AlertRecord) -> None:
        connection.execute(
            """
            INSERT INTO alerts (
                id, fingerprint, code, severity, title, message, source, drive_id, disk_name,
                value_json, threshold_json, metadata_json, created_at, last_seen_at, count, active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _record_params(record),
        )

    def _update_record(self, connection: sqlite3.Connection, record: AlertRecord) -> None:
        connection.execute(
            """
            UPDATE alerts
            SET code = ?, severity = ?, title = ?, message = ?, source = ?, drive_id = ?,
                disk_name = ?, value_json = ?, threshold_json = ?, metadata_json = ?,
                last_seen_at = ?, count = ?, active = ?
            WHERE id = ?
            """,
            (
                record.code,
                record.severity,
                record.title,
                record.message,
                record.source,
                record.drive_id,
                record.disk_name,
                _json_dumps(record.value),
                _json_dumps(record.threshold),
                _json_dumps(record.metadata),
                record.last_seen_at,
                record.count,
                1 if record.active else 0,
                record.id,
            ),
        )

    def _cleanup_history_locked(self, connection: sqlite3.Connection) -> None:
        limit = max(1, int(self._alert_config.history_limit))
        stale_ids = [
            str(row["id"])
            for row in connection.execute(
                """
                SELECT id FROM alerts
                WHERE active = 0
                ORDER BY last_seen_at DESC
                LIMIT -1 OFFSET ?
                """,
                (limit,),
            )
        ]
        if stale_ids:
            connection.executemany("DELETE FROM alerts WHERE id = ?", [(alert_id,) for alert_id in stale_ids])

    def _row_by_fingerprint(self, connection: sqlite3.Connection, fingerprint: str) -> sqlite3.Row | None:
        return connection.execute("SELECT * FROM alerts WHERE fingerprint = ?", (fingerprint,)).fetchone()

    def _connection_sync(self) -> sqlite3.Connection:
        if self._connection is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._db_path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    code TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    source TEXT NOT NULL,
                    drive_id TEXT,
                    disk_name TEXT,
                    value_json TEXT NOT NULL,
                    threshold_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    count INTEGER NOT NULL,
                    active INTEGER NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_alerts_active_seen ON alerts(active, last_seen_at)")
            self._connection = connection
        return self._connection

    def _close_sync(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None


def _record_from_candidate(
    candidate: AlertCandidate,
    fingerprint: str,
    now: float,
    *,
    record_id: str | None = None,
    created_at: float | None = None,
    count: int = 1,
) -> AlertRecord:
    return AlertRecord(
        id=record_id or uuid.uuid4().hex,
        fingerprint=fingerprint,
        code=candidate.code,
        severity=candidate.severity,
        title=candidate.title,
        message=candidate.message,
        source=candidate.source,
        drive_id=candidate.drive_id,
        disk_name=candidate.disk_name,
        value=candidate.value,
        threshold=candidate.threshold,
        metadata=dict(candidate.metadata),
        created_at=created_at or now,
        last_seen_at=now,
        count=count,
        active=True,
    )


def _record_from_row(
    row: sqlite3.Row,
    *,
    active: bool | None = None,
    last_seen_at: float | None = None,
) -> AlertRecord:
    return AlertRecord(
        id=str(row["id"]),
        fingerprint=str(row["fingerprint"]),
        code=str(row["code"]),
        severity=str(row["severity"]),
        title=str(row["title"]),
        message=str(row["message"]),
        source=str(row["source"]),
        drive_id=row["drive_id"],
        disk_name=row["disk_name"],
        value=json.loads(str(row["value_json"])),
        threshold=json.loads(str(row["threshold_json"])),
        metadata=json.loads(str(row["metadata_json"])),
        created_at=float(row["created_at"]),
        last_seen_at=float(last_seen_at if last_seen_at is not None else row["last_seen_at"]),
        count=int(row["count"]),
        active=bool(row["active"]) if active is None else active,
    )


def _record_params(record: AlertRecord) -> tuple[Any, ...]:
    return (
        record.id,
        record.fingerprint,
        record.code,
        record.severity,
        record.title,
        record.message,
        record.source,
        record.drive_id,
        record.disk_name,
        _json_dumps(record.value),
        _json_dumps(record.threshold),
        _json_dumps(record.metadata),
        record.created_at,
        record.last_seen_at,
        record.count,
        1 if record.active else 0,
    )


def _fingerprint(candidate: AlertCandidate) -> str:
    raw = "\x1f".join(candidate.fingerprint_parts())
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _number_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _severity_rank(severity: str) -> int:
    return {"critical": 3, "warning": 2, "info": 1}.get(severity, 0)
