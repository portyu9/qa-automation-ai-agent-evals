from __future__ import annotations

import asyncio
from typing import cast

import pytest

import agent_evals.runtime._evaluator_core as evaluator_core
from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult, AgentAdapter
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.contracts.semantic import SemanticCriterionSpec, SemanticRubricSpec
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime._evaluator_core import EvaluatedTrial, TrialRunner
from agent_evals.runtime.preconditions import EvaluationPreconditionError
from agent_evals.semantic.receipt import SemanticJudgmentReceipt
from agent_evals.semantic.verification import SemanticJudgmentError


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
    assert appended.events[-1].model_dump(mode="json", exclude={"observed_at"}) == {
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


def _semantic_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="mutation.evaluator-semantic",
        revision="1",
        kind=ScenarioKind.CAPABILITY,
        objective="Grade one semantic answer.",
        authority=AuthorityPolicy(),
        semantic_rubric=SemanticRubricSpec(
            rubric_id="mutation-evaluator",
            revision="1",
            criteria=(
                SemanticCriterionSpec(
                    criterion_id="grounded",
                    description="The answer remains grounded.",
                    minimum_score=3,
                ),
            ),
        ),
    )


class _PreconditionFailAdapter:
    @property
    def name(self) -> str:
        return "mutation-precondition"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        raise AdapterPreconditionError(
            code="controlled_precondition",
            reason="controlled adapter precondition",
        )


class _RuntimeFailAdapter:
    @property
    def name(self) -> str:
        return "mutation-runtime"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        raise LookupError("provider detail must not escape")


class _JudgeRuntimeFailure:
    async def judge(self, judge_input: object) -> object:
        del judge_input
        raise LookupError("judge detail must not escape")


class _JudgeUnexpectedResponse:
    async def judge(self, judge_input: object) -> object:
        del judge_input
        return object()


def _assert_single_blocking_error(
    result: EvaluatedTrial,
    *,
    source: str,
    code: str,
    reason: str,
) -> None:
    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    event = result.evidence.events[-1]
    assert event.kind is EvidenceKind.EVALUATION_ERROR
    assert event.source == source
    assert event.payload == {"code": code, "reason": reason}
    assert event.critical is True


@pytest.mark.parametrize(
    ("adapter", "kind", "source", "payload"),
    [
        (
            _PreconditionFailAdapter(),
            EvidenceKind.EVALUATION_ERROR,
            "adapter:mutation-precondition",
            {
                "code": "controlled_precondition",
                "reason": "controlled adapter precondition",
            },
        ),
        (
            _RuntimeFailAdapter(),
            EvidenceKind.RUNTIME_ERROR,
            "adapter:mutation-runtime",
            {
                "exception_type": "LookupError",
                "detail_retained": False,
            },
        ),
    ],
)
def test_adapter_failures_normalize_to_exact_blocked_evidence(
    adapter: object,
    kind: EvidenceKind,
    source: str,
    payload: dict[str, object],
) -> None:
    result = asyncio.run(
        TrialRunner()._run_trial(
            adapter,  # type: ignore[arg-type]
            subject=_subject(),
            scenario=_scenario(),
            trial_id="adapter-failure",
            started=0.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert len(result.evidence.events) == 1
    event = result.evidence.events[0]
    assert event.sequence == 0
    assert event.kind is kind
    assert event.source == source
    assert event.payload == payload
    assert event.critical is True


def test_blocking_adapter_evidence_short_circuits_grading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocking_event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.EVALUATION_ERROR,
        source="adapter:controlled",
        payload={"code": "blocked", "reason": "controlled"},
        critical=True,
    )

    class BlockingEvidenceAdapter(_PassingAdapter):
        async def execute(
            self,
            *,
            subject: SubjectFingerprint,
            scenario: EvaluationScenario,
            trial_id: str,
        ) -> AdapterResult:
            del subject, scenario, trial_id
            return AdapterResult(events=(blocking_event,), final_output="ignored")

    monkeypatch.setattr(
        evaluator_core,
        "grade_deterministic_evidence",
        lambda *_args, **_kwargs: pytest.fail("blocking evidence reached grading"),
    )
    result = asyncio.run(
        TrialRunner()._run_trial(
            BlockingEvidenceAdapter(),  # type: ignore[arg-type]
            subject=_subject(),
            scenario=_scenario(),
            trial_id="blocking-evidence",
            started=0.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert result.evidence.events == (blocking_event,)


def test_pregrading_failure_appends_exact_evaluator_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_pregrading(*_args: object, **_kwargs: object) -> None:
        raise EvaluationPreconditionError(
            source="evaluator:controlled-precondition",
            code="controlled_unverified",
            reason="controlled pregrading failure",
        )

    monkeypatch.setattr(evaluator_core, "verify_pregrading_closure", fail_pregrading)
    result = asyncio.run(
        TrialRunner()._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=_subject(),
            scenario=_scenario(),
            trial_id="pregrading-failure",
            started=0.0,
        )
    )

    _assert_single_blocking_error(
        result,
        source="evaluator:controlled-precondition",
        code="controlled_unverified",
        reason="controlled pregrading failure",
    )


def test_semantic_verification_failure_appends_exact_evaluator_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evaluator_core,
        "verify_semantic_judgment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SemanticJudgmentError("controlled recorded semantic failure")
        ),
    )
    result = asyncio.run(
        TrialRunner()._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=_subject(),
            scenario=_scenario(),
            trial_id="semantic-verification-failure",
            started=0.0,
        )
    )

    _assert_single_blocking_error(
        result,
        source="evaluator:semantic-judgment",
        code="semantic_judgment_unverified",
        reason="controlled recorded semantic failure",
    )


@pytest.mark.parametrize(
    ("final_output", "code", "reason"),
    [
        (
            "candidate",
            "semantic_judge_missing",
            "scenario requires semantic grading but no calibrated judge is configured",
        ),
        (
            None,
            "semantic_judge_missing",
            "scenario requires semantic grading but no calibrated judge is configured",
        ),
    ],
)
def test_semantic_missing_judge_is_exact_and_precedes_candidate_validation(
    final_output: str | None,
    code: str,
    reason: str,
) -> None:
    class SemanticAdapter(_PassingAdapter):
        async def execute(
            self,
            *,
            subject: SubjectFingerprint,
            scenario: EvaluationScenario,
            trial_id: str,
        ) -> AdapterResult:
            del subject, scenario, trial_id
            return AdapterResult(final_output=final_output)

    result = asyncio.run(
        TrialRunner()._run_trial(
            SemanticAdapter(),  # type: ignore[arg-type]
            subject=_subject(),
            scenario=_semantic_scenario(),
            trial_id="semantic-missing-judge",
            started=0.0,
        )
    )

    _assert_single_blocking_error(
        result,
        source="evaluator:semantic-judge",
        code=code,
        reason=reason,
    )


def test_semantic_candidate_missing_is_exact_when_judge_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judge = _JudgeUnexpectedResponse()
    runner = TrialRunner(semantic_judge=judge)  # type: ignore[arg-type]

    class NoOutputAdapter(_PassingAdapter):
        async def execute(
            self,
            *,
            subject: SubjectFingerprint,
            scenario: EvaluationScenario,
            trial_id: str,
        ) -> AdapterResult:
            del subject, scenario, trial_id
            return AdapterResult(final_output=None)

    # Candidate absence is checked before judge authority is consulted.
    monkeypatch.setattr(
        evaluator_core,
        "validate_semantic_judge_authority",
        lambda *_args, **_kwargs: pytest.fail("judge authority must not be consulted"),
    )
    result = asyncio.run(
        runner._run_trial(
            NoOutputAdapter(),  # type: ignore[arg-type]
            subject=_subject(),
            scenario=_semantic_scenario(),
            trial_id="semantic-candidate-missing",
            started=0.0,
        )
    )

    _assert_single_blocking_error(
        result,
        source="evaluator:semantic-judge",
        code="semantic_candidate_missing",
        reason="scenario requires semantic grading but the subject produced no final output",
    )


def test_semantic_judge_authority_failure_is_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = TrialRunner(semantic_judge=_JudgeUnexpectedResponse())  # type: ignore[arg-type]

    def fail_authority(*_args: object, **_kwargs: object) -> tuple[object, object]:
        raise LookupError("controlled authority failure")

    monkeypatch.setattr(evaluator_core, "validate_semantic_judge_authority", fail_authority)
    result = asyncio.run(
        runner._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=_subject(),
            scenario=_semantic_scenario(),
            trial_id="semantic-authority-failure",
            started=0.0,
        )
    )

    _assert_single_blocking_error(
        result,
        source="evaluator:semantic-judge",
        code="semantic_judge_uncalibrated",
        reason="semantic judge authority is unavailable: LookupError",
    )


@pytest.mark.parametrize(
    ("judge", "code", "reason"),
    [
        (
            _JudgeRuntimeFailure(),
            "semantic_judge_runtime_error",
            "semantic judge invocation failed: LookupError",
        ),
        (
            _JudgeUnexpectedResponse(),
            "semantic_judgment_invalid",
            "semantic judge returned an unexpected response type",
        ),
    ],
)
def test_semantic_judge_runtime_and_response_failures_are_exact(
    judge: object,
    code: str,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = TrialRunner(semantic_judge=judge)  # type: ignore[arg-type]
    monkeypatch.setattr(
        evaluator_core,
        "validate_semantic_judge_authority",
        lambda *_args, **_kwargs: (object(), object()),
    )
    result = asyncio.run(
        runner._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=_subject(),
            scenario=_semantic_scenario(),
            trial_id="semantic-judge-failure",
            started=0.0,
        )
    )

    _assert_single_blocking_error(
        result,
        source=(
            "evaluator:semantic-judge"
            if code == "semantic_judge_runtime_error"
            else "evaluator:semantic-judgment"
        ),
        code=code,
        reason=reason,
    )


def test_deterministic_failure_with_recorded_semantic_is_rejected_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = OracleResult(
        name="controlled-failure",
        verdict=TrialVerdict.FAIL,
        reasons=("controlled",),
        critical=True,
    )
    monkeypatch.setattr(
        evaluator_core,
        "grade_deterministic_evidence",
        lambda *_args, **_kwargs: (failed,),
    )
    monkeypatch.setattr(
        evaluator_core,
        "verify_semantic_judgment",
        lambda *_args, **_kwargs: cast(SemanticJudgmentReceipt, object()),
    )

    result = asyncio.run(
        TrialRunner()._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=_subject(),
            scenario=_scenario(),
            trial_id="impossible-semantic",
            started=0.0,
        )
    )

    _assert_single_blocking_error(
        result,
        source="evaluator:semantic-judgment",
        code="semantic_judgment_after_deterministic_failure",
        reason=(
            "recorded semantic judgment is impossible because deterministic "
            "grading already failed and must have short-circuited the judge"
        ),
    )


@pytest.mark.parametrize(
    ("kind", "source", "expected"),
    [
        (
            EvidenceKind.RETRIEVAL_DELIVERY,
            "evaluator-owned-retrieval",
            (
                "evaluator:retrieval-delivery",
                "retrieval_delivery_live_injection",
                (
                    "live adapter output cannot supply evaluator-owned retrieval-delivery "
                    "evidence; live retrieval delivery is accepted only from the exact "
                    "built-in retrieval adapter or through exact evidence replay"
                ),
            ),
        ),
        (
            EvidenceKind.APPROVAL_DECISION,
            "evaluator-owned-approval",
            (
                "evaluator:approval-intent",
                "approval_decision_live_injection",
                (
                    "live adapter output cannot supply framework-owned approval-decision "
                    "evidence; live approval decisions are accepted only from the exact "
                    "built-in HITL approval adapter or through exact evidence replay"
                ),
            ),
        ),
        (
            EvidenceKind.SIDE_EFFECT_OBSERVATION,
            "bridge:side-effect-idempotency",
            (
                "evaluator:side-effect-observer",
                "side_effect_observation_live_injection",
                (
                    "live adapter output cannot supply evaluator-owned side-effect observation "
                    "evidence; live physical-effect observations are accepted only from the "
                    "exact built-in side-effect observer or through exact evidence replay"
                ),
            ),
        ),
        (
            EvidenceKind.PROTOCOL_DELIVERY,
            "bridge:mcp-agent:tool-result",
            (
                "evaluator:protocol-delivery",
                "protocol_delivery_live_injection",
                (
                    "live adapter output cannot supply framework-owned MCP protocol delivery "
                    "source 'bridge:mcp-agent:tool-result'; fresh bridge evidence is accepted "
                    "only from its exact built-in bridge adapter or through exact evidence replay"
                ),
            ),
        ),
    ],
)
def test_live_producer_authority_violation_diagnostics_are_exact(
    kind: EvidenceKind,
    source: str,
    expected: tuple[str, str, str],
) -> None:
    evidence = TrialEvidence(
        trial_id="producer-authority",
        subject_identity=_subject().identity,
        scenario_identity=_scenario().identity,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=kind,
                source=source,
                payload={},
            ),
        ),
    )

    assert (
        TrialRunner._live_evaluator_owned_evidence_violation(
            _PassingAdapter(),  # type: ignore[arg-type]
            evidence,
        )
        == expected
    )


@pytest.mark.parametrize("adapter", [_PreconditionFailAdapter(), _RuntimeFailAdapter()])
def test_exception_deadline_checkpoint_preserves_exact_context(
    adapter: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    observed: list[tuple[str, str, str, float, TrialEvidence | None]] = []

    monkeypatch.setattr(TrialRunner, "_deadline_expired", lambda _self, started: started == 55.0)

    def blocked(
        self: TrialRunner,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
        started: float,
        evidence: TrialEvidence | None = None,
    ) -> EvaluatedTrial:
        assert isinstance(self, TrialRunner)
        observed.append((subject.identity, scenario.identity, trial_id, started, evidence))
        return EvaluatedTrial(
            evidence=TrialEvidence(
                trial_id=trial_id,
                subject_identity=subject.identity,
                scenario_identity=scenario.identity,
            ),
            oracle_results=(),
            verdict=TrialVerdict.BLOCKED,
        )

    monkeypatch.setattr(TrialRunner, "_deadline_blocked", blocked)
    result = asyncio.run(
        TrialRunner()._run_trial(
            adapter,  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="exception-deadline",
            started=55.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert observed == [
        (
            subject.identity,
            scenario.identity,
            "exception-deadline",
            55.0,
            None,
        )
    ]


@pytest.mark.parametrize("adapter", [_PreconditionFailAdapter(), _RuntimeFailAdapter()])
def test_exception_scenario_drift_preserves_exact_context(
    adapter: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    monkeypatch.setattr(TrialRunner, "_deadline_expired", lambda *_args: False)
    monkeypatch.setattr(TrialRunner, "_scenario_contract_drifted", lambda *_args: True)
    monkeypatch.setattr(evaluator_core, "perf_counter", lambda: 10.25)
    observed: list[tuple[object, str, str, str, float]] = []

    def mutated(
        *,
        adapter: AgentAdapter,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
        elapsed_ms: float,
    ) -> EvaluatedTrial:
        observed.append((adapter, subject.identity, scenario.identity, trial_id, elapsed_ms))
        return EvaluatedTrial(
            evidence=TrialEvidence(
                trial_id=trial_id,
                subject_identity=subject.identity,
                scenario_identity=scenario.identity,
            ),
            oracle_results=(),
            verdict=TrialVerdict.BLOCKED,
        )

    monkeypatch.setattr(TrialRunner, "_scenario_contract_mutated", staticmethod(mutated))
    result = asyncio.run(
        TrialRunner()._run_trial(
            adapter,  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="exception-drift",
            started=10.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert observed == [
        (
            adapter,
            subject.identity,
            scenario.identity,
            "exception-drift",
            250.0,
        )
    ]


def test_normal_scenario_drift_call_binding_is_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    adapter = _PassingAdapter()
    monkeypatch.setattr(TrialRunner, "_deadline_expired", lambda *_args: False)
    monkeypatch.setattr(TrialRunner, "_scenario_contract_drifted", lambda *_args: True)
    monkeypatch.setattr(evaluator_core, "perf_counter", lambda: 20.5)
    observed: list[tuple[object, str, str, str, float]] = []

    def mutated(
        *,
        adapter: AgentAdapter,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
        elapsed_ms: float,
    ) -> EvaluatedTrial:
        observed.append((adapter, subject.identity, scenario.identity, trial_id, elapsed_ms))
        return EvaluatedTrial(
            evidence=TrialEvidence(
                trial_id=trial_id,
                subject_identity=subject.identity,
                scenario_identity=scenario.identity,
            ),
            oracle_results=(),
            verdict=TrialVerdict.BLOCKED,
        )

    monkeypatch.setattr(TrialRunner, "_scenario_contract_mutated", staticmethod(mutated))
    result = asyncio.run(
        TrialRunner()._run_trial(
            adapter,  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="normal-drift",
            started=20.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert observed == [
        (
            adapter,
            subject.identity,
            scenario.identity,
            "normal-drift",
            500.0,
        )
    ]


def test_invalid_adapter_result_call_binding_is_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()

    class InvalidAdapter(_PassingAdapter):
        async def execute(
            self,
            *,
            subject: SubjectFingerprint,
            scenario: EvaluationScenario,
            trial_id: str,
        ) -> object:
            del subject, scenario, trial_id
            return object()

    monkeypatch.setattr(TrialRunner, "_deadline_expired", lambda *_args: False)
    monkeypatch.setattr(TrialRunner, "_scenario_contract_drifted", lambda *_args: False)
    monkeypatch.setattr(evaluator_core, "perf_counter", lambda: 30.125)
    observed: list[tuple[object, str, str, str, float]] = []

    def invalid(
        *,
        adapter: AgentAdapter,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
        elapsed_ms: float,
    ) -> EvaluatedTrial:
        observed.append((adapter, subject.identity, scenario.identity, trial_id, elapsed_ms))
        return EvaluatedTrial(
            evidence=TrialEvidence(
                trial_id=trial_id,
                subject_identity=subject.identity,
                scenario_identity=scenario.identity,
            ),
            oracle_results=(),
            verdict=TrialVerdict.BLOCKED,
        )

    monkeypatch.setattr(TrialRunner, "_invalid_adapter_result", staticmethod(invalid))
    adapter = InvalidAdapter()
    result = asyncio.run(
        TrialRunner()._run_trial(
            adapter,  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="invalid-result",
            started=30.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert observed == [
        (
            adapter,
            subject.identity,
            scenario.identity,
            "invalid-result",
            125.0,
        )
    ]


@pytest.mark.parametrize("expire_on", [8, 9])
def test_semantic_path_deadline_checkpoints_preserve_exact_context(
    expire_on: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _semantic_scenario()
    calls = {"expired": 0, "judge": 0, "blocked": 0}

    class Judge:
        async def judge(self, judge_input: object) -> object:
            assert judge_input is not None
            calls["judge"] += 1
            return object()

    def expired(self: TrialRunner, started: float) -> bool:
        assert isinstance(self, TrialRunner)
        assert started == 70.0
        calls["expired"] += 1
        return calls["expired"] == expire_on

    def blocked(
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
        assert scenario.identity == _semantic_scenario().identity
        assert trial_id == "semantic-deadline"
        assert started == 70.0
        assert evidence is not None
        calls["blocked"] += 1
        return EvaluatedTrial(
            evidence=evidence,
            oracle_results=(),
            verdict=TrialVerdict.BLOCKED,
        )

    monkeypatch.setattr(TrialRunner, "_deadline_expired", expired)
    monkeypatch.setattr(TrialRunner, "_deadline_blocked", blocked)
    monkeypatch.setattr(
        evaluator_core,
        "validate_semantic_judge_authority",
        lambda *_args, **_kwargs: (object(), object()),
    )

    result = asyncio.run(
        TrialRunner(semantic_judge=Judge())._run_trial(  # type: ignore[arg-type]
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="semantic-deadline",
            started=70.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert calls["expired"] == expire_on
    assert calls["blocked"] == 1
    assert calls["judge"] == (1 if expire_on == 9 else 0)


def test_exact_zero_remaining_deadline_expires_before_adapter_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NeverAdapter(_PassingAdapter):
        async def execute(
            self,
            *,
            subject: SubjectFingerprint,
            scenario: EvaluationScenario,
            trial_id: str,
        ) -> AdapterResult:
            del subject, scenario, trial_id
            raise AssertionError("zero remaining deadline executed adapter")

    runner = TrialRunner(deadline_seconds=1.0)
    monkeypatch.setattr(
        TrialRunner,
        "_remaining_deadline_seconds",
        lambda _self, started: 0.0 if started == 80.0 else pytest.fail("wrong start"),
    )

    result = asyncio.run(
        runner._run_trial(
            NeverAdapter(),  # type: ignore[arg-type]
            subject=_subject(),
            scenario=_scenario(),
            trial_id="zero-remaining",
            started=80.0,
        )
    )
    assert result.verdict is TrialVerdict.BLOCKED
    assert result.evidence.events[-1].payload["code"] == "trial_deadline_exceeded"


def test_deadline_expired_treats_exact_zero_as_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = TrialRunner(deadline_seconds=1.0)
    monkeypatch.setattr(
        TrialRunner,
        "_remaining_deadline_seconds",
        lambda _self, _started: 0.0,
    )
    assert runner._deadline_expired(90.0) is True


def test_cancel_late_task_registers_exact_result_consumer() -> None:
    class RecordingFuture:
        def __init__(self) -> None:
            self.cancelled = False
            self.callbacks: list[object] = []

        def cancel(self) -> None:
            self.cancelled = True

        def add_done_callback(self, callback: object) -> None:
            self.callbacks.append(callback)

    future = RecordingFuture()
    TrialRunner._cancel_late_task(future)  # type: ignore[arg-type]

    assert future.cancelled is True
    assert future.callbacks == [TrialRunner._consume_late_task_result]


def test_scenario_contract_drift_detection_is_exact() -> None:
    scenario = _scenario()
    assert TrialRunner._scenario_contract_drifted(scenario, scenario.identity) is False
    assert TrialRunner._scenario_contract_drifted(scenario, "0" * 64) is True
def _install_exact_deadline_probe(
    monkeypatch: pytest.MonkeyPatch,
    *,
    expire_on: int,
    expected_subject: SubjectFingerprint,
    expected_scenario: EvaluationScenario,
    expected_trial_id: str,
    expected_started: float,
    require_evidence: bool,
) -> dict[str, int]:
    calls = {"expired": 0, "blocked": 0}

    def expired(self: TrialRunner, started: float) -> bool:
        assert isinstance(self, TrialRunner)
        assert started == expected_started
        calls["expired"] += 1
        return calls["expired"] == expire_on

    def blocked(
        self: TrialRunner,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
        started: float,
        evidence: TrialEvidence | None = None,
    ) -> EvaluatedTrial:
        assert isinstance(self, TrialRunner)
        assert subject.identity == expected_subject.identity
        assert scenario.identity == expected_scenario.identity
        assert trial_id == expected_trial_id
        assert started == expected_started
        if require_evidence:
            assert evidence is not None
            assert evidence.trial_id == expected_trial_id
            assert evidence.subject_identity == expected_subject.identity
            assert evidence.scenario_identity == expected_scenario.identity
        else:
            assert evidence is None
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

    monkeypatch.setattr(TrialRunner, "_deadline_expired", expired)
    monkeypatch.setattr(TrialRunner, "_deadline_blocked", blocked)
    return calls


def test_configured_adapter_zero_remaining_binds_exact_block_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    executed = {"count": 0}
    observed = {"blocked": 0}

    class CountingAdapter(_PassingAdapter):
        async def execute(
            self,
            *,
            subject: SubjectFingerprint,
            scenario: EvaluationScenario,
            trial_id: str,
        ) -> AdapterResult:
            del subject, scenario, trial_id
            executed["count"] += 1
            return AdapterResult(final_output="unexpected")

    def blocked(
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
        assert trial_id == "adapter-zero-remaining"
        assert started == 81.0
        assert evidence is None
        observed["blocked"] += 1
        return EvaluatedTrial(
            evidence=TrialEvidence(
                trial_id=trial_id,
                subject_identity=subject.identity,
                scenario_identity=scenario.identity,
            ),
            oracle_results=(),
            verdict=TrialVerdict.BLOCKED,
        )

    runner = TrialRunner(deadline_seconds=1.0)
    monkeypatch.setattr(
        TrialRunner,
        "_remaining_deadline_seconds",
        lambda _self, started: 0.0
        if started == 81.0
        else pytest.fail("wrong deadline origin"),
    )
    monkeypatch.setattr(TrialRunner, "_deadline_blocked", blocked)

    result = asyncio.run(
        runner._run_trial(
            CountingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="adapter-zero-remaining",
            started=81.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert executed["count"] == 0
    assert observed["blocked"] == 1


def test_configured_adapter_wait_timeout_binds_wait_cancel_and_block_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    observed: dict[str, object] = {"waits": 0, "cancels": 0, "blocked": 0}
    task_holder: list[asyncio.Task[object]] = []

    async def fake_wait(
        awaitables: object,
        *,
        timeout: float,
    ) -> tuple[set[asyncio.Task[object]], set[asyncio.Task[object]]]:
        assert timeout == 0.5
        tasks = tuple(awaitables)  # type: ignore[arg-type]
        assert len(tasks) == 1
        task = tasks[0]
        assert isinstance(task, asyncio.Task)
        task_holder.append(task)
        observed["waits"] = int(observed["waits"]) + 1
        return set(), {task}

    def cancel(self: TrialRunner, task: asyncio.Task[object]) -> None:
        assert isinstance(self, TrialRunner)
        assert task_holder == [task]
        observed["cancels"] = int(observed["cancels"]) + 1
        task.cancel()

    def blocked(
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
        assert trial_id == "adapter-wait-timeout"
        assert started == 82.0
        assert evidence is None
        observed["blocked"] = int(observed["blocked"]) + 1
        return EvaluatedTrial(
            evidence=TrialEvidence(
                trial_id=trial_id,
                subject_identity=subject.identity,
                scenario_identity=scenario.identity,
            ),
            oracle_results=(),
            verdict=TrialVerdict.BLOCKED,
        )

    runner = TrialRunner(deadline_seconds=1.0)
    monkeypatch.setattr(
        TrialRunner,
        "_remaining_deadline_seconds",
        lambda _self, started: 0.5
        if started == 82.0
        else pytest.fail("wrong deadline origin"),
    )
    monkeypatch.setattr(evaluator_core.asyncio, "wait", fake_wait)
    monkeypatch.setattr(TrialRunner, "_cancel_late_task", cancel)
    monkeypatch.setattr(TrialRunner, "_deadline_blocked", blocked)

    result = asyncio.run(
        runner._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="adapter-wait-timeout",
            started=82.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert observed == {"waits": 1, "cancels": 1, "blocked": 1}


@pytest.mark.parametrize("adapter", [_PreconditionFailAdapter(), _RuntimeFailAdapter()])
def test_adapter_failure_elapsed_time_is_exact(
    adapter: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evaluator_core, "perf_counter", lambda: 10.25)
    result = asyncio.run(
        TrialRunner()._run_trial(
            adapter,  # type: ignore[arg-type]
            subject=_subject(),
            scenario=_scenario(),
            trial_id="adapter-elapsed",
            started=10.0,
        )
    )
    assert result.evidence.elapsed_ms == 250.0


def test_validation_error_deadline_checkpoint_binds_exact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    calls = _install_exact_deadline_probe(
        monkeypatch,
        expire_on=2,
        expected_subject=subject,
        expected_scenario=scenario,
        expected_trial_id="validation-deadline",
        expected_started=31.0,
        require_evidence=False,
    )

    def invalid_evidence(*_args: object, **_kwargs: object) -> TrialEvidence:
        return TrialEvidence.model_validate({})

    monkeypatch.setattr(TrialRunner, "_to_evidence", invalid_evidence)
    result = asyncio.run(
        TrialRunner()._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="validation-deadline",
            started=31.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert calls == {"expired": 2, "blocked": 1}


def test_pregrading_exception_deadline_checkpoint_binds_exact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    calls = _install_exact_deadline_probe(
        monkeypatch,
        expire_on=5,
        expected_subject=subject,
        expected_scenario=scenario,
        expected_trial_id="pregrading-deadline",
        expected_started=32.0,
        require_evidence=True,
    )

    def fail_pregrading(*_args: object, **_kwargs: object) -> None:
        raise EvaluationPreconditionError(
            source="evaluator:deadline-probe",
            code="deadline_probe",
            reason="force pregrading exception checkpoint",
        )

    monkeypatch.setattr(evaluator_core, "verify_pregrading_closure", fail_pregrading)
    result = asyncio.run(
        TrialRunner()._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="pregrading-deadline",
            started=32.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert calls == {"expired": 5, "blocked": 1}


def test_semantic_verification_exception_deadline_binds_exact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    calls = _install_exact_deadline_probe(
        monkeypatch,
        expire_on=7,
        expected_subject=subject,
        expected_scenario=scenario,
        expected_trial_id="semantic-verify-deadline",
        expected_started=33.0,
        require_evidence=True,
    )

    def fail_semantic(*_args: object, **_kwargs: object) -> object:
        raise SemanticJudgmentError("force semantic verification exception checkpoint")

    monkeypatch.setattr(evaluator_core, "verify_semantic_judgment", fail_semantic)
    result = asyncio.run(
        TrialRunner()._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="semantic-verify-deadline",
            started=33.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert calls == {"expired": 7, "blocked": 1}


def test_semantic_authority_exception_deadline_binds_exact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _semantic_scenario()
    calls = _install_exact_deadline_probe(
        monkeypatch,
        expire_on=8,
        expected_subject=subject,
        expected_scenario=scenario,
        expected_trial_id="semantic-authority-deadline",
        expected_started=34.0,
        require_evidence=True,
    )

    def fail_authority(*_args: object, **_kwargs: object) -> tuple[object, object]:
        raise LookupError("force semantic authority exception checkpoint")

    monkeypatch.setattr(evaluator_core, "validate_semantic_judge_authority", fail_authority)
    result = asyncio.run(
        TrialRunner(semantic_judge=_JudgeUnexpectedResponse())._run_trial(  # type: ignore[arg-type]
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="semantic-authority-deadline",
            started=34.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert calls == {"expired": 8, "blocked": 1}


def test_semantic_runtime_exception_deadline_binds_exact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _semantic_scenario()
    calls = _install_exact_deadline_probe(
        monkeypatch,
        expire_on=9,
        expected_subject=subject,
        expected_scenario=scenario,
        expected_trial_id="semantic-runtime-deadline",
        expected_started=35.0,
        require_evidence=True,
    )
    monkeypatch.setattr(
        evaluator_core,
        "validate_semantic_judge_authority",
        lambda *_args, **_kwargs: (object(), object()),
    )

    result = asyncio.run(
        TrialRunner(semantic_judge=_JudgeRuntimeFailure())._run_trial(  # type: ignore[arg-type]
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="semantic-runtime-deadline",
            started=35.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert calls == {"expired": 9, "blocked": 1}


def test_semantic_invalid_response_exception_deadline_binds_exact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _semantic_scenario()
    calls = _install_exact_deadline_probe(
        monkeypatch,
        expire_on=10,
        expected_subject=subject,
        expected_scenario=scenario,
        expected_trial_id="semantic-invalid-deadline",
        expected_started=36.0,
        require_evidence=True,
    )
    monkeypatch.setattr(
        evaluator_core,
        "validate_semantic_judge_authority",
        lambda *_args, **_kwargs: (object(), object()),
    )

    result = asyncio.run(
        TrialRunner(semantic_judge=_JudgeUnexpectedResponse())._run_trial(  # type: ignore[arg-type]
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="semantic-invalid-deadline",
            started=36.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert calls == {"expired": 10, "blocked": 1}


def test_semantic_final_deadline_checkpoint_binds_exact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_evals.semantic.models import (
        SemanticCriterionResult,
        SemanticDecision,
        SemanticJudgeResponse,
    )

    subject = _subject()
    scenario = _semantic_scenario()
    calls = _install_exact_deadline_probe(
        monkeypatch,
        expire_on=10,
        expected_subject=subject,
        expected_scenario=scenario,
        expected_trial_id="semantic-final-deadline",
        expected_started=37.0,
        require_evidence=True,
    )
    response = SemanticJudgeResponse(
        criteria=(
            SemanticCriterionResult(
                criterion_id="grounded",
                decision=SemanticDecision.PASS,
                score=4,
            ),
        ),
        overall=SemanticDecision.PASS,
    )

    class ValidJudge:
        async def judge(self, judge_input: object) -> SemanticJudgeResponse:
            assert judge_input is not None
            return response

    monkeypatch.setattr(
        evaluator_core,
        "validate_semantic_judge_authority",
        lambda *_args, **_kwargs: (object(), object()),
    )
    fake_receipt = cast(SemanticJudgmentReceipt, object())
    monkeypatch.setattr(
        evaluator_core.SemanticJudgmentReceipt,
        "create",
        lambda **_kwargs: fake_receipt,
    )
    monkeypatch.setattr(
        evaluator_core,
        "append_semantic_judgment",
        lambda evidence, receipt: evidence
        if receipt is fake_receipt
        else pytest.fail("wrong semantic receipt"),
    )

    result = asyncio.run(
        TrialRunner(semantic_judge=ValidJudge())._run_trial(  # type: ignore[arg-type]
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="semantic-final-deadline",
            started=37.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert calls == {"expired": 10, "blocked": 1}


@pytest.mark.parametrize("judge_remaining", [0.0, 0.5])
def test_configured_semantic_judge_remaining_boundary_is_exact(
    judge_remaining: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _semantic_scenario()
    judge_calls = {"count": 0}
    wait_calls = {"count": 0}
    blocked_calls = {"count": 0}
    remaining_values = iter((2.0, judge_remaining))

    class Judge:
        async def judge(self, judge_input: object) -> object:
            assert judge_input is not None
            judge_calls["count"] += 1
            return object()

    async def fake_wait(
        awaitables: object,
        *,
        timeout: float,
    ) -> tuple[set[asyncio.Task[object]], set[asyncio.Task[object]]]:
        tasks = tuple(awaitables)  # type: ignore[arg-type]
        assert len(tasks) == 1
        task = tasks[0]
        assert isinstance(task, asyncio.Task)
        wait_calls["count"] += 1
        if wait_calls["count"] == 1:
            assert timeout == 2.0
        else:
            assert timeout == judge_remaining
        await task
        return {task}, set()

    def remaining(_self: TrialRunner, started: float) -> float:
        assert started == 38.0
        return next(remaining_values)

    def blocked(
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
        assert scenario.identity == _semantic_scenario().identity
        assert trial_id == "semantic-remaining"
        assert started == 38.0
        assert evidence is not None
        blocked_calls["count"] += 1
        return EvaluatedTrial(
            evidence=evidence,
            oracle_results=(),
            verdict=TrialVerdict.BLOCKED,
        )

    runner = TrialRunner(semantic_judge=Judge(), deadline_seconds=3.0)  # type: ignore[arg-type]
    monkeypatch.setattr(TrialRunner, "_remaining_deadline_seconds", remaining)
    monkeypatch.setattr(TrialRunner, "_deadline_expired", lambda _self, _started: False)
    monkeypatch.setattr(TrialRunner, "_deadline_blocked", blocked)
    monkeypatch.setattr(evaluator_core.asyncio, "wait", fake_wait)
    monkeypatch.setattr(
        evaluator_core,
        "validate_semantic_judge_authority",
        lambda *_args, **_kwargs: (object(), object()),
    )

    result = asyncio.run(
        runner._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="semantic-remaining",
            started=38.0,
        )
    )

    if judge_remaining == 0.0:
        assert result.verdict is TrialVerdict.BLOCKED
        assert judge_calls["count"] == 0
        assert wait_calls["count"] == 1
        assert blocked_calls["count"] == 1
    else:
        assert judge_calls["count"] == 1
        assert wait_calls["count"] == 2
        assert blocked_calls["count"] == 0
        _assert_single_blocking_error(
            result,
            source="evaluator:semantic-judgment",
            code="semantic_judgment_invalid",
            reason="semantic judge returned an unexpected response type",
        )


def test_configured_semantic_judge_wait_timeout_binds_exact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _semantic_scenario()
    waits = {"count": 0}
    cancels = {"count": 0}
    blocked = {"count": 0}
    task_holder: list[asyncio.Task[object]] = []

    class Judge:
        async def judge(self, judge_input: object) -> object:
            assert judge_input is not None
            return object()

    async def fake_wait(
        awaitables: object,
        *,
        timeout: float,
    ) -> tuple[set[asyncio.Task[object]], set[asyncio.Task[object]]]:
        tasks = tuple(awaitables)  # type: ignore[arg-type]
        assert len(tasks) == 1
        task = tasks[0]
        assert isinstance(task, asyncio.Task)
        waits["count"] += 1
        assert timeout == 0.5
        if waits["count"] == 1:
            await task
            return {task}, set()
        task_holder.append(task)
        return set(), {task}

    def cancel(self: TrialRunner, task: asyncio.Task[object]) -> None:
        assert isinstance(self, TrialRunner)
        assert task_holder == [task]
        cancels["count"] += 1
        task.cancel()

    def deadline_blocked(
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
        assert scenario.identity == _semantic_scenario().identity
        assert trial_id == "semantic-wait-timeout"
        assert started == 39.0
        assert evidence is not None
        blocked["count"] += 1
        return EvaluatedTrial(
            evidence=evidence,
            oracle_results=(),
            verdict=TrialVerdict.BLOCKED,
        )

    runner = TrialRunner(semantic_judge=Judge(), deadline_seconds=3.0)  # type: ignore[arg-type]
    monkeypatch.setattr(
        TrialRunner,
        "_remaining_deadline_seconds",
        lambda _self, started: 0.5
        if started == 39.0
        else pytest.fail("wrong deadline origin"),
    )
    monkeypatch.setattr(TrialRunner, "_deadline_expired", lambda _self, _started: False)
    monkeypatch.setattr(TrialRunner, "_deadline_blocked", deadline_blocked)
    monkeypatch.setattr(TrialRunner, "_cancel_late_task", cancel)
    monkeypatch.setattr(evaluator_core.asyncio, "wait", fake_wait)
    monkeypatch.setattr(
        evaluator_core,
        "validate_semantic_judge_authority",
        lambda *_args, **_kwargs: (object(), object()),
    )

    result = asyncio.run(
        runner._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=subject,
            scenario=scenario,
            trial_id="semantic-wait-timeout",
            started=39.0,
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert waits["count"] == 2
    assert cancels["count"] == 1
    assert blocked["count"] == 1


def test_recorded_semantic_result_preserves_deterministic_oracle_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from agent_evals.semantic.models import SemanticDecision

    oracle = OracleResult(
        name="recorded-semantic-oracle",
        verdict=TrialVerdict.PASS,
        reasons=("preserved",),
        critical=True,
    )
    recorded = cast(
        SemanticJudgmentReceipt,
        SimpleNamespace(decision=SemanticDecision.PASS),
    )
    monkeypatch.setattr(
        evaluator_core,
        "grade_deterministic_evidence",
        lambda *_args, **_kwargs: (oracle,),
    )
    monkeypatch.setattr(
        evaluator_core,
        "verify_semantic_judgment",
        lambda *_args, **_kwargs: recorded,
    )

    result = asyncio.run(
        TrialRunner()._run_trial(
            _PassingAdapter(),  # type: ignore[arg-type]
            subject=_subject(),
            scenario=_semantic_scenario(),
            trial_id="recorded-semantic-oracles",
            started=0.0,
        )
    )

    assert result.verdict is TrialVerdict.PASS
    assert result.oracle_results == (oracle,)
    assert result.semantic_judgment is recorded

