from __future__ import annotations

import json

import pytest

from agent_evals._strict_json import (
    MAX_JSON_INTEGER_DECIMAL_DIGITS,
    StrictJsonError,
    strict_json_loads,
)


def test_strict_json_accepts_valid_utf8_and_ignores_structure_inside_strings() -> None:
    payload = json.dumps(
        {"text": "snowman ☃ {[still text]}", "nested": {"value": 3}},
        ensure_ascii=False,
    ).encode()

    assert strict_json_loads(payload, label="test", require_object=True) == {
        "text": "snowman ☃ {[still text]}",
        "nested": {"value": 3},
    }


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":2}',
        b'{"outer":{"x":1,"x":2}}',
    ],
)
def test_strict_json_rejects_duplicate_keys(payload: bytes) -> None:
    with pytest.raises(StrictJsonError, match="duplicate object key"):
        strict_json_loads(payload, label="test", require_object=True)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":-Infinity}',
        b'{"value":1e9999}',
    ],
)
def test_strict_json_rejects_non_finite_numeric_forms(payload: bytes) -> None:
    with pytest.raises(StrictJsonError, match="non-finite"):
        strict_json_loads(payload, label="test", require_object=True)


def test_strict_json_rejects_invalid_utf8() -> None:
    with pytest.raises(StrictJsonError, match="UTF-8"):
        strict_json_loads(b'{"value":"\xff"}', label="test", require_object=True)


def test_strict_json_rejects_unpaired_unicode_surrogate() -> None:
    with pytest.raises(StrictJsonError, match="non-scalar Unicode"):
        strict_json_loads(r'{"value":"\ud800"}', label="test", require_object=True)


def test_strict_json_rejects_excessive_structural_depth_before_decode() -> None:
    payload = ("[" * 65 + "0" + "]" * 65).encode()
    with pytest.raises(StrictJsonError, match="structural depth 64"):
        strict_json_loads(payload, label="test")


def test_strict_json_rejects_extreme_integer_token() -> None:
    payload = '{"value":' + "9" * (MAX_JSON_INTEGER_DECIMAL_DIGITS + 1) + "}"
    with pytest.raises(StrictJsonError, match="maximum decimal digits"):
        strict_json_loads(payload, label="test", require_object=True)


def test_strict_json_can_require_object_root() -> None:
    with pytest.raises(StrictJsonError, match="root must be an object"):
        strict_json_loads("[1,2,3]", label="test", require_object=True)
