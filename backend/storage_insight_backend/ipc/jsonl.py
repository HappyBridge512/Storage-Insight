from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, TextIO


@dataclass(frozen=True)
class RequestMessage:
    id: str
    method: str
    payload: dict[str, Any]


class JsonLineTransport:
    def __init__(self, input_stream: TextIO, output_stream: TextIO) -> None:
        self._input = input_stream
        self._output = output_stream
        self._write_lock = asyncio.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def read_message(self) -> RequestMessage | None:
        try:
            line = await asyncio.to_thread(self._input.readline)
        except (BrokenPipeError, OSError):
            self._closed = True
            return None
        if line == "":
            return None

        raw = json.loads(line)
        return RequestMessage(
            id=str(raw["id"]),
            method=str(raw["method"]),
            payload=dict(raw.get("payload") or {}),
        )

    async def respond_ok(self, request_id: str, result: Any) -> None:
        await self._write({"id": request_id, "ok": True, "result": result})

    async def respond_error(self, request_id: str, message: str, code: str = "BackendError") -> None:
        await self._write({"id": request_id, "ok": False, "error": {"code": code, "message": message}})

    async def emit(self, event: str, payload: Any) -> None:
        await self._write({"event": event, "payload": payload})

    async def _write(self, message: dict[str, Any]) -> None:
        async with self._write_lock:
            if self._closed:
                return
            encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
            try:
                self._output.write(encoded + "\n")
                self._output.flush()
            except (BrokenPipeError, OSError):
                # The Rust parent owns the other end of this pipe. Once it has
                # closed the window or process, no response can be delivered.
                self._closed = True
