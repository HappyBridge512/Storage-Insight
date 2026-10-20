from __future__ import annotations

import asyncio
import errno
import io
import unittest

from storage_insight_backend.ipc.jsonl import JsonLineTransport


class _FlushFails(io.StringIO):
    def flush(self) -> None:
        raise OSError(errno.EINVAL, "Invalid argument")


class _ReadFails(io.StringIO):
    def readline(self, *args: object, **kwargs: object) -> str:
        raise OSError(errno.EINVAL, "Invalid argument")


class JsonLineTransportTests(unittest.TestCase):
    def test_flush_os_error_closes_transport_without_raising(self) -> None:
        output = _FlushFails()
        transport = JsonLineTransport(io.StringIO(), output)

        asyncio.run(transport.emit("monitoring.snapshot", {"drives": []}))

        self.assertTrue(transport.closed)
        asyncio.run(transport.respond_ok("request", {"ignored": True}))
        self.assertEqual(1, output.getvalue().count("\n"))

    def test_read_os_error_is_treated_as_closed_input(self) -> None:
        transport = JsonLineTransport(_ReadFails(), io.StringIO())

        self.assertIsNone(asyncio.run(transport.read_message()))
        self.assertTrue(transport.closed)
