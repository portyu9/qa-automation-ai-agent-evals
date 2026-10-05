"""Strict JSON decoding for trust-boundary material.

This module owns parser semantics that the evaluator must not inherit implicitly from a framework:
UTF-8 only, bounded structural nesting, duplicate-key rejection, bounded integer forms, finite
floating-point values, and Unicode scalar strings. Callers still own schema and domain validation.
"""

from __future__ import annotations

import json
import math
from typing import Any

from agent_evals.evidence.limits import MAX_JSON_INTEGER_DECIMAL_DIGITS

_DEFAULT_MAX_DEPTH = 64


class StrictJsonError(ValueError):
    """Untrusted JSON violated evaluator-owned decoding invariants."""


def strict_json_loads(
    value: bytes | str,
    *,
    label: str,
    require_object: bool = False,
    max_depth: int = _DEFAULT_MAX_DEPTH,
) -> Any:
    """Decode one JSON value using fail-closed evaluator-owned parser semantics."""
    if type(max_depth) is not int or max_depth < 1:
        raise ValueError("max_depth must be a positive exact integer")
    if type(value) is bytes:
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StrictJsonError(f"{label} must be valid UTF-8 JSON") from exc
    elif type(value) is str:
        text = value
    else:
        raise StrictJsonError(f"{label} must be exact bytes or text")

    _preflight_nesting(text, label=label, max_depth=max_depth)

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise StrictJsonError(f"{label} contains duplicate object key {key!r}")
            result[key] = item
        return result

    def reject_constant(token: str) -> object:
        raise StrictJsonError(f"{label} contains non-finite JSON number {token!r}")

    def parse_int(token: str) -> int:
        digits = token[1:] if token.startswith("-") else token
        if len(digits) > MAX_JSON_INTEGER_DECIMAL_DIGITS:
            raise StrictJsonError(
                f"{label} contains an integer exceeding maximum decimal digits "
                f"{MAX_JSON_INTEGER_DECIMAL_DIGITS}"
            )
        try:
            return int(token)
        except ValueError as exc:
            raise StrictJsonError(f"{label} contains an invalid integer") from exc

    def parse_float(token: str) -> float:
        try:
            number = float(token)
        except ValueError as exc:
            raise StrictJsonError(f"{label} contains an invalid floating-point number") from exc
        if not math.isfinite(number):
            raise StrictJsonError(f"{label} contains a non-finite floating-point number")
        return number

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
            parse_int=parse_int,
            parse_float=parse_float,
        )
    except StrictJsonError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise StrictJsonError(f"{label} must contain valid bounded JSON") from exc

    if require_object and type(parsed) is not dict:
        raise StrictJsonError(f"{label} JSON root must be an object")
    _require_unicode_scalars(parsed, label=label)
    return parsed


def _preflight_nesting(text: str, *, label: str, max_depth: int) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > max_depth:
                raise StrictJsonError(
                    f"{label} exceeds maximum JSON structural depth {max_depth}"
                )
        elif character in "]}":
            depth -= 1
            if depth < 0:
                raise StrictJsonError(f"{label} contains unbalanced JSON structure")


def _require_unicode_scalars(value: Any, *, label: str) -> None:
    stack = [value]
    while stack:
        current = stack.pop()
        if type(current) is str:
            _encode_scalar(current, label=label)
        elif type(current) is list:
            stack.extend(current)
        elif type(current) is dict:
            for key, item in current.items():
                _encode_scalar(key, label=label)
                stack.append(item)


def _encode_scalar(value: str, *, label: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise StrictJsonError(f"{label} contains a non-scalar Unicode string") from exc
