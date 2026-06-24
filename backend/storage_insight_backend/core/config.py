from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any


def _default_config_dir() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "Storage Insight"
    return Path.home() / ".storage-insight"


@dataclass(frozen=True)
class MonitoringConfig:
    interval_seconds: float = 2.0
    low_space_percent: float = 10.0
    high_temperature_celsius: int = 55
    high_activity_percent: float = 92.0
    abnormal_activity_min_iops: float = 100.0
    abnormal_activity_min_bytes_per_second: float = 10_000_000.0
    abnormal_activity_sustain_seconds: float = 15.0


@dataclass(frozen=True)
class AlertConfig:
    cooldown_seconds: float = 300.0
    history_limit: int = 500
    active_update_interval_seconds: float = 60.0
    enable_desktop_notifications: bool = True


@dataclass(frozen=True)
class ScannerConfig:
    max_depth: int = 12
    max_children_per_node: int = 80
    max_result_nodes: int = 0
    max_file_types: int = 64
    completed_result_limit: int = 3
    max_active_scans: int = 1
    progress_interval_ms: int = 350


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    directory: str = ""
    filename: str = "storage-insight-backend.log"


@dataclass(frozen=True)
class AppConfig:
    config_dir: str = ""
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    plugins_enabled: bool = True
    ai_modules_enabled: bool = False

    @classmethod
    def load(cls) -> "AppConfig":
        config_dir = Path(os.getenv("STORAGE_INSIGHT_CONFIG_DIR") or _default_config_dir())
        config_path = config_dir / "config.json"
        base = cls(config_dir=str(config_dir), logging=LoggingConfig(directory=str(config_dir / "logs")))

        if not config_path.exists():
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(asdict(base), indent=2), encoding="utf-8")
            return base

        raw = json.loads(config_path.read_text(encoding="utf-8"))
        return cls.from_dict(raw, config_dir)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], config_dir: Path) -> "AppConfig":
        logging_raw = raw.get("logging") or {}
        if not logging_raw.get("directory"):
            logging_raw["directory"] = str(config_dir / "logs")

        return cls(
            config_dir=str(config_dir),
            monitoring=_dataclass_from_dict(MonitoringConfig, raw.get("monitoring") or {}),
            alerts=_dataclass_from_dict(AlertConfig, raw.get("alerts") or {}),
            scanner=_scanner_config_from_dict(raw.get("scanner") or {}),
            logging=_dataclass_from_dict(LoggingConfig, logging_raw),
            plugins_enabled=bool(raw.get("plugins_enabled", True)),
            ai_modules_enabled=bool(raw.get("ai_modules_enabled", False)),
        )

    def to_public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["config_dir"] = str(self.config_dir)
        return data


def _dataclass_from_dict(model: type[Any], raw: dict[str, Any]) -> Any:
    if not is_dataclass(model):
        raise TypeError(f"{model!r} is not a dataclass")
    allowed = {field.name for field in fields(model)}
    return model(**{key: value for key, value in raw.items() if key in allowed})


def _scanner_config_from_dict(raw: dict[str, Any]) -> ScannerConfig:
    defaults = ScannerConfig()
    return ScannerConfig(
        max_depth=_int_between(raw.get("max_depth", defaults.max_depth), defaults.max_depth, defaults.max_depth),
        max_children_per_node=_int_between(
            raw.get("max_children_per_node", defaults.max_children_per_node),
            defaults.max_children_per_node,
            defaults.max_children_per_node,
        ),
        max_result_nodes=_int_between(
            raw.get("max_result_nodes", defaults.max_result_nodes),
            defaults.max_result_nodes,
            defaults.max_result_nodes,
        ),
        max_file_types=_int_between(raw.get("max_file_types", defaults.max_file_types), 8, defaults.max_file_types),
        completed_result_limit=_int_between(
            raw.get("completed_result_limit", defaults.completed_result_limit),
            1,
            defaults.completed_result_limit,
        ),
        max_active_scans=_int_between(raw.get("max_active_scans", defaults.max_active_scans), 1, defaults.max_active_scans),
        progress_interval_ms=_int_between(raw.get("progress_interval_ms", defaults.progress_interval_ms), 150, 2000),
    )


def _int_between(value: Any, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = maximum
    return min(max(parsed, minimum), maximum)
