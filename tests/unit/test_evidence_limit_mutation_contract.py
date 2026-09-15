from __future__ import annotations

import math

import pytest

from agent_evals.evidence.limits import (
    MAX_JSON_INTEGER_DECIMAL_DIGITS,
    JsonMaterialBudget,
    ResourceLimitError,
    validate_json_material,
    validate_utf8_text,
)


def _budget(*, nodes: int = 16, material_bytes: int = 64, depth: int = 8) -> JsonMaterialBudget:
    return JsonMaterialBudget(
        max_depth=depth,
        max_nodes=nodes,
        max_utf8_bytes=material_bytes,
    )


def test_walker_continues_after_container_exit_markers() -> None:
    value = [object(), [], []]

    with pytest.raises(
        ResourceLimitError,
        match=r"^fixture contains unsupported JSON value type object$",
    ):
        validate_json_material(value, budget=_budget(), label="fixture")


def test_zero_node_budget_rejects_before_value_accounting() -> None:
    with pytest.raises(
        ResourceLimitError,
        match=r"^fixture exceeds maximum JSON node count 0$",
    ):
        validate_json_material(None, budget=_budget(nodes=0), label="fixture")


def test_nested_nodes_are_counted_cumulatively() -> None:
    with pytest.raises(ResourceLimitError, match="maximum JSON node count 3"):
        validate_json_material(
            [[[None]]],
            budget=_budget(nodes=3, material_bytes=4),
            label="fixture",
        )


def test_null_and_true_use_exact_cumulative_material_accounting() -> None:
    value = [None, True]

    validate_json_material(value, budget=_budget(nodes=3, material_bytes=8), label="fixture")

    with pytest.raises(
        ResourceLimitError,
        match=r"^fixture exceeds maximum UTF-8 material bytes 7$",
    ):
        validate_json_material(value, budget=_budget(nodes=3, material_bytes=7), label="fixture")


def test_false_uses_exact_cumulative_material_accounting() -> None:
    validate_json_material(False, budget=_budget(nodes=1, material_bytes=5), label="fixture")
    validate_json_material(
        [False, False],
        budget=_budget(nodes=3, material_bytes=10),
        label="fixture",
    )

    with pytest.raises(
        ResourceLimitError,
        match=r"^fixture exceeds maximum UTF-8 material bytes 4$",
    ):
        validate_json_material(False, budget=_budget(nodes=1, material_bytes=4), label="fixture")

    with pytest.raises(
        ResourceLimitError,
        match=r"^fixture exceeds maximum UTF-8 material bytes 9$",
    ):
        validate_json_material(
            [False, False],
            budget=_budget(nodes=3, material_bytes=9),
            label="fixture",
        )


def test_string_character_fast_path_preserves_exact_byte_boundary() -> None:
    validate_json_material("abcd", budget=_budget(nodes=1, material_bytes=4), label="fixture")

    with pytest.raises(
        ResourceLimitError,
        match=r"^fixture exceeds maximum UTF-8 material bytes 4$",
    ):
        validate_json_material("abcde", budget=_budget(nodes=1, material_bytes=4), label="fixture")


def test_integer_bit_prefilter_accepts_public_decimal_digit_boundary() -> None:
    boundary_bits = math.ceil(MAX_JSON_INTEGER_DECIMAL_DIGITS * math.log2(10))
    value = 1 << (boundary_bits - 1)
    rendered = str(value)

    assert len(rendered) == MAX_JSON_INTEGER_DECIMAL_DIGITS
    validate_json_material(
        value,
        budget=_budget(nodes=1, material_bytes=len(rendered)),
        label="fixture",
    )


def test_negative_integer_preserves_sign_exclusion_at_digit_boundary() -> None:
    value = -(10 ** (MAX_JSON_INTEGER_DECIMAL_DIGITS - 1))
    rendered = str(value)

    assert len(rendered) == MAX_JSON_INTEGER_DECIMAL_DIGITS + 1
    validate_json_material(
        value,
        budget=_budget(nodes=1, material_bytes=len(rendered)),
        label="fixture",
    )


def test_integer_material_bytes_accumulate_across_siblings() -> None:
    value = [1, 1]

    validate_json_material(value, budget=_budget(nodes=3, material_bytes=2), label="fixture")

    with pytest.raises(
        ResourceLimitError,
        match=r"^fixture exceeds maximum UTF-8 material bytes 1$",
    ):
        validate_json_material(value, budget=_budget(nodes=3, material_bytes=1), label="fixture")


def test_float_finiteness_and_material_accounting_are_enforced() -> None:
    validate_json_material(1.25, budget=_budget(nodes=1, material_bytes=24), label="fixture")
    validate_json_material(
        [1.0, 2.0],
        budget=_budget(nodes=3, material_bytes=48),
        label="fixture",
    )

    for value in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(
            ResourceLimitError,
            match=r"^fixture contains a non-finite number$",
        ):
            validate_json_material(value, budget=_budget(nodes=1), label="fixture")

    with pytest.raises(
        ResourceLimitError,
        match=r"^fixture exceeds maximum UTF-8 material bytes 47$",
    ):
        validate_json_material(
            [1.0, 2.0],
            budget=_budget(nodes=3, material_bytes=47),
            label="fixture",
        )


def test_dict_cycle_reports_cycle_authority() -> None:
    value: dict[str, object] = {}
    value["self"] = value

    with pytest.raises(
        ResourceLimitError,
        match=r"^fixture contains a reference cycle$",
    ):
        validate_json_material(value, budget=_budget(), label="fixture")


def test_dict_width_guard_wins_before_child_validation() -> None:
    value = {"safe": None, "hostile": object()}

    with pytest.raises(ResourceLimitError, match="maximum JSON node count 2"):
        validate_json_material(
            value,
            budget=_budget(nodes=2, material_bytes=64),
            label="fixture",
        )


def test_list_width_guard_accepts_exact_capacity_and_wins_before_child_validation() -> None:
    validate_json_material(
        [None],
        budget=_budget(nodes=2, material_bytes=4),
        label="fixture",
    )

    with pytest.raises(ResourceLimitError, match="maximum JSON node count 2"):
        validate_json_material(
            [None, object()],
            budget=_budget(nodes=2, material_bytes=64),
            label="fixture",
        )


def test_object_key_length_and_cumulative_bytes_preserve_exact_boundaries() -> None:
    validate_json_material(
        {"abcd": []},
        budget=_budget(nodes=2, material_bytes=4),
        label="fixture",
    )
    validate_json_material(
        {"aa": [], "bb": []},
        budget=_budget(nodes=3, material_bytes=4),
        label="fixture",
    )

    with pytest.raises(
        ResourceLimitError,
        match=r"^fixture exceeds maximum UTF-8 material bytes 4$",
    ):
        validate_json_material(
            {"abcde": []},
            budget=_budget(nodes=2, material_bytes=4),
            label="fixture",
        )

    with pytest.raises(
        ResourceLimitError,
        match=r"^fixture exceeds maximum UTF-8 material bytes 3$",
    ):
        validate_json_material(
            {"aa": [], "bb": []},
            budget=_budget(nodes=3, material_bytes=3),
            label="fixture",
        )


def test_utf8_text_rejects_multibyte_overflow_even_when_character_count_fits() -> None:
    with pytest.raises(
        ResourceLimitError,
        match=r"^fixture exceeds maximum UTF-8 bytes 2$",
    ):
        validate_utf8_text("éé", max_bytes=2, label="fixture")
