from __future__ import annotations

import pytest

from agent_evals.adapters.openai_semantic_judge import (
    _canonical_json,
    _strict_json_object,
    openai_semantic_judge_profile,
)


def test_openai_semantic_judge_profile_is_content_addressed_by_behavior_material() -> None:
    first = openai_semantic_judge_profile(
        model_name="scripted-judge",
        model_revision="openai-agents-0.22.0",
    )
    same = openai_semantic_judge_profile(
        model_name="scripted-judge",
        model_revision="openai-agents-0.22.0",
    )
    changed_model = openai_semantic_judge_profile(
        model_name="different-judge",
        model_revision="openai-agents-0.22.0",
    )
    changed_revision = openai_semantic_judge_profile(
        model_name="scripted-judge",
        model_revision="openai-agents-0.22.1",
    )

    assert first.identity == same.identity
    assert first.identity != changed_model.identity
    assert first.identity != changed_revision.identity
    assert first.adapter == "openai-agents-semantic-judge"
    assert first.adapter_version == "1"
    assert first.response_schema == "agent-evals/semantic-judge-response/v1"


def test_canonical_semantic_judge_json_is_stable_unicode_preserving_and_finite() -> None:
    assert _canonical_json({"z": 1, "a": "café"}) == '{"a":"café","z":1}'

    with pytest.raises(ValueError, match="Out of range float values"):
        _canonical_json({"score": float("nan")})


def test_strict_semantic_judge_json_accepts_exact_object_and_rejects_ambiguity() -> None:
    assert _strict_json_object('{"overall":"pass","criteria":[]}') == {
        "overall": "pass",
        "criteria": [],
    }

    with pytest.raises(ValueError, match="duplicate key 'overall'"):
        _strict_json_object('{"overall":"pass","overall":"fail"}')

    with pytest.raises(ValueError, match="non-finite number 'NaN'"):
        _strict_json_object('{"score":NaN}')

    with pytest.raises(ValueError, match="not valid JSON"):
        _strict_json_object('{"overall":')

    with pytest.raises(ValueError, match="must be one JSON object"):
        _strict_json_object('[{"overall":"pass"}]')
