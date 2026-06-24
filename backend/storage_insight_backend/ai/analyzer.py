from __future__ import annotations

from typing import Any


class AnalysisModule:
    def summarize_drive_state(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "enabled": False,
            "summary": "AI analysis module is disabled in this build.",
            "snapshot_drive_count": len(snapshot.get("drives", [])),
        }
