"""Fail-closed resource budgets for trust-critical JSON-compatible material.

The walker in this module is deliberately iterative. It rejects cycles, excessive nesting, too many
nodes, oversized UTF-8 scalar/key material, unsupported Python values, and non-finite floats before
callers hand the material to sorted JSON canonicalization or hashing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class JsonMaterialBudget:
    max_depth: int
    max_nodes: int
    max_utf8_bytes: int


EVENT_PAYLOAD_BUDGET = JsonMaterialBudget(
    max_depth=32,
    max_nodes=8_192,
    max_utf8_bytes=256 * 1024,
)
FINAL_STATE_BUDGET = JsonMaterialBudget(
    max_depth=32,
    max_nodes=32_768,
    max_utf8_bytes=1024 * 1024,
)
RECEIPT_MATERIAL_BUDGET = JsonMaterialBudget(
    max_depth=48,
    max_nodes=65_536,
    max_utf8_bytes=2 * 1024 * 1024,
)
MAX_TRIAL_EVENTS = 4_096
MAX_FINAL_OUTPUT_UTF8_BYTES = 1024 * 1024


class ResourceLimitError(ValueError):
    """Trust-critical material exceeded an evaluator resource ceiling."""


def validate_json_material(
    value: Any,
    *,
    budget: JsonMaterialBudget,
    label: str,
) -> None:
    """Validate JSON-compatible material without recursive descent or JSON serialization.

    ``max_utf8_bytes`` counts UTF-8 bytes in string values and object keys plus the bounded textual
    representation of JSON numeric/literal scalars. JSON punctuation/escaping overhead is not part
    of this pre-canonicalization budget; canonical output remains bounded indirectly by node count
    and the material-byte ceiling.
    """

    # Stack entries are (value, depth, exiting_container). Exit markers let us distinguish an
    # actual reference cycle from a harmless repeated alias that JSON would duplicate by value.
    stack: list[tuple[Any, int, bool]] = [(value, 0, False)]
    active_containers: set[int] = set()
    nodes = 0
    material_bytes = 0

    while stack:
        current, depth, exiting = stack.pop()
        if exiting:
            active_containers.remove(id(current))
            continue

        if depth > budget.max_depth:
            raise ResourceLimitError(
                f"{label} exceeds maximum JSON nesting depth {budget.max_depth}"
            )

        nodes += 1
        if nodes > budget.max_nodes:
            raise ResourceLimitError(f"{label} exceeds maximum JSON node count {budget.max_nodes}")

        if current is None or current is True:
            material_bytes += 4
        elif current is False:
            material_bytes += 5
        elif isinstance(current, str):
            if len(current) > budget.max_utf8_bytes:
                raise ResourceLimitError(
                    f"{label} exceeds maximum UTF-8 material bytes {budget.max_utf8_bytes}"
                )
            material_bytes += len(current.encode("utf-8"))
        elif isinstance(current, int) and not isinstance(current, bool):
            try:
                material_bytes += len(str(current))
            except ValueError as exc:
                raise ResourceLimitError(
                    f"{label} contains an integer too large to normalize"
                ) from exc
        elif isinstance(current, float):
            if not math.isfinite(current):
                raise ResourceLimitError(f"{label} contains a non-finite number")
            material_bytes += 24
        elif isinstance(current, dict):
            identity = id(current)
            if identity in active_containers:
                raise ResourceLimitError(f"{label} contains a reference cycle")
            if len(current) > budget.max_nodes - nodes:
                raise ResourceLimitError(
                    f"{label} exceeds maximum JSON node count {budget.max_nodes}"
                )
            active_containers.add(identity)
            stack.append((current, depth, True))
            for key, child in current.items():
                if not isinstance(key, str):
                    raise ResourceLimitError(f"{label} object keys must be strings")
                if len(key) > budget.max_utf8_bytes:
                    raise ResourceLimitError(
                        f"{label} exceeds maximum UTF-8 material bytes {budget.max_utf8_bytes}"
                    )
                material_bytes += len(key.encode("utf-8"))
                if material_bytes > budget.max_utf8_bytes:
                    raise ResourceLimitError(
                        f"{label} exceeds maximum UTF-8 material bytes {budget.max_utf8_bytes}"
                    )
                stack.append((child, depth + 1, False))
        elif isinstance(current, (list, tuple)):
            identity = id(current)
            if identity in active_containers:
                raise ResourceLimitError(f"{label} contains a reference cycle")
            if len(current) > budget.max_nodes - nodes:
                raise ResourceLimitError(
                    f"{label} exceeds maximum JSON node count {budget.max_nodes}"
                )
            active_containers.add(identity)
            stack.append((current, depth, True))
            for child in current:
                stack.append((child, depth + 1, False))
        else:
            raise ResourceLimitError(
                f"{label} contains unsupported JSON value type {type(current).__name__}"
            )

        if material_bytes > budget.max_utf8_bytes:
            raise ResourceLimitError(
                f"{label} exceeds maximum UTF-8 material bytes {budget.max_utf8_bytes}"
            )


def validate_utf8_text(value: str | None, *, max_bytes: int, label: str) -> None:
    if value is None:
        return
    if len(value) > max_bytes or len(value.encode("utf-8")) > max_bytes:
        raise ResourceLimitError(f"{label} exceeds maximum UTF-8 bytes {max_bytes}")
