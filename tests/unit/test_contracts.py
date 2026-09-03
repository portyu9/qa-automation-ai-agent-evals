from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)


def fingerprint() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="example",
        model="model-a",
        application_revision="abc123",
        instructions="Be useful.",
        tool_schema={"tools": [{"name": "lookup"}]},
        policy={"allowed": ["lookup"]},
        memory_policy={"retention": "trial"},
        adapter="scripted",
        adapter_version="1",
    )


def test_subject_identity_is_content_addressed_and_stable() -> None:
    assert fingerprint().identity == fingerprint().identity
    changed = SubjectFingerprint.from_material(
        provider="example",
        model="model-b",
        application_revision="abc123",
        instructions="Be useful.",
        tool_schema={"tools": [{"name": "lookup"}]},
        policy={"allowed": ["lookup"]},
        memory_policy={"retention": "trial"},
        adapter="scripted",
        adapter_version="1",
    )
    assert fingerprint().identity != changed.identity


def test_scenario_identity_is_independent_of_set_and_prefix_input_order() -> None:
    first = EvaluationScenario(
        scenario_id="identity.case",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Check identity",
        authority=AuthorityPolicy(
            allowed_tools=frozenset({"b", "a"}),
            allowed_resource_prefixes=("tenant/8/", "tenant/7/"),
        ),
        tags=frozenset({"z", "a"}),
    )
    second = EvaluationScenario(
        scenario_id="identity.case",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Check identity",
        authority=AuthorityPolicy(
            allowed_tools=frozenset({"a", "b"}),
            allowed_resource_prefixes=("tenant/7/", "tenant/8/"),
        ),
        tags=frozenset({"a", "z"}),
    )
    assert first.identity == second.identity


def test_authority_policy_is_fail_closed() -> None:
    policy = AuthorityPolicy(
        allowed_tools=frozenset({"lookup"}),
        allowed_resource_prefixes=("tenant/7/",),
    )
    assert policy.authorizes_tool("lookup")
    assert not policy.authorizes_tool("delete")
    assert policy.authorizes_resource("tenant/7/orders")
    assert not policy.authorizes_resource("tenant/8/orders")


def test_empty_resource_prefix_is_rejected_instead_of_authorizing_everything() -> None:
    with pytest.raises(ValidationError):
        AuthorityPolicy(allowed_resource_prefixes=("",))


def test_approval_required_tool_must_be_allowed() -> None:
    with pytest.raises(ValidationError):
        AuthorityPolicy(approval_required_tools=frozenset({"refund"}))


def test_scenario_rejects_contradictory_outcome() -> None:
    with pytest.raises(ValidationError):
        EvaluationScenario(
            scenario_id="refund.case",
            revision="1",
            kind=ScenarioKind.SECURITY,
            objective="Process refund safely",
            required_outcomes={"refund.status": "created"},
            forbidden_outcomes={"refund.status": "created"},
        )
