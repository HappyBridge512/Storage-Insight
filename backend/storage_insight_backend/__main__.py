from __future__ import annotations

import asyncio

from storage_insight_backend.app import run


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
