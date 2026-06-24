from __future__ import annotations

import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from storage_insight_backend.core.config import AppConfig


def configure_logging(config: AppConfig) -> None:
    level = getattr(logging, config.logging.level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    errors: list[str] = []
    for log_file in _candidate_log_files(config):
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
            if errors:
                root.warning("primary file logging unavailable; using %s; errors: %s", log_file, "; ".join(errors))
            return
        except OSError as exc:
            errors.append(f"{log_file}: {exc}")

    fallback_handler = logging.StreamHandler(sys.stderr)
    fallback_handler.setFormatter(formatter)
    root.addHandler(fallback_handler)
    root.warning("file logging unavailable; using stderr fallback: %s", "; ".join(errors))


def _candidate_log_files(config: AppConfig) -> list[Path]:
    candidates = [Path(config.logging.directory) / config.logging.filename]
    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Storage Insight" / "logs" / config.logging.filename)
    candidates.append(Path.home() / ".storage-insight" / "logs" / config.logging.filename)
    candidates.append(Path(tempfile.gettempdir()) / "Storage Insight" / "logs" / config.logging.filename)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
