"""Durable repeated-trial provenance embedded in assurance reports."""

from __future__ import annotations

import re
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.runtime.reset_isolation import (
    ResetIsolationError,
    ResetIsolationReceipt,
    verify_reset_isolation_sequence,
)
from agent_evals.runtime.sampling import (
    SamplingProvenanceError,
    SessionSamplingMetadata,
    verify_session_sampling_metadata,
)
from agent_evals.runtime.session import EvaluationSessionResult, IndependenceStatus

_CAMPAIGN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_INDEPENDENCE_BASIS_LENGTH = 2_000


class SessionProvenanceSnapshot(BaseModel):
    """Versioned report-bound provenance for one repeated-trial campaign.

    This snapshot preserves the exact independence qualification together with campaign, adapter,
    reset/isolation, sampling, randomness, and stopping provenance. Receipt hashes remain integrity
    relations only; this model does not upgrade them into authentication, provider attestation, or
    formal IID evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_id: str = Field(min_length=1, max_length=128)
    independence_status: IndependenceStatus
    independence_basis: str | None = Field(
        default=None,
        max_length=_MAX_INDEPENDENCE_BASIS_LENGTH,
    )
    runtime_adapter_name: str = Field(min_length=1, max_length=256)
    subject_adapter: str = Field(min_length=1, max_length=512)
    subject_adapter_version: str = Field(min_length=1, max_length=512)
    reset_strategy_name: str | None = Field(default=None, max_length=256)
    reset_strategy_version: str | None = Field(default=None, max_length=256)
    reset_isolation_receipts: tuple[ResetIsolationReceipt, ...] = ()
    sampling_metadata: SessionSamplingMetadata

    @field_validator("campaign_id")
    @classmethod
    def validate_campaign_id(cls, value: str) -> str:
        if _CAMPAIGN_ID_RE.fullmatch(value) is None:
            raise ValueError("report campaign_id is not canonical")
        return value

    @field_validator(
        "runtime_adapter_name",
        "subject_adapter",
        "subject_adapter_version",
        "reset_strategy_name",
        "reset_strategy_version",
    )
    @classmethod
    def reject_surrounding_whitespace(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("report session provenance identities must not contain whitespace")
        return value

    @model_validator(mode="after")
    def validate_independence_shape(self) -> Self:
        strategy_present = self.reset_strategy_name is not None or self.reset_strategy_version is not None
        if strategy_present and (
            self.reset_strategy_name is None or self.reset_strategy_version is None
        ):
            raise ValueError("reset strategy name/version must be both present or both absent")

        if self.independence_status is IndependenceStatus.UNVERIFIED:
            if self.independence_basis is not None:
                raise ValueError("unverified independence cannot carry an assertion basis")
            if strategy_present or self.reset_isolation_receipts:
                raise ValueError("unverified independence cannot carry verified reset provenance")
        elif self.independence_status is IndependenceStatus.OPERATOR_ASSERTED:
            basis = self.independence_basis
            if basis is None or not basis or basis != basis.strip():
                raise ValueError("operator-asserted independence requires a bounded assertion basis")
            if strategy_present or self.reset_isolation_receipts:
                raise ValueError(
                    "operator-asserted independence cannot carry evaluator-verified reset provenance"
                )
        elif self.independence_status is IndependenceStatus.VERIFIED:
            if self.independence_basis is not None:
                raise ValueError("verified independence cannot carry an operator assertion basis")
            if not strategy_present or not self.reset_isolation_receipts:
                raise ValueError(
                    "verified independence requires reset strategy and receipt provenance"
                )
        else:
            raise ValueError("unsupported independence status")
        return self

    @classmethod
    def from_session(cls, session: EvaluationSessionResult) -> SessionProvenanceSnapshot:
        """Copy one fully validated modern session into durable report provenance."""
        session.validate()
        if session.campaign_id is None:
            raise ValueError("assurance-report v6 requires a campaign identity")
        if (
            session.runtime_adapter_name is None
            or session.subject_adapter is None
            or session.subject_adapter_version is None
        ):
            raise ValueError("assurance-report v6 requires complete adapter provenance")
        if session.sampling_metadata is None:
            raise ValueError("assurance-report v6 requires versioned sampling provenance")

        reset_receipts = tuple(
            ResetIsolationReceipt.model_validate(receipt.model_dump(mode="json"))
            for receipt in session.reset_isolation_receipts
        )
        sampling_metadata = SessionSamplingMetadata.model_validate(
            session.sampling_metadata.model_dump(mode="json")
        )
        return cls(
            campaign_id=session.campaign_id,
            independence_status=session.independence_status,
            independence_basis=session.independence_basis,
            runtime_adapter_name=session.runtime_adapter_name,
            subject_adapter=session.subject_adapter,
            subject_adapter_version=session.subject_adapter_version,
            reset_strategy_name=session.reset_strategy_name,
            reset_strategy_version=session.reset_strategy_version,
            reset_isolation_receipts=reset_receipts,
            sampling_metadata=sampling_metadata,
        )

    @property
    def reset_receipt_roots(self) -> tuple[str, ...]:
        return tuple(receipt.receipt_root for receipt in self.reset_isolation_receipts)

    @property
    def randomness_receipt_roots(self) -> tuple[str, ...]:
        return tuple(
            receipt.receipt_root
            for receipt in self.sampling_metadata.randomness_control_receipts
        )

    def validate_against_report(
        self,
        *,
        subject_identity: str,
        scenario_identity: str,
        trial_ids: tuple[str, ...],
        evidence_roots: tuple[str, ...],
    ) -> None:
        """Re-derive provenance relations from the ordered report trial records."""
        if len(trial_ids) != len(evidence_roots):
            raise ValueError("report trial IDs and evidence roots must have equal length")
        expected_trial_ids = tuple(
            _campaign_trial_id(self.campaign_id, attempt_index)
            for attempt_index in range(len(trial_ids))
        )
        if trial_ids != expected_trial_ids:
            raise ValueError("report trial order does not match the bound campaign identity")

        try:
            verify_session_sampling_metadata(
                self.sampling_metadata,
                campaign_id=self.campaign_id,
                subject_identity=subject_identity,
                scenario_identity=scenario_identity,
                runtime_adapter_name=self.runtime_adapter_name,
                subject_adapter=self.subject_adapter,
                subject_adapter_version=self.subject_adapter_version,
                trial_ids=trial_ids,
            )
        except SamplingProvenanceError as exc:
            raise ValueError("assurance report sampling provenance is invalid") from exc

        if self.independence_status is IndependenceStatus.VERIFIED:
            if self.reset_strategy_name is None or self.reset_strategy_version is None:
                raise ValueError("verified report independence lost reset strategy provenance")
            try:
                verify_reset_isolation_sequence(
                    self.reset_isolation_receipts,
                    campaign_id=self.campaign_id,
                    subject_identity=subject_identity,
                    scenario_identity=scenario_identity,
                    runtime_adapter_name=self.runtime_adapter_name,
                    subject_adapter=self.subject_adapter,
                    subject_adapter_version=self.subject_adapter_version,
                    reset_strategy_name=self.reset_strategy_name,
                    reset_strategy_version=self.reset_strategy_version,
                    trial_ids=trial_ids,
                    evidence_roots=evidence_roots,
                )
            except ResetIsolationError as exc:
                raise ValueError("assurance report reset/isolation provenance is invalid") from exc


def _campaign_trial_id(campaign_id: str, attempt_index: int) -> str:
    return f"campaign:{campaign_id}:attempt:{attempt_index:04d}"
