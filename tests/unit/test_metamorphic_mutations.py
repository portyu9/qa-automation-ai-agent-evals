from __future__ import annotations

import pytest

from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.metamorphic.mutations import (
    MetamorphicEffectivenessPolicy,
    MetamorphicEffectivenessReport,
    MetamorphicMutantOutcome,
    MetamorphicMutantResult,
    MetamorphicMutationRecord,
    MetamorphicMutationSpec,
    generate_metamorphic_mutant,
)


def _base() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="mutation.base",
        revision="1",
        kind=ScenarioKind.CAPABILITY,
        objective="Preserve the declared behavior under the controlled transform.",
        initial_state={"locale": "en", "noise": "drop-me"},
        required_outcomes={"ok": True},
        tags=frozenset({"base"}),
    )


def test_generate_metamorphic_mutant_applies_only_declared_transformations() -> None:
    base = _base()
    spec = MetamorphicMutationSpec(
        mutation_id="mutation.locale",
        relation_id="relation.invariance",
        mutant_scenario_id="mutation.locale.variant",
        mutant_revision="1",
        objective_suffix="Equivalent formatting variant.",
        initial_state_overlay={"locale": "fr"},
        drop_initial_state_keys=("noise",),
        add_tags=("metamorphic.generated",),
    )

    mutant, record = generate_metamorphic_mutant(base, spec)

    assert mutant.kind is ScenarioKind.METAMORPHIC
    assert mutant.initial_state == {"locale": "fr"}
    assert mutant.identity != base.identity
    assert record.parent_scenario_identity == base.identity
    assert record.mutant_scenario_identity == mutant.identity
    assert record.mutation_spec_identity == spec.identity


def _record(index: int, *, parent: str = "a" * 64) -> MetamorphicMutationRecord:
    return MetamorphicMutationRecord(
        mutation_id=f"mutation.{index}",
        relation_id="relation.kill",
        parent_scenario_identity=parent,
        mutant_scenario_identity=f"{index + 1:064x}",
        mutation_spec_identity=f"{index + 101:064x}",
    )


def test_effectiveness_preserves_blocked_outcomes_and_uses_integer_ratio() -> None:
    outcomes = (
        MetamorphicMutantOutcome(mutation=_record(0), result=MetamorphicMutantResult.KILLED),
        MetamorphicMutantOutcome(mutation=_record(1), result=MetamorphicMutantResult.KILLED),
        MetamorphicMutantOutcome(mutation=_record(2), result=MetamorphicMutantResult.KILLED),
        MetamorphicMutantOutcome(mutation=_record(3), result=MetamorphicMutantResult.SURVIVED),
        MetamorphicMutantOutcome(mutation=_record(4), result=MetamorphicMutantResult.BLOCKED),
    )
    report = MetamorphicEffectivenessReport.create(
        policy=MetamorphicEffectivenessPolicy(
            min_evaluable_mutants=4,
            min_kill_numerator=3,
            min_kill_denominator=4,
        ),
        outcomes=outcomes,
    )

    assert report.total_mutants == 5
    assert report.evaluable_mutants == 4
    assert report.killed == 3
    assert report.survived == 1
    assert report.blocked == 1
    assert report.accepted is True

    weaker = tuple(
        outcome
        if index != 2
        else outcome.model_copy(update={"result": MetamorphicMutantResult.SURVIVED})
        for index, outcome in enumerate(outcomes)
    )
    rejected = MetamorphicEffectivenessReport.create(
        policy=report.policy,
        outcomes=weaker,
    )
    assert rejected.killed == 2
    assert rejected.survived == 2
    assert rejected.blocked == 1
    assert rejected.accepted is False


def test_effectiveness_rejects_cross_parent_aggregation() -> None:
    outcomes = (
        MetamorphicMutantOutcome(mutation=_record(0), result=MetamorphicMutantResult.KILLED),
        MetamorphicMutantOutcome(
            mutation=_record(1, parent="b" * 64),
            result=MetamorphicMutantResult.KILLED,
        ),
    )

    with pytest.raises(ValueError, match="exactly one parent"):
        MetamorphicEffectivenessReport.create(
            policy=MetamorphicEffectivenessPolicy(min_evaluable_mutants=1),
            outcomes=outcomes,
        )
