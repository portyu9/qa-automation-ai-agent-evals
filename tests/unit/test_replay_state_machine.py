from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Literal

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.replay import EvidenceReplayAdapter, ReplayIdentityError
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.evidence.store import LocalEvidenceStore
from agent_evals.runtime.evaluator import TrialRunner

ReplayMode = Literal["clean", "evaluation_error", "runtime_error"]
ReplaySource = Literal["direct", "store"]

_MODES: tuple[ReplayMode, ...] = ("clean", "evaluation_error", "runtime_error")
_SOURCES: tuple[ReplaySource, ...] = ("direct", "store")


def _subject(*, model: str = "recorded") -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="replay-state-machine",
        model=model,
        application_revision="rev-1",
        instructions="Return the recorded state without re-executing anything.",
        tool_schema={},
        policy={},
        memory_policy={"retention": "trial"},
        adapter="recorded",
        adapter_version="1",
    )


def _scenario(*, revision: str = "1") -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="replay.state-machine",
        revision=revision,
        kind=ScenarioKind.REGRESSION,
        objective="Regrade one immutable recorded observation.",
        required_outcomes={"status": "ok"},
    )


def _blocking_event(kind: EvidenceKind) -> EvidenceEvent:
    if kind is EvidenceKind.EVALUATION_ERROR:
        return EvidenceEvent(
            sequence=0,
            kind=kind,
            source="evaluator:recorded-precondition",
            payload={
                "code": "recorded_precondition_failed",
                "reason": "required evaluator evidence was unavailable",
            },
            critical=True,
        )
    if kind is EvidenceKind.RUNTIME_ERROR:
        return EvidenceEvent(
            sequence=0,
            kind=kind,
            source="adapter:recorded-runtime",
            payload={"exception_type": "RecordedRuntimeError", "detail_retained": False},
            critical=True,
        )
    raise AssertionError(f"unsupported blocking evidence kind: {kind}")


def _recorded_evidence(mode: ReplayMode) -> TrialEvidence:
    if mode == "clean":
        events: tuple[EvidenceEvent, ...] = ()
    elif mode == "evaluation_error":
        events = (_blocking_event(EvidenceKind.EVALUATION_ERROR),)
    else:
        events = (_blocking_event(EvidenceKind.RUNTIME_ERROR),)

    return TrialEvidence(
        trial_id=f"replay-state-machine:{mode}",
        subject_identity=_subject().identity,
        scenario_identity=_scenario().identity,
        events=events,
        final_state={"status": "ok", "mode": mode},
        final_output="Recorded terminal observation",
        elapsed_ms=12.5,
        input_tokens=17,
        output_tokens=5,
        estimated_cost_usd=0.001,
    )


class ReplayIdentityStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self._temporary = tempfile.TemporaryDirectory()
        self.store = LocalEvidenceStore(Path(self._temporary.name) / "evidence")
        self.recorded: dict[ReplayMode, TrialEvidence] = {
            mode: _recorded_evidence(mode) for mode in _MODES
        }
        self.record_keys: dict[ReplayMode, str] = {
            mode: self.store.write(evidence).record_key for mode, evidence in self.recorded.items()
        }
        self.mode: ReplayMode = "clean"
        self.source: ReplaySource = "direct"
        self.trial_matches = True
        self.subject_matches = True
        self.scenario_matches = True

    def teardown(self) -> None:
        self._temporary.cleanup()

    @rule(mode=st.sampled_from(_MODES))
    def select_recorded_mode(self, mode: ReplayMode) -> None:
        self.mode = mode

    @rule(source=st.sampled_from(_SOURCES))
    def select_replay_source(self, source: ReplaySource) -> None:
        self.source = source

    @rule()
    def drift_trial_identity(self) -> None:
        self.trial_matches = False

    @rule()
    def restore_trial_identity(self) -> None:
        self.trial_matches = True

    @rule()
    def drift_subject_identity(self) -> None:
        self.subject_matches = False

    @rule()
    def restore_subject_identity(self) -> None:
        self.subject_matches = True

    @rule()
    def drift_scenario_identity(self) -> None:
        self.scenario_matches = False

    @rule()
    def restore_scenario_identity(self) -> None:
        self.scenario_matches = True

    @rule()
    def probe_runner_mapping(self) -> None:
        evidence = self._current_evidence()
        evaluated = asyncio.run(
            TrialRunner().run(
                self._adapter(),
                subject=self._call_subject(),
                scenario=self._call_scenario(),
                trial_id=self._call_trial_id(),
            )
        )

        if not self._identities_match():
            assert evaluated.verdict is TrialVerdict.BLOCKED
            assert evaluated.oracle_results == ()
            assert len(evaluated.evidence.events) == 1
            error = evaluated.evidence.events[0]
            assert error.kind is EvidenceKind.EVALUATION_ERROR
            assert error.critical is True
            assert error.payload["code"] == "replay_identity_mismatch"
            return

        assert evaluated.evidence == evidence
        assert evaluated.evidence.evidence_root == evidence.evidence_root
        assert evaluated.completion_evidence_root == evidence.evidence_root
        if self.mode == "clean":
            assert evaluated.verdict is TrialVerdict.PASS
        else:
            assert evaluated.verdict is TrialVerdict.BLOCKED
            assert evaluated.oracle_results == ()

    @rule()
    def probe_adapter_snapshot_isolation(self) -> None:
        source = _recorded_evidence("clean")
        expected_root = source.evidence_root
        adapter = EvidenceReplayAdapter(source)
        source.final_state["status"] = "tampered-after-adapter-construction"

        result = asyncio.run(
            adapter.execute(
                subject=_subject(),
                scenario=_scenario(),
                trial_id="replay-state-machine:clean",
            )
        )

        assert result.final_state == {"status": "ok", "mode": "clean"}
        replayed = TrialEvidence(
            trial_id="replay-state-machine:clean",
            subject_identity=_subject().identity,
            scenario_identity=_scenario().identity,
            events=result.events,
            final_state=result.final_state,
            final_output=result.final_output,
            elapsed_ms=result.elapsed_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
        )
        assert replayed.evidence_root == expected_root

    @invariant()
    def adapter_replay_tracks_current_identity_state_without_cached_authority(self) -> None:
        evidence = self._current_evidence()
        adapter = self._adapter()

        if not self._identities_match():
            with pytest.raises(ReplayIdentityError):
                asyncio.run(
                    adapter.execute(
                        subject=self._call_subject(),
                        scenario=self._call_scenario(),
                        trial_id=self._call_trial_id(),
                    )
                )
            return

        result = asyncio.run(
            adapter.execute(
                subject=self._call_subject(),
                scenario=self._call_scenario(),
                trial_id=self._call_trial_id(),
            )
        )
        self._assert_exact_adapter_result(result, evidence)

    def _current_evidence(self) -> TrialEvidence:
        return self.recorded[self.mode]

    def _adapter(self) -> EvidenceReplayAdapter:
        if self.source == "direct":
            return EvidenceReplayAdapter(self._current_evidence())
        return EvidenceReplayAdapter.from_store(self.store, self.record_keys[self.mode])

    def _call_trial_id(self) -> str:
        trial_id = self._current_evidence().trial_id
        return trial_id if self.trial_matches else f"{trial_id}:drifted"

    def _call_subject(self) -> SubjectFingerprint:
        return _subject() if self.subject_matches else _subject(model="drifted")

    def _call_scenario(self) -> EvaluationScenario:
        return _scenario() if self.scenario_matches else _scenario(revision="drifted")

    def _identities_match(self) -> bool:
        return self.trial_matches and self.subject_matches and self.scenario_matches

    @staticmethod
    def _assert_exact_adapter_result(result: AdapterResult, evidence: TrialEvidence) -> None:
        assert result.events == evidence.events
        assert result.final_state == evidence.final_state
        assert result.final_output == evidence.final_output
        assert result.elapsed_ms == evidence.elapsed_ms
        assert result.input_tokens == evidence.input_tokens
        assert result.output_tokens == evidence.output_tokens
        assert result.estimated_cost_usd == evidence.estimated_cost_usd


TestReplayIdentityStateMachine = ReplayIdentityStateMachine.TestCase
TestReplayIdentityStateMachine.settings = settings(
    max_examples=60,
    stateful_step_count=20,
    deadline=None,
)
