"""Diagnostic semantic robustness contracts subordinate to calibrated semantic authority.

These contracts measure perturbation stability, judge-revision drift, inter-judge agreement, and
optional ensemble disagreement. They intentionally expose only diagnostic sufficient statistics:
they do not mint calibration authority, derive a grading verdict, or rescue deterministic failure.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.semantic.models import SemanticDecision

_STABILITY_SCHEMA: Literal["agent-evals/semantic-stability-observation/v1"] = (
    "agent-evals/semantic-stability-observation/v1"
)
_DRIFT_SCHEMA: Literal["agent-evals/semantic-drift-observation/v1"] = (
    "agent-evals/semantic-drift-observation/v1"
)
_AGREEMENT_SCHEMA: Literal["agent-evals/semantic-agreement-observation/v1"] = (
    "agent-evals/semantic-agreement-observation/v1"
)
_ENSEMBLE_SCHEMA: Literal["agent-evals/semantic-ensemble-observation/v1"] = (
    "agent-evals/semantic-ensemble-observation/v1"
)
_SUMMARY_SCHEMA: Literal["agent-evals/semantic-robustness-summary/v1"] = (
    "agent-evals/semantic-robustness-summary/v1"
)


class SemanticProbeKind(StrEnum):
    """Controlled perturbation class used only for semantic stability diagnostics."""

    PARAPHRASE = "paraphrase"
    ORDER = "order"
    FORMAT = "format"


class SemanticEnsembleConsensus(StrEnum):
    """Diagnostic consistency shape across independent judge profiles."""

    UNANIMOUS_RESOLVED = "unanimous_resolved"
    UNANIMOUS_ABSTAIN = "unanimous_abstain"
    DISAGREEMENT = "disagreement"


class SemanticStabilityObservation(BaseModel):
    """Compare one exact judge profile before and after a controlled input perturbation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-stability-observation/v1"] = _STABILITY_SCHEMA
    case_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_profile_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_kind: SemanticProbeKind
    baseline_decision: SemanticDecision
    transformed_decision: SemanticDecision

    @property
    def changed(self) -> bool:
        return self.baseline_decision is not self.transformed_decision

    @property
    def contains_abstention(self) -> bool:
        return (
            self.baseline_decision is SemanticDecision.ABSTAIN
            or self.transformed_decision is SemanticDecision.ABSTAIN
        )


class SemanticDriftObservation(BaseModel):
    """Compare decisions for one case across two distinct judge-profile identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-drift-observation/v1"] = _DRIFT_SCHEMA
    case_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_profile_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_profile_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_decision: SemanticDecision
    candidate_decision: SemanticDecision

    @model_validator(mode="after")
    def require_distinct_profiles(self) -> Self:
        if self.baseline_profile_identity == self.candidate_profile_identity:
            raise ValueError(\n                "semantic drift observation requires distinct judge profile identities"\n            )
        return self

    @property
    def changed(self) -> bool:
        return self.baseline_decision is not self.candidate_decision

    @property
    def contains_abstention(self) -> bool:
        return (
            self.baseline_decision is SemanticDecision.ABSTAIN
            or self.candidate_decision is SemanticDecision.ABSTAIN
        )


class SemanticAgreementObservation(BaseModel):
    """Pairwise inter-judge agreement diagnostic for one case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-agreement-observation/v1"] = _AGREEMENT_SCHEMA
    case_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    left_profile_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    right_profile_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    left_decision: SemanticDecision
    right_decision: SemanticDecision

    @model_validator(mode="after")
    def require_canonical_distinct_pair(self) -> Self:
        if self.left_profile_identity >= self.right_profile_identity:
            raise ValueError(
                "semantic agreement profile identities must be distinct and canonical"
            )
        return self

    @property
    def agrees(self) -> bool:
        return self.left_decision is self.right_decision

    @property
    def contains_abstention(self) -> bool:
        return (
            self.left_decision is SemanticDecision.ABSTAIN
            or self.right_decision is SemanticDecision.ABSTAIN
        )


class SemanticEnsembleVote(BaseModel):
    """One profile-bound decision inside a diagnostic ensemble observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: SemanticDecision


class SemanticEnsembleObservation(BaseModel):
    """Diagnostic ensemble shape without deriving any authoritative aggregate verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-ensemble-observation/v1"] = _ENSEMBLE_SCHEMA
    case_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    votes: tuple[SemanticEnsembleVote, ...] = Field(min_length=2, max_length=32)

    @model_validator(mode="after")
    def require_unique_canonical_profiles(self) -> Self:
        identities = tuple(vote.profile_identity for vote in self.votes)
        if len(set(identities)) != len(identities):
            raise ValueError("semantic ensemble requires unique judge profile identities")
        if identities != tuple(sorted(identities)):
            raise ValueError("semantic ensemble votes must be ordered by judge profile identity")
        return self

    @property
    def consensus(self) -> SemanticEnsembleConsensus:
        decisions = {vote.decision for vote in self.votes}
        if len(decisions) != 1:
            return SemanticEnsembleConsensus.DISAGREEMENT
        only = next(iter(decisions))
        if only is SemanticDecision.ABSTAIN:
            return SemanticEnsembleConsensus.UNANIMOUS_ABSTAIN
        return SemanticEnsembleConsensus.UNANIMOUS_RESOLVED


class SemanticRobustnessSummary(BaseModel):
    """Versioned integer sufficient statistics for semantic robustness surveillance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-robustness-summary/v1"] = _SUMMARY_SCHEMA
    stability_observations: int = Field(ge=0, strict=True)
    stability_changes: int = Field(ge=0, strict=True)
    stability_with_abstention: int = Field(ge=0, strict=True)
    drift_observations: int = Field(ge=0, strict=True)
    drift_changes: int = Field(ge=0, strict=True)
    drift_with_abstention: int = Field(ge=0, strict=True)
    agreement_observations: int = Field(ge=0, strict=True)
    agreement_disagreements: int = Field(ge=0, strict=True)
    agreement_with_abstention: int = Field(ge=0, strict=True)
    ensemble_observations: int = Field(ge=0, strict=True)
    ensemble_disagreements: int = Field(ge=0, strict=True)
    ensemble_unanimous_abstentions: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def validate_subcounts(self) -> Self:
        bounded = (
            ("stability_changes", self.stability_changes, self.stability_observations),
            (
                "stability_with_abstention",
                self.stability_with_abstention,
                self.stability_observations,
            ),
            ("drift_changes", self.drift_changes, self.drift_observations),
            ("drift_with_abstention", self.drift_with_abstention, self.drift_observations),
            (
                "agreement_disagreements",
                self.agreement_disagreements,
                self.agreement_observations,
            ),
            (
                "agreement_with_abstention",
                self.agreement_with_abstention,
                self.agreement_observations,
            ),
            (
                "ensemble_disagreements",
                self.ensemble_disagreements,
                self.ensemble_observations,
            ),
            (
                "ensemble_unanimous_abstentions",
                self.ensemble_unanimous_abstentions,
                self.ensemble_observations,
            ),
        )
        for label, count, total in bounded:
            if count > total:
                raise ValueError(f"{label} cannot exceed its observation count")
        return self

    @classmethod
    def create(
        cls,
        *,
        stability: tuple[SemanticStabilityObservation, ...] = (),
        drift: tuple[SemanticDriftObservation, ...] = (),
        agreement: tuple[SemanticAgreementObservation, ...] = (),
        ensembles: tuple[SemanticEnsembleObservation, ...] = (),
    ) -> Self:
        stability_checked = tuple(_revalidate_stability(item) for item in stability)
        drift_checked = tuple(_revalidate_drift(item) for item in drift)
        agreement_checked = tuple(_revalidate_agreement(item) for item in agreement)
        ensemble_checked = tuple(_revalidate_ensemble(item) for item in ensembles)
        return cls(
            stability_observations=len(stability_checked),
            stability_changes=sum(item.changed for item in stability_checked),
            stability_with_abstention=sum(
                item.contains_abstention for item in stability_checked
            ),
            drift_observations=len(drift_checked),
            drift_changes=sum(item.changed for item in drift_checked),
            drift_with_abstention=sum(item.contains_abstention for item in drift_checked),
            agreement_observations=len(agreement_checked),
            agreement_disagreements=sum(not item.agrees for item in agreement_checked),
            agreement_with_abstention=sum(
                item.contains_abstention for item in agreement_checked
            ),
            ensemble_observations=len(ensemble_checked),
            ensemble_disagreements=sum(
                item.consensus is SemanticEnsembleConsensus.DISAGREEMENT
                for item in ensemble_checked
            ),
            ensemble_unanimous_abstentions=sum(
                item.consensus is SemanticEnsembleConsensus.UNANIMOUS_ABSTAIN
                for item in ensemble_checked
            ),
        )


def _revalidate_stability(value: SemanticStabilityObservation) -> SemanticStabilityObservation:
    if type(value) is not SemanticStabilityObservation:
        raise ValueError("semantic robustness requires exact stability observations")
    return SemanticStabilityObservation.model_validate(value.model_dump(mode="json"))


def _revalidate_drift(value: SemanticDriftObservation) -> SemanticDriftObservation:
    if type(value) is not SemanticDriftObservation:
        raise ValueError("semantic robustness requires exact drift observations")
    return SemanticDriftObservation.model_validate(value.model_dump(mode="json"))


def _revalidate_agreement(value: SemanticAgreementObservation) -> SemanticAgreementObservation:
    if type(value) is not SemanticAgreementObservation:
        raise ValueError("semantic robustness requires exact agreement observations")
    return SemanticAgreementObservation.model_validate(value.model_dump(mode="json"))


def _revalidate_ensemble(value: SemanticEnsembleObservation) -> SemanticEnsembleObservation:
    if type(value) is not SemanticEnsembleObservation:
        raise ValueError("semantic robustness requires exact ensemble observations")
    return SemanticEnsembleObservation.model_validate(value.model_dump(mode="json"))


__all__ = [
    "SemanticAgreementObservation",
    "SemanticDriftObservation",
    "SemanticEnsembleConsensus",
    "SemanticEnsembleObservation",
    "SemanticEnsembleVote",
    "SemanticProbeKind",
    "SemanticRobustnessSummary",
    "SemanticStabilityObservation",
]
