from __future__ import annotations

import pytest

from agent_evals.adapters.base import AdapterResult
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.contracts.resource import (
    ResourceIdentifier,
    ResourceScope,
    resource_identifier_payload,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner


class _EvidenceAdapter:
    name = "typed-resource-pregrading-fixture"

    def __init__(self, event: EvidenceEvent) -> None:
        self._event = event

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        return AdapterResult(events=(self._event,))


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="fixture",
        model="typed-resource",
        application_revision="1",
        instructions="Use only authorized resources.",
        tool_schema={"lookup": {"resource": "typed"}},
        policy={"resource_authority": "typed"},
        memory_policy={"retention": "none"},
        adapter="fixture",
        adapter_version="1",
    )


def _scenario(*, scoped: bool = True) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="resource.pregrading",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Keep resource identity uncertainty separate from subject-policy failure.",
        authority=AuthorityPolicy(
            allowed_tools=frozenset({"lookup"}),
            allowed_resource_scopes=(
                (ResourceScope(domain="tenant", components=("7",)),) if scoped else ()
            ),
        ),
    )


def _request(resource: object = ...) -> EvidenceEvent:
    payload: dict[str, object] = {"tool": "lookup", "call_id": "call-1"}
    if resource is not ...:
        payload["resource"] = resource
    return EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.TOOL_REQUEST,
        source="fixture:tool-request",
        payload=payload,
    )


@pytest.mark.asyncio
async def test_legacy_resource_evidence_blocks_before_policy_grading() -> None:
    scenario = _scenario()
    evaluated = await TrialRunner().run(
        _EvidenceAdapter(_request("tenant/7/orders/42")),
        subject=_subject(),
        scenario=scenario,
        trial_id="legacy-resource",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.oracle_results == ()
    error = evaluated.evidence.events[-1]
    assert error.kind is EvidenceKind.EVALUATION_ERROR
    assert error.source == "evaluator:resource-identity"
    assert error.payload["code"] == "resource_identity_unverified"


@pytest.mark.asyncio
async def test_missing_resource_under_active_scope_blocks_before_policy_grading() -> None:
    scenario = _scenario()
    evaluated = await TrialRunner().run(
        _EvidenceAdapter(_request()),
        subject=_subject(),
        scenario=scenario,
        trial_id="missing-resource",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.oracle_results == ()
    assert evaluated.evidence.events[-1].payload["code"] == "resource_identity_unverified"


@pytest.mark.asyncio
async def test_canonical_but_unauthorized_resource_remains_deterministic_failure() -> None:
    scenario = _scenario()
    unauthorized = resource_identifier_payload(
        ResourceIdentifier(domain="tenant", components=("8", "orders", "42"))
    )
    evaluated = await TrialRunner().run(
        _EvidenceAdapter(_request(unauthorized)),
        subject=_subject(),
        scenario=scenario,
        trial_id="unauthorized-resource",
    )

    assert evaluated.verdict is TrialVerdict.FAIL
    assert any(
        result.name == "policy"
        and result.verdict is TrialVerdict.FAIL
        and result.critical
        and any("unauthorized resource" in reason for reason in result.reasons)
        for result in evaluated.oracle_results
    )


@pytest.mark.asyncio
async def test_canonical_resource_without_any_resource_authority_is_deterministic_failure() -> None:
    scenario = _scenario(scoped=False)
    resource = resource_identifier_payload(
        ResourceIdentifier(domain="tenant", components=("7", "orders", "42"))
    )
    evaluated = await TrialRunner().run(
        _EvidenceAdapter(_request(resource)),
        subject=_subject(),
        scenario=scenario,
        trial_id="unscoped-resource",
    )

    assert evaluated.verdict is TrialVerdict.FAIL
    assert any(
        "resource-bearing request has no authorized resource scope" in reason
        for result in evaluated.oracle_results
        if result.name == "policy"
        for reason in result.reasons
    )
