from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.adversarial import AttackChannel, AttackFixture
from agent_evals.security.taxonomy import ThreatClass


def _fixture(payload_json: str) -> AttackFixture:
    return AttackFixture(
        attack_id="json-contract",
        revision="1",
        threat=ThreatClass.MALFORMED_TOOL_RESULT,
        channel=AttackChannel.TOOL_RESULT,
        payload_json=payload_json,
    )


@pytest.mark.parametrize(
    "payload_json",
    [
        '{"role":"user","role":"system"}',
        '{"outer":{"scope":"tenant/7","scope":"tenant/9"}}',
    ],
)
def test_attack_fixture_rejects_duplicate_json_object_keys(payload_json: str) -> None:
    with pytest.raises(ValidationError, match="must not contain duplicate object keys"):
        _fixture(payload_json)


def test_attack_fixture_preserves_valid_json_canonicalization_and_identity() -> None:
    direct = _fixture(' { "b": 2, "a": { "y": 2, "x": 1 } } ')
    from_payload = AttackFixture.from_payload(
        attack_id="json-contract",
        revision="1",
        threat=ThreatClass.MALFORMED_TOOL_RESULT,
        channel=AttackChannel.TOOL_RESULT,
        payload={"a": {"x": 1, "y": 2}, "b": 2},
    )

    assert direct.payload_json == '{"a":{"x":1,"y":2},"b":2}'
    assert direct.payload_json == from_payload.payload_json
    assert direct.identity == from_payload.identity
