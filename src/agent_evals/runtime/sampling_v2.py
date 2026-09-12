"""Population-aware session statistical provenance with explicit v1 compatibility."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.runtime.population import (
    PopulationProvenance,
    PopulationProvenanceError,
    validate_population_provenance,
)
from agent_evals.runtime.sampling import SessionSamplingMetadata
from agent_evals.runtime.session import EvaluationSessionResult

_SAMPLING_V2_SCHEMA: Literal["agent-evals/session-sampling/v2"] = (
    "agent-evals/session-sampling/v2"
)
_SAMPLING_V2_DOMAIN = b"agent-evals/session-sampling/v2\0"
_CAMPAIGN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SessionSamplingMetadataV2(BaseModel):
    """Population-aware envelope over the historical v1 attempt provenance.

    V1 remains the exact sampling/randomness/stopping record emitted by the existing session runner.
    V2 adds explicit population provenance and binds both layers to the campaign, subject and
    scenario. The root is an integrity value only; it is not authentication or proof that the
    referenced population was sampled representatively.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/session-sampling/v2"] = _SAMPLING_V2_SCHEMA
    campaign_id: str = Field(min_length=1, max_length=128)
    subject_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempt_provenance: SessionSamplingMetadata
    population_provenance: PopulationProvenance
    metadata_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        if _CAMPAIGN_ID_RE.fullmatch(self.campaign_id) is None:
            raise ValueError("session-sampling v2 campaign_id is not canonical")
        expected = _metadata_root(self.model_dump(mode="json", exclude={"metadata_root"}))
        if not hmac.compare_digest(expected, self.metadata_root):
            raise ValueError("session-sampling v2 root does not match canonical metadata")
        return self

    @classmethod
    def from_session(
        cls,
        session: EvaluationSessionResult,
        *,
        population_provenance: PopulationProvenance,
    ) -> SessionSamplingMetadataV2:
        """Bind predeclared population provenance to one fully validated modern session."""
        session.validate()
        if session.campaign_id is None:
            raise PopulationProvenanceError(
                "session-sampling v2 requires a campaign identity"
            )
        if session.sampling_metadata is None:
            raise PopulationProvenanceError(
                "session-sampling v2 requires historical v1 attempt provenance"
            )
        population = validate_population_provenance(population_provenance)
        attempt = SessionSamplingMetadata.model_validate(
            session.sampling_metadata.model_dump(mode="json")
        )
        unsigned: dict[str, Any] = {
            "schema_version": _SAMPLING_V2_SCHEMA,
            "campaign_id": session.campaign_id,
            "subject_identity": session.subject_identity,
            "scenario_identity": session.scenario_identity,
            "attempt_provenance": attempt.model_dump(mode="json"),
            "population_provenance": population.model_dump(mode="json"),
        }
        return cls.model_validate({**unsigned, "metadata_root": _metadata_root(unsigned)})

    def validate_against_session(self, session: EvaluationSessionResult) -> None:
        """Re-derive the v2 envelope relation to the finalized session."""
        session.validate()
        if session.campaign_id is None or session.sampling_metadata is None:
            raise PopulationProvenanceError(
                "session-sampling v2 cannot bind a legacy session without campaign/sampling data"
            )
        if self.campaign_id != session.campaign_id:
            raise PopulationProvenanceError(
                "session-sampling v2 campaign does not match finalized session"
            )
        if not hmac.compare_digest(self.subject_identity, session.subject_identity):
            raise PopulationProvenanceError(
                "session-sampling v2 subject does not match finalized session"
            )
        if not hmac.compare_digest(self.scenario_identity, session.scenario_identity):
            raise PopulationProvenanceError(
                "session-sampling v2 scenario does not match finalized session"
            )
        expected_attempt = SessionSamplingMetadata.model_validate(
            session.sampling_metadata.model_dump(mode="json")
        )
        if self.attempt_provenance != expected_attempt:
            raise PopulationProvenanceError(
                "session-sampling v2 attempt provenance does not match finalized session"
            )
        try:
            validate_population_provenance(self.population_provenance)
        except PopulationProvenanceError as exc:
            raise PopulationProvenanceError(
                "session-sampling v2 population provenance is invalid"
            ) from exc


def _metadata_root(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_SAMPLING_V2_DOMAIN + canonical).hexdigest()
