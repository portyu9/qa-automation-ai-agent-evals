"""Shared loopback ASGI hosting primitives for deterministic MCP transport laboratories."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


def bind_loopback_socket() -> socket.socket:
    """Bind and listen on one ephemeral IPv4 loopback socket without a check-then-bind race."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    return listener


@asynccontextmanager
async def serve_prebound(app: Any, listener: socket.socket) -> AsyncIterator[None]:
    """Serve one ASGI app on a pre-bound listener with bounded startup and shutdown."""
    import uvicorn

    port = int(listener.getsockname()[1])
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        access_log=False,
        lifespan="on",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(500):
            if server.started:
                break
            if task.done():
                task.result()
            await asyncio.sleep(0.01)
        else:
            raise RuntimeError("loopback ASGI server did not start")
        yield
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except TimeoutError:
            server.force_exit = True
            await asyncio.wait_for(task, timeout=2.0)
