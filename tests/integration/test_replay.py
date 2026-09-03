from __future__ import annotations

from pathlib import Path

import pytest

from agent_evals.adapters.replay import EvidenceReplayAdapter, ReplayIdentityError
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import TrialEvidence, TrialVerdict
from agent_evals.evidence.store import LocalEvidenceStore
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


@pytest.mark.asyncio
async def test_replay_regrades_recorded_state_without_reusing_original_trial_identity(
    tmp_path: Path,
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    original = recorded_evidence()
    manifest = store.write(original)
    adapter = EvidenceReplayAdapter.from_store(store, manifest.record_key)

    replayed = await TrialRunner().run(
        adapter,
        subject=subject(),
        scenario=scenario(),
        trial_id="replay-trial",
    )

    assert replayed.verdict is TrialVerdict.PASS
    assert replayed.evidence.final_state == original.final_state
    assert replayed.evidence.trial_id == "replay-trial"
    assert replayed.evidence.evidence_root != original.evidence_root


@pytest.mark.asyncio
async def test_replay_refuses_subject_or_scenario_identity_drift() -> None:
    adapter = EvidenceReplayAdapter(recorded_evidence())

    with pytest.raises(ReplayIdentityError, match="subject identity"):
        await adapter.execute(
            subject=subject(model="different"),
            scenario=scenario(),
            trial_id="replay",
        )
    with pytest.raises(ReplayIdentityError, match="scenario identity"):
        await adapter.execute(
            subject=subject(),
            scenario=scenario(revision="2"),
            trial_id="replay",
        )
