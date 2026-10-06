from __future__ import annotations

import pytest
from pydantic import ValidationError

import agent_evals.semantic as semantic
from agent_evals.semantic.models import SemanticDecision
from agent_evals.semantic.robustness import (
    SemanticAgreementObservation,
    SemanticDriftObservation,
    SemanticEnsembleConsensus,
    SemanticEnsembleObservation,
    SemanticEnsembleVote,
    SemanticProbeKind,
    SemanticRobustnessSummary,
    SemanticStabilityObservation,
)

CASE = "d" * 64
PROFILE_A = "a" * 64
PROFILE_B = "b" * 64
PROFILE_C = "c" * 64


def test_stability_summary_counts_changes_and_abstention_without_grading() -> None:
    changed = SemanticStabilityObservation(
        case_identity=CASE,
        judge_profile_identity=PROFILE_A,
        probe_kind=SemanticProbeKind.PARAPHRASE,
        baseline_decision=SemanticDecision.PASS,
        transformed_decision=SemanticDecision.FAIL,
    )
    abstained = SemanticStabilityObservation(
        case_identity="e" * 64,
        judge_profile_identity=PROFILE_A,
        probe_kind=SemanticProbeKind.FORMAT,
        baseline_decision=SemanticDecision.PASS,
        transformed_decision=SemanticDecision.ABSTAIN,
    )

    summary = SemanticRobustnessSummary.create(stability=(changed, abstained))

    assert changed.changed is True
    assert changed.contains_abstention is False
    assert summary.stability_observations == 2
    assert summary.stability_changes == 2
    assert summary.stability_with_abstention == 1
    assert not hasattr(summary, "decision")
    assert not hasattr(summary, "accepted")


def test_drift_requires_distinct_profiles_and_counts_revision_change() -> None:
    with pytest.raises(ValidationError, match="distinct judge profile identities"):
        SemanticDriftObservation(
            case_identity=CASE,
            baseline_profile_identity=PROFILE_A,
            candidate_profile_identity=PROFILE_A,
            baseline_decision=SemanticDecision.PASS,
            candidate_decision=SemanticDecision.PASS,
        )

    drift = SemanticDriftObservation(
        case_identity=CASE,
        baseline_profile_identity=PROFILE_A,
        candidate_profile_identity=PROFILE_B,
        baseline_decision=SemanticDecision.FAIL,
        candidate_decision=SemanticDecision.ABSTAIN,
    )
    summary = SemanticRobustnessSummary.create(drift=(drift,))

    assert drift.changed is True
    assert drift.contains_abstention is True
    assert summary.drift_changes == 1
    assert summary.drift_with_abstention == 1


def test_pairwise_agreement_requires_canonical_profile_pair() -> None:
    with pytest.raises(ValidationError, match="distinct and canonical"):
        SemanticAgreementObservation(
            case_identity=CASE,
            left_profile_identity=PROFILE_B,
            right_profile_identity=PROFILE_A,
            left_decision=SemanticDecision.PASS,
            right_decision=SemanticDecision.PASS,
        )

    disagreement = SemanticAgreementObservation(
        case_identity=CASE,
        left_profile_identity=PROFILE_A,
        right_profile_identity=PROFILE_B,
        left_decision=SemanticDecision.PASS,
        right_decision=SemanticDecision.FAIL,
    )
    summary = SemanticRobustnessSummary.create(agreement=(disagreement,))

    assert disagreement.agrees is False
    assert summary.agreement_disagreements == 1


def test_ensemble_is_diagnostic_only_and_requires_unique_canonical_profiles() -> None:
    with pytest.raises(ValidationError, match="unique judge profile identities"):
        SemanticEnsembleObservation(
            case_identity=CASE,
            votes=(
                SemanticEnsembleVote(
                    profile_identity=PROFILE_A,
                    decision=SemanticDecision.PASS,
                ),
                SemanticEnsembleVote(
                    profile_identity=PROFILE_A,
                    decision=SemanticDecision.FAIL,
                ),
            ),
        )

    with pytest.raises(ValidationError, match="ordered by judge profile identity"):
        SemanticEnsembleObservation(
            case_identity=CASE,
            votes=(
                SemanticEnsembleVote(
                    profile_identity=PROFILE_B,
                    decision=SemanticDecision.PASS,
                ),
                SemanticEnsembleVote(
                    profile_identity=PROFILE_A,
                    decision=SemanticDecision.PASS,
                ),
            ),
        )

    ensemble = SemanticEnsembleObservation(
        case_identity=CASE,
        votes=(
            SemanticEnsembleVote(
                profile_identity=PROFILE_A,
                decision=SemanticDecision.PASS,
            ),
            SemanticEnsembleVote(
                profile_identity=PROFILE_B,
                decision=SemanticDecision.FAIL,
            ),
            SemanticEnsembleVote(
                profile_identity=PROFILE_C,
                decision=SemanticDecision.PASS,
            ),
        ),
    )
    summary = SemanticRobustnessSummary.create(ensembles=(ensemble,))

    assert ensemble.consensus is SemanticEnsembleConsensus.DISAGREEMENT
    assert summary.ensemble_disagreements == 1
    assert not hasattr(ensemble, "majority_decision")
    assert not hasattr(ensemble, "decision")


def test_unanimous_abstention_is_distinct_from_resolved_consistency() -> None:
    abstained = SemanticEnsembleObservation(
        case_identity=CASE,
        votes=(
            SemanticEnsembleVote(
                profile_identity=PROFILE_A,
                decision=SemanticDecision.ABSTAIN,
            ),
            SemanticEnsembleVote(
                profile_identity=PROFILE_B,
                decision=SemanticDecision.ABSTAIN,
            ),
        ),
    )
    resolved = SemanticEnsembleObservation(
        case_identity="e" * 64,
        votes=(
            SemanticEnsembleVote(
                profile_identity=PROFILE_A,
                decision=SemanticDecision.FAIL,
            ),
            SemanticEnsembleVote(
                profile_identity=PROFILE_B,
                decision=SemanticDecision.FAIL,
            ),
        ),
    )
    summary = SemanticRobustnessSummary.create(ensembles=(abstained, resolved))

    assert abstained.consensus is SemanticEnsembleConsensus.UNANIMOUS_ABSTAIN
    assert resolved.consensus is SemanticEnsembleConsensus.UNANIMOUS_RESOLVED
    assert summary.ensemble_unanimous_abstentions == 1
    assert summary.ensemble_disagreements == 0


def test_summary_revalidates_copied_observations() -> None:
    valid = SemanticStabilityObservation(
        case_identity=CASE,
        judge_profile_identity=PROFILE_A,
        probe_kind=SemanticProbeKind.ORDER,
        baseline_decision=SemanticDecision.PASS,
        transformed_decision=SemanticDecision.PASS,
    )
    forged = valid.model_copy(update={"case_identity": "not-a-digest"})

    with pytest.raises(ValidationError, match="case_identity"):
        SemanticRobustnessSummary.create(stability=(forged,))


def test_summary_rejects_impossible_subcounts() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        SemanticRobustnessSummary(
            stability_observations=0,
            stability_changes=1,
            stability_with_abstention=0,
            drift_observations=0,
            drift_changes=0,
            drift_with_abstention=0,
            agreement_observations=0,
            agreement_disagreements=0,
            agreement_with_abstention=0,
            ensemble_observations=0,
            ensemble_disagreements=0,
            ensemble_unanimous_abstentions=0,
        )


def test_semantic_robustness_contracts_are_public_api() -> None:
    expected = {
        "SemanticAgreementObservation",
        "SemanticDriftObservation",
        "SemanticEnsembleConsensus",
        "SemanticEnsembleObservation",
        "SemanticEnsembleVote",
        "SemanticProbeKind",
        "SemanticRobustnessSummary",
        "SemanticStabilityObservation",
    }

    assert expected <= set(semantic.__all__)
    for name in expected:
        assert getattr(semantic, name) is not None
