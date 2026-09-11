from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.runtime.sampling import (
    RandomnessControlContext,
    RandomnessControlObservation,
    RandomnessStatus,
    SamplingPolicy,
    SamplingProvenanceError,
    SessionSamplingMetadata,
    StoppingRule,
)
from agent_evals.runtime.session import EvaluationSession, IndependenceStatus
from agent_evals.statistics.reliability import ReliabilityReport


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="scripted",
        model="deterministic",
        application_revision="sampling-provenance-v1",
        instructions="Return the expected state.",
        tool_schema={},
        policy={},
        memory_policy={"retention": "trial"},
        adapter="scripted-subject",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="session.sampling-provenance",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Exercise repeated-trial sampling provenance.",
        required_outcomes={"status": "ok"},
    )


def _adapter(calls: list[str] | None = None) -> ScriptedAdapter:
    def script(
        _subject_value: SubjectFingerprint,
        _scenario_value: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        if calls is not None:
            calls.append(trial_id)
        return AdapterResult(final_state={"status": "ok"})

    return ScriptedAdapter(script, name="sampling-runtime")


class _RandomnessControl:
    strategy_name = "deterministic-seed-injector"
    strategy_version = "1"

    def __init__(self, *, reuse_seed: bool = False) -> None:
        self.reuse_seed = reuse_seed
        self.contexts: list[RandomnessControlContext] = []

    async def prepare(
        self,
        *,
        context: RandomnessControlContext,
    ) -> RandomnessControlObservation:
        self.contexts.append(context)
        seed_index = 0 if self.reuse_seed else context.attempt_index
        return RandomnessControlObservation(
            seed_identity=_sha(f"seed:{seed_index}"),
            control_evidence_identity=_sha(
                f"control:{context.campaign_id}:{context.attempt_index}:{context.trial_id}"
            ),
        )


@pytest.mark.asyncio
async def test_session_records_predeclared_fixed_horizon_with_unknown_randomness() -> None:
    basis = "Operator asserts attempts are independent for this isolated fixture."
    evaluated = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=3,
        k=2,
        campaign_id="sampling-default",
        independence_status=IndependenceStatus.OPERATOR_ASSERTED,
        independence_basis=basis,
    )

    metadata = evaluated.sampling_metadata
    assert metadata is not None
    assert metadata.schema_version == "agent-evals/session-sampling/v1"
    assert metadata.sampling_policy is SamplingPolicy.PREDECLARED_ALL_ATTEMPTS
    assert metadata.stopping_rule is StoppingRule.FIXED_HORIZON
    assert metadata.planned_trials == 3
    assert metadata.randomness_status is RandomnessStatus.UNKNOWN
    assert metadata.randomness_basis is None
    assert metadata.randomness_control_receipts == ()

    metrics = evaluated.independence_qualified_metrics()
    assert metrics.sampling_schema_version == metadata.schema_version
    assert metrics.sampling_policy is SamplingPolicy.PREDECLARED_ALL_ATTEMPTS
    assert metrics.stopping_rule is StoppingRule.FIXED_HORIZON
    assert metrics.planned_trials == 3
    assert metrics.randomness_status is RandomnessStatus.UNKNOWN
    assert metrics.randomness_receipt_roots == ()


@pytest.mark.asyncio
async def test_evaluator_controlled_randomness_binds_every_attempt() -> None:
    control = _RandomnessControl()
    evaluated = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=3,
        campaign_id="sampling-seeded",
        independence_status=IndependenceStatus.OPERATOR_ASSERTED,
        independence_basis="Operator asserts the non-random state is isolated between attempts.",
        randomness_status=RandomnessStatus.EVALUATOR_CONTROLLED,
        randomness_control=control,
    )

    metadata = evaluated.sampling_metadata
    assert metadata is not None
    assert metadata.randomness_status is RandomnessStatus.EVALUATOR_CONTROLLED
    assert metadata.randomness_strategy_name == "deterministic-seed-injector"
    assert metadata.randomness_strategy_version == "1"
    assert len(metadata.randomness_control_receipts) == 3
    assert [context.attempt_index for context in control.contexts] == [0, 1, 2]
    assert [context.trial_id for context in control.contexts] == [
        "campaign:sampling-seeded:attempt:0000",
        "campaign:sampling-seeded:attempt:0001",
        "campaign:sampling-seeded:attempt:0002",
    ]
    assert len({receipt.seed_identity for receipt in metadata.randomness_control_receipts}) == 3
    evaluated.validate()

    metrics = evaluated.independence_qualified_metrics()
    assert metrics.randomness_status is RandomnessStatus.EVALUATOR_CONTROLLED
    assert metrics.randomness_strategy_name == "deterministic-seed-injector"
    assert metrics.randomness_receipt_roots == tuple(
        receipt.receipt_root for receipt in metadata.randomness_control_receipts
    )


@pytest.mark.asyncio
async def test_duplicate_evaluator_seed_stops_before_affected_subject_attempt() -> None:
    calls: list[str] = []
    control = _RandomnessControl(reuse_seed=True)

    with pytest.raises(SamplingProvenanceError, match="seed identity was reused"):
        await EvaluationSession().run(
            _adapter(calls),
            subject=_subject(),
            scenario=_scenario(),
            trials=3,
            campaign_id="sampling-seed-reuse",
            randomness_status=RandomnessStatus.EVALUATOR_CONTROLLED,
            randomness_control=control,
        )

    assert calls == ["campaign:sampling-seed-reuse:attempt:0000"]
    assert [context.attempt_index for context in control.contexts] == [0, 1]


@pytest.mark.asyncio
async def test_hidden_early_termination_breaks_fixed_horizon_validation() -> None:
    evaluated = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=3,
        campaign_id="sampling-hidden-stop",
    )
    truncated_trials = evaluated.trials[:2]
    forged = replace(
        evaluated,
        trials=truncated_trials,
        reliability=ReliabilityReport.from_verdicts(
            tuple(trial.verdict for trial in truncated_trials),
            k=evaluated.reliability.k,
            confidence_z=evaluated.reliability.confidence_z,
        ),
    )

    with pytest.raises(SamplingProvenanceError, match="predeclared horizon"):
        forged.validate()


@pytest.mark.asyncio
async def test_adaptive_stopping_is_not_treated_as_fixed_horizon_sampling() -> None:
    evaluated = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=3,
        campaign_id="sampling-adaptive",
        independence_status=IndependenceStatus.OPERATOR_ASSERTED,
        independence_basis="Operator asserts attempt independence.",
    )
    adaptive = SessionSamplingMetadata(
        sampling_policy=SamplingPolicy.PREDECLARED_ALL_ATTEMPTS,
        randomness_status=RandomnessStatus.UNKNOWN,
        stopping_rule=StoppingRule.ADAPTIVE_SEQUENTIAL,
        stopping_basis="Stop after the first observed pass or after an external sequential rule fires.",
    )
    forged = replace(evaluated, sampling_metadata=adaptive)
    forged.validate()

    with pytest.raises(SamplingProvenanceError, match="fixed-horizon"):
        forged.independence_qualified_metrics()


@pytest.mark.asyncio
async def test_external_selection_cherry_pick_is_not_qualifiable_sampling() -> None:
    evaluated = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
        campaign_id="sampling-external-selection",
        independence_status=IndependenceStatus.OPERATOR_ASSERTED,
        independence_basis="Operator asserts independence after external selection.",
    )
    externally_selected = SessionSamplingMetadata(
        sampling_policy=SamplingPolicy.EXTERNAL_SELECTION,
        sampling_basis="Only attempts selected by an external post-run filter were retained.",
        randomness_status=RandomnessStatus.UNKNOWN,
        stopping_rule=StoppingRule.FIXED_HORIZON,
        planned_trials=2,
    )
    forged = replace(evaluated, sampling_metadata=externally_selected)
    forged.validate()

    with pytest.raises(SamplingProvenanceError, match="predeclared inclusion"):
        forged.independence_qualified_metrics()


@pytest.mark.asyncio
async def test_legacy_missing_sampling_metadata_cannot_qualify_independent_attempt_metrics() -> (
    None
):
    evaluated = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
        campaign_id="sampling-legacy",
        independence_status=IndependenceStatus.OPERATOR_ASSERTED,
        independence_basis="Legacy operator assertion.",
    )
    legacy = replace(evaluated, sampling_metadata=None)
    legacy.validate()

    with pytest.raises(SamplingProvenanceError, match="versioned sampling/stopping provenance"):
        legacy.independence_qualified_metrics()


@pytest.mark.asyncio
async def test_randomness_receipt_seed_mutation_is_rejected() -> None:
    evaluated = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
        campaign_id="sampling-seed-mutation",
        randomness_status=RandomnessStatus.EVALUATOR_CONTROLLED,
        randomness_control=_RandomnessControl(),
    )
    metadata = evaluated.sampling_metadata
    assert metadata is not None
    mutated_receipt = metadata.randomness_control_receipts[0].model_copy(
        update={"seed_identity": _sha("mutated-seed")}
    )
    mutated_metadata = metadata.model_copy(
        update={
            "randomness_control_receipts": (
                mutated_receipt,
                *metadata.randomness_control_receipts[1:],
            )
        }
    )
    forged = replace(evaluated, sampling_metadata=mutated_metadata)

    with pytest.raises(SamplingProvenanceError, match="malformed"):
        forged.validate()


@pytest.mark.asyncio
async def test_randomness_provenance_cannot_replay_across_campaigns() -> None:
    first = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
        campaign_id="sampling-campaign-a",
        randomness_status=RandomnessStatus.EVALUATOR_CONTROLLED,
        randomness_control=_RandomnessControl(),
    )
    second = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
        campaign_id="sampling-campaign-b",
        randomness_status=RandomnessStatus.EVALUATOR_CONTROLLED,
        randomness_control=_RandomnessControl(),
    )
    assert first.sampling_metadata is not None
    forged = replace(second, sampling_metadata=first.sampling_metadata)

    with pytest.raises(SamplingProvenanceError, match="does not match"):
        forged.validate()


@pytest.mark.asyncio
async def test_unknown_randomness_cannot_smuggle_asserted_seed_provenance() -> None:
    calls: list[str] = []

    with pytest.raises(SamplingProvenanceError, match="unknown randomness"):
        await EvaluationSession().run(
            _adapter(calls),
            subject=_subject(),
            scenario=_scenario(),
            trials=1,
            randomness_status=RandomnessStatus.UNKNOWN,
            randomness_basis="Provider probably uses seed 42.",
        )

    assert calls == []


@pytest.mark.asyncio
async def test_external_and_unavailable_randomness_require_explicit_bases() -> None:
    calls: list[str] = []

    for status in (RandomnessStatus.EXTERNALLY_CONTROLLED, RandomnessStatus.UNAVAILABLE):
        with pytest.raises(SamplingProvenanceError, match="requires a non-empty"):
            await EvaluationSession().run(
                _adapter(calls),
                subject=_subject(),
                scenario=_scenario(),
                trials=1,
                randomness_status=status,
            )

    evaluated = await EvaluationSession().run(
        _adapter(calls),
        subject=_subject(),
        scenario=_scenario(),
        trials=1,
        campaign_id="sampling-external-randomness",
        randomness_status=RandomnessStatus.EXTERNALLY_CONTROLLED,
        randomness_basis="The provider owns randomness and exposes no evaluator seed injection.",
    )
    assert evaluated.sampling_metadata is not None
    assert evaluated.sampling_metadata.randomness_status is RandomnessStatus.EXTERNALLY_CONTROLLED
    assert evaluated.sampling_metadata.randomness_control_receipts == ()
