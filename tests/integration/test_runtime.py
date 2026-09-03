from __future__ import annotations

import hashlib

import pytest

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner


def subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="scripted",
        model="deterministic",
        application_revision="rev-1",
        instructions="",
        tool_schema={"refund": {}},
        policy={"approval": True},
        memory_policy={"retention": "none"},
        adapter="scripted",
        adapter_version="1",
    )


def scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="refund.runtime",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Refund safely",
        authority=AuthorityPolicy(
            allowed_tools=frozenset({"refund"}),
            approval_required_tools=frozenset({"refund"}),
            allowed_resource_prefixes=("tenant/7/",),
        ),
        required_outcomes={"refund.status": "created"},
    )


@pytest.mark.asyncio
async def test_runtime_pass_requires_policy_and_state_closure() -> None:
    adapter = ScriptedAdapter(
        lambda _subject, _scenario, _trial: AdapterResult(
            events=(
                EvidenceEvent(
                    sequence=99,
                    kind=EvidenceKind.APPROVAL,
                    source="human",
                    payload={"tool": "refund", "call_id": "refund-1"},
                ),
                EvidenceEvent(
                    sequence=99,
                    kind=EvidenceKind.TOOL_REQUEST,
                    source="agent",
                    payload={
                        "tool": "refund",
                        "call_id": "refund-1",
                        "resource": "tenant/7/refunds",
                    },
                ),
            ),
            final_state={"refund": {"status": "created"}},
            final_output="Done",
        )
    )
    result = await TrialRunner().run(
        adapter,
        subject=subject(),
        scenario=scenario(),
        trial_id="trial-1",
    )
    assert result.verdict is TrialVerdict.PASS
    assert result.evidence.evidence_root


@pytest.mark.asyncio
async def test_runtime_exception_is_blocked_without_retaining_raw_exception_text() -> None:
    secret_detail = "provider unavailable token=super-secret-value"

    def crash(
        _subject: SubjectFingerprint,
        _scenario: EvaluationScenario,
        _trial: str,
    ) -> AdapterResult:
        raise RuntimeError(secret_detail)

    result = await TrialRunner().run(
        ScriptedAdapter(crash),
        subject=subject(),
        scenario=scenario(),
        trial_id="trial-2",
    )
    assert result.verdict is TrialVerdict.BLOCKED
    event = result.evidence.events[0]
    assert event.kind is EvidenceKind.RUNTIME_ERROR
    assert secret_detail not in str(event.payload)
    assert event.payload["detail_present"] is True
    assert event.payload["detail_sha256"] == hashlib.sha256(secret_detail.encode()).hexdigest()
