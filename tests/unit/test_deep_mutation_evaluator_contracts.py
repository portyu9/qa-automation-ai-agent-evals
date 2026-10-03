from __future__ import annotations

import asyncio
from typing import cast

import pytest

import agent_evals.runtime._evaluator_core as evaluator_core
from agent_evals.adapters.base import AdapterResult, AgentAdapter
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime._evaluator_core import EvaluatedTrial, TrialRunner
from agent_evals.semantic.receipt import SemanticJudgmentReceipt


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="scripted",
        model="deterministic",
        application_revision="mutation-wrapper",
        instructions="Exercise the evaluator wrapper only.",
        tool_schema={},
        policy={},
        memory_policy={"retention": "trial"},
        adapter="scripted",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="mutation.evaluator-wrapper",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Preserve exact TrialRunner.run forwarding and timing semantics.",
        authority=AuthorityPolicy(),
    )


def _adapter() -> AgentAdapter:
    return ScriptedAdapter(lambda *_: pytest.fail("wrapper test must not execute the adapter"))


def _inner_result(subject: SubjectFingerprint, scenario: EvaluationScenario) -> EvaluatedTrial:
    evidence = TrialEvidence(
        trial_id="inner-trial",
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
    )
    oracle = OracleResult(
        name="wrapper-probe",
        verdict=TrialVerdict.FAIL,
        reasons=("probe",),
        critical=True,
    )
    semantic = cast(SemanticJudgmentReceipt, object())
    return EvaluatedTrial(
        evidence=evidence,
        oracle_results=(oracle,),
        verdict=TrialVerdict.FAIL,
        semantic_judgment=semantic,
        evaluator_elapsed_ms=7.0,
    )


def test_run_forwards_exact_inputs_and_rewraps_exact_inner_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    adapter = _adapter()
    inner = _inner_result(subject, scenario)
    observed: list[tuple[AgentAdapter, SubjectFingerprint, EvaluationScenario, str, float]] = []

    async def fake_run_trial(
        self: TrialRunner,
        adapter_arg: AgentAdapter,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
        started: float,
    ) -> EvaluatedTrial:
        assert isinstance(self, TrialRunner)
        observed.append((adapter_arg, subject, scenario, trial_id, started))
        return inner

    times = iter((10.0, 10.25))
    monkeypatch.setattr(evaluator_core, "perf_counter", lambda: next(times))
    monkeypatch.setattr(TrialRunner, "_run_trial", fake_run_trial)

    result = asyncio.run(
        TrialRunner().run(
            adapter,
            subject=subject,
            scenario=scenario,
            trial_id="outer-trial",
        )
    )

    assert observed == [(adapter, subject, scenario, "outer-trial", 10.0)]
    assert result.evidence is inner.evidence
    assert result.oracle_results is inner.oracle_results
    assert result.verdict is inner.verdict
    assert result.semantic_judgment is inner.semantic_judgment
    assert result.evaluator_elapsed_ms == 250.0
    assert result.completion_evidence_root == inner.evidence.evidence_root


def test_run_clamps_negative_observed_elapsed_time_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    adapter = _adapter()
    inner = _inner_result(subject, scenario)

    async def fake_run_trial(
        self: TrialRunner,
        adapter_arg: AgentAdapter,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
        started: float,
    ) -> EvaluatedTrial:
        assert isinstance(self, TrialRunner)
        assert adapter_arg is adapter
        assert subject.identity == inner.evidence.subject_identity
        assert scenario.identity == inner.evidence.scenario_identity
        assert trial_id == "negative-clock"
        assert started == 20.0
        return inner

    times = iter((20.0, 19.0))
    monkeypatch.setattr(evaluator_core, "perf_counter", lambda: next(times))
    monkeypatch.setattr(TrialRunner, "_run_trial", fake_run_trial)

    result = asyncio.run(
        TrialRunner().run(
            adapter,
            subject=subject,
            scenario=scenario,
            trial_id="negative-clock",
        )
    )

    assert result.evaluator_elapsed_ms == 0.0


class _PassingAdapter:
    @property
    def name(self) -> str:
        return "mutation-passing"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        assert subject.identity
        assert scenario.identity
        assert trial_id
        return AdapterResult(final_state={}, final_output="ok")


@pytest.mark.parametrize("expire_on", range(1, 8))
def test_run_trial_deadline_checkpoints_preserve_exact_context(
    expire_on: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    started = 100.0
    calls = {"expired": 0, "blocked": 0}

    def fake_deadline_expired(self: TrialRunner, observed_started: float) -> bool:
        assert isinstance(self, TrialRunner)
        assert observed_started == started
        calls["expired"] += 1
        return calls["expired"] == expire_on

    def fake_deadline_blocked(
        self: TrialRunner,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
        started: float,
        evidence: TrialEvidence | None = None,
    ) -> EvaluatedTrial:
        assert isinstance(self, TrialRunner)
        assert subject.identity == _subject().identity
        assert scenario.identity == _scenario().identity
        assert trial_id == "phase-deadline"
        assert started == 100.0
        if expire_on == 1:
            assert evidence is None
        else:
            assert evidence is not None
            assert evidence.trial_id == "phase-deadline"
            assert evidence.subject_identity == subject.identity
            assert evidence.scenario_identity == scenario.identity
        calls["blocked"] += 1
        blocked_evidence = evidence or TrialEvidence(
            trial_id=trial_id,
            subject_identity=subject.identity,
            scenario_identity=scenario.identity,
        )
        return EvaluatedTrial(
            evidence=blocked_evidence,
            oracle_results=(),
            verdict=TrialVerdict.BLOCKED,
        )

    monkeypatch.setattr(TrialRunner, "_deadline_expired", fake_deadline_expired)
    monkeypatch.setattr(TrialRunner, "_deadline_blocked", fake_deadline_blocked)

    result = asyncio.run(
        TrialRunner()._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="phase-deadline",
            started=started,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert calls == {"expired": expire_on, "blocked": 1}


def test_evaluated_trial_elapsed_diagnostics_are_exact() -> None:
    evidence = TrialEvidence(
        trial_id="elapsed-contract",
        subject_identity=_subject().identity,
        scenario_identity=_scenario().identity,
    )

    with pytest.raises(TypeError) as captured:
        EvaluatedTrial(
            evidence=evidence,
            oracle_results=(),
            verdict=TrialVerdict.PASS,
            evaluator_elapsed_ms=True,
        )
    assert str(captured.value) == (
        "evaluator_elapsed_ms must be a finite non-negative number or None"
    )

    with pytest.raises(ValueError) as captured:
        EvaluatedTrial(
            evidence=evidence,
            oracle_results=(),
            verdict=TrialVerdict.PASS,
            evaluator_elapsed_ms=-1.0,
        )
    assert str(captured.value) == "evaluator_elapsed_ms must be a finite non-negative number"


def test_deadline_configuration_and_remaining_time_diagnostics_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(TypeError) as captured:
        TrialRunner(deadline_seconds=True)
    assert str(captured.value) == "deadline_seconds must be a finite positive number or None"

    with pytest.raises(ValueError) as captured:
        TrialRunner(deadline_seconds=0.0)
    assert str(captured.value) == "deadline_seconds must be a finite positive number"

    runner = TrialRunner()
    with pytest.raises(RuntimeError) as captured:
        runner._remaining_deadline_seconds(10.0)
    assert str(captured.value) == "deadline remaining requested without configured deadline"

    runner = TrialRunner(deadline_seconds=5.0)
    monkeypatch.setattr(evaluator_core, "perf_counter", lambda: 12.5)
    assert runner._remaining_deadline_seconds(10.0) == 2.5


def test_deadline_blocked_preserves_evidence_and_exact_error_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    original = TrialEvidence(
        trial_id="deadline-preserve",
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.STATE,
                source="environment",
                payload={"status": "observed"},
            ),
        ),
        final_state={"status": "ok"},
        final_output="done",
        elapsed_ms=9.0,
        input_tokens=7,
        output_tokens=3,
        estimated_cost_usd=0.01,
    )
    monkeypatch.setattr(evaluator_core, "perf_counter", lambda: 10.25)

    result = TrialRunner(deadline_seconds=1.0)._deadline_blocked(
        subject=subject,
        scenario=scenario,
        trial_id="deadline-preserve",
        started=10.0,
        evidence=original,
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert result.evidence.trial_id == original.trial_id
    assert result.evidence.subject_identity == original.subject_identity
    assert result.evidence.scenario_identity == original.scenario_identity
    assert result.evidence.final_state == original.final_state
    assert result.evidence.final_output == original.final_output
    assert result.evidence.elapsed_ms == 250.0
    assert result.evidence.input_tokens == 7
    assert result.evidence.output_tokens == 3
    assert result.evidence.estimated_cost_usd == 0.01
    event = result.evidence.events[-1]
    assert event.sequence == 1
    assert event.kind is EvidenceKind.EVALUATION_ERROR
    assert event.source == "evaluator:deadline"
    assert event.payload == {
        "code": "trial_deadline_exceeded",
        "reason": "evaluator wall-clock deadline exceeded",
        "deadline_seconds": 1.0,
    }
    assert event.critical is True


def test_evaluation_error_helpers_preserve_exact_fail_closed_contract() -> None:
    subject = _subject()
    scenario = _scenario()
    base = TrialEvidence(
        trial_id="helper-contract",
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
        final_state={"status": "ok"},
        final_output="done",
        elapsed_ms=12.5,
        input_tokens=2,
        output_tokens=4,
        estimated_cost_usd=0.02,
    )

    appended = TrialRunner._append_evaluation_error(
        base,
        source="evaluator:test",
        code="controlled_failure",
        reason="controlled reason",
    )
    assert appended.trial_id == base.trial_id
    assert appended.subject_identity == base.subject_identity
    assert appended.scenario_identity == base.scenario_identity
    assert appended.final_state == base.final_state
    assert appended.final_output == base.final_output
    assert appended.elapsed_ms == 12.5
    assert appended.input_tokens == 2
    assert appended.output_tokens == 4
    assert appended.estimated_cost_usd == 0.02
    assert appended.events[-1].model_dump(mode="json") == {
        "sequence": 0,
        "kind": EvidenceKind.EVALUATION_ERROR.value,
        "source": "evaluator:test",
        "payload": {"code": "controlled_failure", "reason": "controlled reason"},
        "critical": True,
    }

    adapter = _PassingAdapter()
    mutated = TrialRunner._scenario_contract_mutated(
        adapter=adapter,  # type: ignore[arg-type]
        subject=subject,
        scenario=scenario,
        trial_id="helper-contract",
        elapsed_ms=33.0,
    )
    assert mutated.verdict is TrialVerdict.BLOCKED
    assert mutated.oracle_results == ()
    assert mutated.evidence.elapsed_ms == 33.0
    assert mutated.evidence.events[0].source == "evaluator:adapter:mutation-passing"
    assert mutated.evidence.events[0].payload == {
        "code": "scenario_contract_mutated",
        "reason": (
            "adapter-facing scenario contract changed during execution; "
            "the evaluator retained the pre-execution contract"
        ),
    }
    assert mutated.evidence.events[0].critical is True

    invalid = TrialRunner._invalid_adapter_result(
        adapter=adapter,  # type: ignore[arg-type]
        subject=subject,
        scenario=scenario,
        trial_id="helper-contract",
        elapsed_ms=44.0,
    )
    assert invalid.verdict is TrialVerdict.BLOCKED
    assert invalid.oracle_results == ()
    assert invalid.evidence.elapsed_ms == 44.0
    assert invalid.evidence.events[0].source == "evaluator:adapter:mutation-passing"
    assert invalid.evidence.events[0].payload == {
        "code": "invalid_adapter_result",
        "reason": "adapter result failed normalized evidence validation",
    }
    assert invalid.evidence.events[0].critical is True


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (
            EvidenceKind.SEMANTIC_JUDGMENT,
            (
                "evaluator:semantic-judgment",
                "semantic_judgment_live_injection",
                (
                    "live adapter output cannot supply evaluator-owned semantic judgment "
                    "evidence; recorded semantic judgments are accepted only through the "
                    "exact evidence replay adapter"
                ),
            ),
        ),
        (
            EvidenceKind.ATTACK_DELIVERY,
            (
                "evaluator:attack-delivery",
                "attack_delivery_live_injection",
                (
                    "live adapter output cannot supply evaluator-owned attack-delivery "
                    "evidence; fresh adversarial delivery is accepted only from an exact "
                    "framework-controlled OpenAI injector adapter or through exact evidence "
                    "replay"
                ),
            ),
        ),
    ],
)
def test_live_evaluator_owned_evidence_violation_diagnostics_are_exact(
    kind: EvidenceKind,
    expected: tuple[str, str, str],
) -> None:
    evidence = TrialEvidence(
        trial_id="live-authority",
        subject_identity=_subject().identity,
        scenario_identity=_scenario().identity,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=kind,
                source="untrusted-live-adapter",
                payload={},
            ),
        ),
    )

    observed = TrialRunner._live_evaluator_owned_evidence_violation(
        _PassingAdapter(),  # type: ignore[arg-type]
        evidence,
    )
    assert observed == expected
