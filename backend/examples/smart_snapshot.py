from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

PROJECT_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_BACKEND))

from storage_insight_backend.services.smart_service import SmartService


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    snapshot = SmartService(polling_interval_seconds=30).snapshot(force=True)
    print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
