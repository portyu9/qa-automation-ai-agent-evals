from __future__ import annotations

from pathlib import Path

import pytest

from agent_evals.adapters.replay import EvidenceReplayAdapter, ReplayIdentityError
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.evidence.store import LocalEvidenceStore
from agent_evals.mcp.agent_bridge import MCPAgentToolResultReceipt
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec
from agent_evals.runtime.evaluator import TrialRunner


def subject(*, model: str = "recorded") -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="replay-test",
        model=model,
        application_revision="rev-1",
        instructions="Return the expected state.",
        tool_schema={},
        policy={},
        memory_policy={"retention": "none"},
        adapter="recorded",
        adapter_version="1",
    )


def scenario(*, revision: str = "1") -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="replay.outcome",
        revision=revision,
        kind=ScenarioKind.REGRESSION,
        objective="Verify the recorded outcome.",
        required_outcomes={"status": "ok"},
    )


def recorded_evidence() -> TrialEvidence:
    return TrialEvidence(
        trial_id="original-trial",
        subject_identity=subject().identity,
        scenario_identity=scenario().identity,
        final_state={"status": "ok"},
        final_output="Recorded success",
    )


def malformed_protocol_delivery_evidence() -> TrialEvidence:
    controlled_scenario = scenario()
    fault = MCPFaultSpec.from_payload(
        fault_id="replay-protocol-result",
        revision="1",
        kind=MCPFaultKind.TOOL_RESULT_POISON,
        tool_name="lookup_customer",
        payload={"value": "controlled"},
    )
    protocol = MCPFaultReceipt.create(
        fault=fault,
        protocol_version="2026-07-28",
        injection_point=("mcp:2026-07-28:tools/call:lookup_customer:result.content[0].text"),
        observed_text=fault.payload_json,
    )
    bridge = MCPAgentToolResultReceipt.create(
        scenario_identity=controlled_scenario.identity,
        protocol_receipt=protocol,
        agent_tool_name="lookup_customer",
        agent_call_id="call_replay",
        agent_output={"type": "text", "text": fault.payload_json},
    )
    payload = bridge.model_dump(mode="json")
    payload["receipt_root"] = "0" * 64
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.PROTOCOL_DELIVERY,
        source="bridge:mcp-agent:tool-result",
        payload=payload,
    )
    return TrialEvidence(
        trial_id="original-trial",
        subject_identity=subject().identity,
        scenario_identity=controlled_scenario.identity,
        events=(event,),
        final_state={"status": "ok"},
        final_output="Recorded success",
    )


@pytest.mark.asyncio
async def test_replay_regrades_recorded_state_with_exact_evidence_identity(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    original = recorded_evidence()
    manifest = store.write(original)
    adapter = EvidenceReplayAdapter.from_store(store, manifest.record_key)

    replayed = await TrialRunner().run(
        adapter,
        subject=subject(),
        scenario=scenario(),
        trial_id=original.trial_id,
    )

    assert replayed.verdict is TrialVerdict.PASS
    assert replayed.evidence == original
    assert replayed.evidence.evidence_root == original.evidence_root


@pytest.mark.asyncio
async def test_replay_refuses_trial_subject_or_scenario_identity_drift() -> None:
    adapter = EvidenceReplayAdapter(recorded_evidence())

    with pytest.raises(ReplayIdentityError, match="trial identity"):
        await adapter.execute(
            subject=subject(),
            scenario=scenario(),
            trial_id="different-trial",
        )
    with pytest.raises(ReplayIdentityError, match="subject identity"):
        await adapter.execute(
            subject=subject(model="different"),
            scenario=scenario(),
            trial_id="original-trial",
        )
    with pytest.raises(ReplayIdentityError, match="scenario identity"):
        await adapter.execute(
            subject=subject(),
            scenario=scenario(revision="2"),
            trial_id="original-trial",
        )


@pytest.mark.asyncio
async def test_replay_identity_drift_is_evaluation_error_not_runtime_failure() -> None:
    result = await TrialRunner().run(
        EvidenceReplayAdapter(recorded_evidence()),
        subject=subject(model="different"),
        scenario=scenario(),
        trial_id="original-trial",
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert len(result.evidence.events) == 1
    event = result.evidence.events[0]
    assert event.kind is EvidenceKind.EVALUATION_ERROR
    assert event.critical is True
    assert event.payload["code"] == "replay_identity_mismatch"
    assert "subject identity" in event.payload["reason"]


@pytest.mark.asyncio
async def test_replay_revalidates_protocol_delivery_before_regrading() -> None:
    original = malformed_protocol_delivery_evidence()

    replayed = await TrialRunner().run(
        EvidenceReplayAdapter(original),
        subject=subject(),
        scenario=scenario(),
        trial_id=original.trial_id,
    )

    assert replayed.verdict is TrialVerdict.BLOCKED
    assert replayed.oracle_results == ()
    assert replayed.evidence.events[0] == original.events[0]
    error = replayed.evidence.events[-1]
    assert error.kind is EvidenceKind.EVALUATION_ERROR
    assert error.source == "evaluator:protocol-delivery"
    assert error.payload["code"] == "protocol_delivery_unverified"
    assert "malformed or internally inconsistent" in error.payload["reason"]
