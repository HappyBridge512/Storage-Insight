from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PluginDescriptor:
    name: str
    path: Path
    enabled: bool


class PluginManager:
    def __init__(self, plugin_dir: Path) -> None:
        self._plugin_dir = plugin_dir

    def discover(self) -> list[PluginDescriptor]:
        if not self._plugin_dir.exists():
            return []
        return [
            PluginDescriptor(name=entry.name, path=entry, enabled=True)
            for entry in self._plugin_dir.iterdir()
            if entry.is_dir()
        ]
