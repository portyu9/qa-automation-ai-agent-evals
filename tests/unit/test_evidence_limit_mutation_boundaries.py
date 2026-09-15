from __future__ import annotations

import math

import pytest

from agent_evals.evidence.limits import (
    MAX_JSON_INTEGER_DECIMAL_DIGITS,
    JsonMaterialBudget,
    ResourceLimitError,
    validate_json_material,
)


def test_exit_marker_continues_to_remaining_siblings() -> None:
    value = ["abcdefgh", [None]]

    with pytest.raises(ResourceLimitError) as exc_info:
        validate_json_material(
            value,
            budget=JsonMaterialBudget(max_depth=2, max_nodes=4, max_utf8_bytes=4),
            label="fixture",
        )

    assert str(exc_info.value) == "fixture exceeds maximum UTF-8 material bytes 4"


def test_node_counter_accumulates_across_nested_containers() -> None:
    value = [[None]]

    with pytest.raises(ResourceLimitError) as exc_info:
        validate_json_material(
            value,
            budget=JsonMaterialBudget(max_depth=2, max_nodes=2, max_utf8_bytes=8),
            label="fixture",
        )

    assert str(exc_info.value) == "fixture exceeds maximum JSON node count 2"


def test_repeated_literal_accounting_is_cumulative() -> None:
    cases = (
        ([None, None], 8),
        ([False, False], 10),
        ([17, 17], 4),
        ([1.25, 1.25], 48),
    )
    for value, exact_bytes in cases:
        validate_json_material(
            value,
            budget=JsonMaterialBudget(max_depth=1, max_nodes=3, max_utf8_bytes=exact_bytes),
            label="fixture",
        )
        with pytest.raises(ResourceLimitError):
            validate_json_material(
                value,
                budget=JsonMaterialBudget(
                    max_depth=1,
                    max_nodes=3,
                    max_utf8_bytes=exact_bytes - 1,
                ),
                label="fixture",
            )


def test_json_string_precheck_accepts_exact_ascii_character_ceiling() -> None:
    validate_json_material(
        "abcd",
        budget=JsonMaterialBudget(max_depth=0, max_nodes=1, max_utf8_bytes=4),
        label="fixture",
    )


def test_json_string_precheck_reports_overlong_ascii_material() -> None:
    with pytest.raises(ResourceLimitError) as exc_info:
        validate_json_material(
            "abcde",
            budget=JsonMaterialBudget(max_depth=0, max_nodes=1, max_utf8_bytes=4),
            label="fixture",
        )

    assert str(exc_info.value) == "fixture exceeds maximum UTF-8 material bytes 4"


def test_integer_bit_guard_accepts_exact_bit_ceiling() -> None:
    exact_bits = math.ceil(MAX_JSON_INTEGER_DECIMAL_DIGITS * math.log2(10))
    value = 1 << (exact_bits - 1)
    assert value.bit_length() == exact_bits
    assert len(str(value)) == MAX_JSON_INTEGER_DECIMAL_DIGITS

    validate_json_material(
        value,
        budget=JsonMaterialBudget(
            max_depth=0,
            max_nodes=1,
            max_utf8_bytes=MAX_JSON_INTEGER_DECIMAL_DIGITS,
        ),
        label="fixture",
    )


def test_negative_integer_digit_ceiling_excludes_sign_but_bytes_include_it() -> None:
    value = -(10 ** (MAX_JSON_INTEGER_DECIMAL_DIGITS - 1))
    assert len(str(value)) == MAX_JSON_INTEGER_DECIMAL_DIGITS + 1

    validate_json_material(
        value,
        budget=JsonMaterialBudget(
            max_depth=0,
            max_nodes=1,
            max_utf8_bytes=MAX_JSON_INTEGER_DECIMAL_DIGITS + 1,
        ),
        label="fixture",
    )

    with pytest.raises(ResourceLimitError) as exc_info:
        validate_json_material(
            value,
            budget=JsonMaterialBudget(
                max_depth=0,
                max_nodes=1,
                max_utf8_bytes=MAX_JSON_INTEGER_DECIMAL_DIGITS,
            ),
            label="fixture",
        )

    assert str(exc_info.value) == (
        f"fixture exceeds maximum UTF-8 material bytes {MAX_JSON_INTEGER_DECIMAL_DIGITS}"
    )


def test_dictionary_cycle_preserves_cycle_diagnostic() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    with pytest.raises(ResourceLimitError) as exc_info:
        validate_json_material(
            cyclic,
            budget=JsonMaterialBudget(max_depth=2, max_nodes=4, max_utf8_bytes=16),
            label="fixture",
        )

    assert str(exc_info.value) == "fixture contains a reference cycle"


def test_dictionary_preflight_rejects_before_child_depth_check() -> None:
    value = {"a": None}

    with pytest.raises(ResourceLimitError) as exc_info:
        validate_json_material(
            value,
            budget=JsonMaterialBudget(max_depth=0, max_nodes=1, max_utf8_bytes=8),
            label="fixture",
        )

    assert str(exc_info.value) == "fixture exceeds maximum JSON node count 1"


def test_list_preflight_rejects_before_child_depth_check() -> None:
    value = [None]

    with pytest.raises(ResourceLimitError) as exc_info:
        validate_json_material(
            value,
            budget=JsonMaterialBudget(max_depth=0, max_nodes=1, max_utf8_bytes=8),
            label="fixture",
        )

    assert str(exc_info.value) == "fixture exceeds maximum JSON node count 1"


def test_object_key_precheck_accepts_exact_character_ceiling() -> None:
    validate_json_material(
        {"abcd": {}},
        budget=JsonMaterialBudget(max_depth=1, max_nodes=2, max_utf8_bytes=4),
        label="fixture",
    )


def test_object_key_precheck_reports_overlong_key() -> None:
    with pytest.raises(ResourceLimitError) as exc_info:
        validate_json_material(
            {"abcde": {}},
            budget=JsonMaterialBudget(max_depth=1, max_nodes=2, max_utf8_bytes=4),
            label="fixture",
        )

    assert str(exc_info.value) == "fixture exceeds maximum UTF-8 material bytes 4"


def test_object_key_bytes_accumulate_with_prior_scalar_material() -> None:
    value = [{"bb": {}}, "aa"]

    validate_json_material(
        value,
        budget=JsonMaterialBudget(max_depth=2, max_nodes=4, max_utf8_bytes=4),
        label="fixture",
    )

    with pytest.raises(ResourceLimitError) as exc_info:
        validate_json_material(
            value,
            budget=JsonMaterialBudget(max_depth=2, max_nodes=4, max_utf8_bytes=3),
            label="fixture",
        )

    assert str(exc_info.value) == "fixture exceeds maximum UTF-8 material bytes 3"
