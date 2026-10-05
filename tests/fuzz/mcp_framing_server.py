from __future__ import annotations

import base64
import json
import os
import sys
import time
from typing import Any


def _load_plan() -> dict[str, Any]:
    encoded = os.environ["AGENT_EVALS_MCP_FUZZ_PLAN"]
    padding = "=" * (-len(encoded) % 4)
    raw = base64.urlsafe_b64decode((encoded + padding).encode())
    parsed = json.loads(raw)
    if type(parsed) is not dict:
        raise TypeError("fuzz plan must be a JSON object")
    return parsed


def _read_requests(count: int) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for _ in range(count):
        line = sys.stdin.buffer.readline()
        if not line:
            raise EOFError("stdin closed before all planned requests arrived")
        parsed = json.loads(line)
        if type(parsed) is not dict:
            raise TypeError("request must be a JSON object")
        requests.append(parsed)
    return requests


def _emit_fragmented(value: dict[str, Any], chunk_sizes: list[int]) -> None:
    payload = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        + b"\n"
    )
    offset = 0
    chunk_index = 0
    while offset < len(payload):
        size = chunk_sizes[chunk_index % len(chunk_sizes)]
        chunk_index += 1
        end = min(len(payload), offset + size)
        sys.stdout.buffer.write(payload[offset:end])
        sys.stdout.buffer.flush()
        offset = end
        time.sleep(0.0002)


def main() -> int:
    plan = _load_plan()
    count = plan["count"]
    order = plan["order"]
    chunk_sizes = plan["chunk_sizes"]
    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive integer")
    if type(order) is not list or sorted(order) != list(range(count)):
        raise ValueError("order must be a permutation of request indexes")
    if (
        type(chunk_sizes) is not list
        or not chunk_sizes
        or any(type(size) is not int or not 1 <= size <= 16 for size in chunk_sizes)
    ):
        raise ValueError("chunk_sizes must contain integers from 1 through 16")

    requests = _read_requests(count)
    for response_index in order:
        request = requests[response_index]
        request_id = request.get("id")
        _emit_fragmented(
            {
                "jsonrpc": "2.0",
                "method": "notifications/fuzz",
                "params": {
                    "request_id": request_id,
                    "request_index": response_index,
                },
            },
            chunk_sizes,
        )
        _emit_fragmented(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "request_id": request_id,
                    "request_index": response_index,
                },
            },
            list(reversed(chunk_sizes)),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
