"""Population-aware Assurance Report v7 envelope."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.assurance.report import AssuranceReport
from agent_evals.contracts.models import EvaluationScenario
from agent_evals.gates.release import ReleasePolicy
from agent_evals.runtime.population_session import PopulationBoundSessionResult
from agent_evals.runtime.sampling_v2 import SessionSamplingMetadataV2

_REPORT_SCHEMA: Literal["agent-evals/assurance-report/v7"] = "agent-evals/assurance-report/v7"
_REPORT_DOMAIN = b"agent-evals/assurance-report/v7\0"


class AssuranceReportV7(BaseModel):
    """Population-aware envelope over the fully self-validating v6 report.

    V7 deliberately nests the exact v6 predecessor rather than silently changing v6 semantics.
    The predecessor continues to rederive trial/reliability/release claims. V7 adds only the
    population-aware v2 statistical envelope and a new domain-separated root binding both layers.

    Neither the v7 root nor nested population/frame identities are signatures, authentication,
    attestation, or proof of representative/unbiased sampling, stationarity, exchangeability, or
    IID behavior.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/assurance-report/v7"] = _REPORT_SCHEMA
    predecessor_report: AssuranceReport
    session_sampling: SessionSamplingMetadataV2
    report_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_session(
        cls,
        result: PopulationBoundSessionResult,
        *,
        scenario: EvaluationScenario,
        release_policy: ReleasePolicy,
    ) -> AssuranceReportV7:
        result.validate()
        predecessor = AssuranceReport.from_session(
            result.session,
            scenario=scenario,
            release_policy=release_policy,
        )
        sampling = SessionSamplingMetadataV2.model_validate(
            result.sampling_metadata.model_dump(mode="json")
        )
        _validate_cross_layer_binding(predecessor, sampling)
        unsigned: dict[str, Any] = {
            "schema_version": _REPORT_SCHEMA,
            "predecessor_report": predecessor.model_dump(mode="json"),
            "session_sampling": sampling.model_dump(mode="json"),
        }
        return cls.model_validate({**unsigned, "report_root": _report_root(unsigned)})

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        _validate_cross_layer_binding(self.predecessor_report, self.session_sampling)
        expected = _report_root(self.model_dump(mode="json", exclude={"report_root"}))
        if not hmac.compare_digest(expected, self.report_root):
            raise ValueError("assurance-report v7 root does not match report content")
        return self

    @property
    def population_provenance(self):  # type: ignore[no-untyped-def]
        return self.session_sampling.population_provenance

    @property
    def gate(self):  # type: ignore[no-untyped-def]
        return self.predecessor_report.gate

    @property
    def reliability(self):  # type: ignore[no-untyped-def]
        return self.predecessor_report.reliability

    @property
    def trials(self):  # type: ignore[no-untyped-def]
        return self.predecessor_report.trials


def _validate_cross_layer_binding(
    predecessor: AssuranceReport,
    sampling: SessionSamplingMetadataV2,
) -> None:
    provenance = predecessor.session_provenance
    if sampling.campaign_id != provenance.campaign_id:
        raise ValueError("assurance-report v7 sampling campaign does not match predecessor")
    if not hmac.compare_digest(sampling.subject_identity, predecessor.subject_identity):
        raise ValueError("assurance-report v7 sampling subject does not match predecessor")
    if not hmac.compare_digest(sampling.scenario_identity, predecessor.scenario_identity):
        raise ValueError("assurance-report v7 sampling scenario does not match predecessor")
    if sampling.attempt_provenance != provenance.sampling_metadata:
        raise ValueError(
            "assurance-report v7 attempt provenance does not match predecessor report"
        )


def _report_root(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_REPORT_DOMAIN + canonical).hexdigest()
