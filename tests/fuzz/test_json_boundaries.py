from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_evals._strict_json import StrictJsonError, strict_json_loads

pytestmark = pytest.mark.fuzz

_SAFE_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    max_size=80,
)
_JSON_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**120), max_value=10**120),
    st.floats(allow_nan=False, allow_infinity=False, width=64),
    _SAFE_TEXT,
)
_JSON_VALUES = st.recursive(
    _JSON_SCALARS,
    lambda children: st.one_of(
        st.lists(children, max_size=8),
        st.dictionaries(_SAFE_TEXT, children, max_size=8),
    ),
    max_leaves=40,
)


@given(payload=st.binary(max_size=4096))
@settings(max_examples=1200, deadline=None)
def test_arbitrary_bytes_never_escape_strict_json_contract(payload: bytes) -> None:
    try:
        decoded = strict_json_loads(payload, label="fuzz input")
    except StrictJsonError:
        return

    rendered = json.dumps(decoded, allow_nan=False, ensure_ascii=False)
    rendered.encode("utf-8")


@given(value=_JSON_VALUES)
@settings(max_examples=700, deadline=None)
def test_valid_finite_json_round_trips_under_strict_decoder(value: object) -> None:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    assert strict_json_loads(encoded, label="round trip") == value


@given(
    key=_SAFE_TEXT,
    left=_JSON_SCALARS,
    right=_JSON_SCALARS,
)
@settings(max_examples=500, deadline=None)
def test_duplicate_keys_are_always_rejected(
    key: str,
    left: object,
    right: object,
) -> None:
    payload = (
        "{"
        + json.dumps(key, ensure_ascii=False)
        + ":"
        + json.dumps(left, allow_nan=False, ensure_ascii=False)
        + ","
        + json.dumps(key, ensure_ascii=False)
        + ":"
        + json.dumps(right, allow_nan=False, ensure_ascii=False)
        + "}"
    )

    with pytest.raises(StrictJsonError, match="duplicate object key"):
        strict_json_loads(payload, label="duplicate fuzz", require_object=True)


@given(depth=st.integers(min_value=65, max_value=512))
@settings(max_examples=200, deadline=None)
def test_excessive_json_nesting_is_rejected_before_recursive_decode(depth: int) -> None:
    payload = "[" * depth + "0" + "]" * depth

    with pytest.raises(StrictJsonError, match="structural depth"):
        strict_json_loads(payload, label="nesting fuzz")


@given(exponent=st.integers(min_value=309, max_value=100_000))
@settings(max_examples=300, deadline=None)
def test_overflowing_numeric_forms_are_rejected(exponent: int) -> None:
    payload = f'{{"value":1e{exponent}}}'

    with pytest.raises(StrictJsonError, match="non-finite"):
        strict_json_loads(payload, label="numeric fuzz", require_object=True)
