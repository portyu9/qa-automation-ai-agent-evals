"""Integrity-bound provenance for adapter-reported token and cost telemetry.

This module deliberately does not alter ``TrialEvidence/v2``. Historical evidence keeps its exact
schema/root semantics while callers can bind those existing scalar values to an explicit,
evaluator-owned description of where the telemetry claim came from.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.evidence.models import TrialEvidence

_SCHEMA_VERSION = "agent-evals/runtime-metric-provenance/v1"
_ROOT_DOMAIN = b"agent-evals/runtime-metric-provenance/v1\0"
_MAX_LABEL_LENGTH = 256


class MetricTelemetryAuthority(StrEnum):
    """Authority class for runtime metric values in this provenance schema."""

    UNVERIFIED = "unverified_telemetry"


class MetricTelemetrySource(StrEnum):
    """Evaluator classification of the path that supplied the recorded telemetry."""

    UNKNOWN = "unknown"
    ADAPTER_ASSERTED = "adapter_asserted"
    OPENAI_AGENTS_SDK_USAGE = "openai_agents_sdk_usage"
    HISTORICAL_EVIDENCE_REPLAY = "historical_evidence_replay"


class PricingProvenanceStatus(StrEnum):
    """Whether a bounded pricing-basis assertion accompanied the recorded cost scalar."""

    UNKNOWN = "unknown"
    ADAPTER_ASSERTED = "adapter_asserted"


class RuntimeMetricSourceAssertion(BaseModel):
    """Bounded adapter assertion about telemetry and optional pricing source metadata.

    Validation makes the assertion safe to persist and compare. It does not authenticate the
    adapter, provider, tokenizer, price sheet, account, or bill.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    source_name: str = Field(min_length=1, max_length=_MAX_LABEL_LENGTH)
    source_version: str | None = Field(default=None, min_length=1, max_length=_MAX_LABEL_LENGTH)
    pricing_source: str | None = Field(default=None, min_length=1, max_length=_MAX_LABEL_LENGTH)
    pricing_version: str | None = Field(default=None, min_length=1, max_length=_MAX_LABEL_LENGTH)

    @model_validator(mode="after")
    def validate_labels(self) -> RuntimeMetricSourceAssertion:
        for name in ("source_name", "source_version", "pricing_source", "pricing_version"):
            value = getattr(self, name)
            if value is not None and value != value.strip():
                raise ValueError(f"{name} must not contain surrounding whitespace")
        if (self.pricing_source is None) != (self.pricing_version is None):
            raise ValueError("pricing_source and pricing_version must be supplied together")
        return self


@runtime_checkable
class RuntimeMetricProvenanceProvider(Protocol):
    """Optional adapter surface for bounded telemetry-source assertions.

    Implementing this protocol never grants stronger metric authority. The evaluator records any
    accepted assertion under ``UNVERIFIED`` authority only.
    """

    @property
    def runtime_metric_provenance_assertion(self) -> RuntimeMetricSourceAssertion: ...


class RuntimeMetricProvenance(BaseModel):
    """Evaluator-owned binding from final evidence to unverified token/cost telemetry provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    schema_version: str = Field(
        default=_SCHEMA_VERSION,
        pattern=r"^agent-evals/runtime-metric-provenance/v1$",
    )
    authority: MetricTelemetryAuthority = MetricTelemetryAuthority.UNVERIFIED
    source: MetricTelemetrySource
    runtime_adapter_name: str = Field(min_length=1, max_length=_MAX_LABEL_LENGTH)
    source_assertion: RuntimeMetricSourceAssertion | None = None
    pricing_status: PricingProvenanceStatus
    trial_id: str = Field(min_length=1)
    evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    estimated_cost_usd: float = Field(ge=0.0, allow_inf_nan=False, strict=True)
    provenance_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_claim_shape(self) -> RuntimeMetricProvenance:
        if self.runtime_adapter_name != self.runtime_adapter_name.strip():
            raise ValueError("runtime_adapter_name must not contain surrounding whitespace")
        if self.authority is not MetricTelemetryAuthority.UNVERIFIED:
            raise ValueError("runtime metric provenance v1 cannot grant verified metric authority")

        if self.source is MetricTelemetrySource.ADAPTER_ASSERTED:
            if self.source_assertion is None:
                raise ValueError("adapter-asserted metric source requires its bounded assertion")
        elif (
            self.source_assertion is not None
            and self.source is not MetricTelemetrySource.OPENAI_AGENTS_SDK_USAGE
        ):
            raise ValueError("metric source assertion is not valid for this source classification")

        has_pricing = (
            self.source_assertion is not None and self.source_assertion.pricing_source is not None
        )
        expected_pricing = (
            PricingProvenanceStatus.ADAPTER_ASSERTED
            if has_pricing
            else PricingProvenanceStatus.UNKNOWN
        )
        if self.pricing_status is not expected_pricing:
            raise ValueError("pricing provenance status does not match the bounded source assertion")

        if self.provenance_root != self._computed_root():
            raise ValueError("runtime metric provenance root does not match canonical material")
        return self

    @classmethod
    def create(
        cls,
        *,
        evidence: TrialEvidence,
        runtime_adapter_name: str,
        source: MetricTelemetrySource,
        source_assertion: RuntimeMetricSourceAssertion | None = None,
    ) -> RuntimeMetricProvenance:
        assertion = (
            RuntimeMetricSourceAssertion.model_validate(source_assertion.model_dump(mode="json"))
            if source_assertion is not None
            else None
        )

        # The exact built-in OpenAI adapter reads token counts from the SDK usage surface only on a
        # completed SDK result. If no token telemetry was retained, do not claim that source merely
        # because the adapter type is capable of producing it; downgrade to explicit unknown.
        if (
            source is MetricTelemetrySource.OPENAI_AGENTS_SDK_USAGE
            and evidence.input_tokens == 0
            and evidence.output_tokens == 0
        ):
            source = MetricTelemetrySource.UNKNOWN
            assertion = None

        pricing_status = (
            PricingProvenanceStatus.ADAPTER_ASSERTED
            if assertion is not None and assertion.pricing_source is not None
            else PricingProvenanceStatus.UNKNOWN
        )
        unsigned: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "authority": MetricTelemetryAuthority.UNVERIFIED.value,
            "source": source.value,
            "runtime_adapter_name": runtime_adapter_name,
            "source_assertion": None if assertion is None else assertion.model_dump(mode="json"),
            "pricing_status": pricing_status.value,
            "trial_id": evidence.trial_id,
            "evidence_root": evidence.evidence_root,
            "input_tokens": evidence.input_tokens,
            "output_tokens": evidence.output_tokens,
            "estimated_cost_usd": evidence.estimated_cost_usd,
        }
        return cls(
            **unsigned,
            provenance_root=_root(unsigned),
        )

    def validate_against_evidence(self, evidence: TrialEvidence) -> None:
        """Fail closed if the provenance no longer describes the exact final evidence."""
        if self.trial_id != evidence.trial_id:
            raise ValueError("runtime metric provenance trial identity does not match evidence")
        if self.evidence_root != evidence.evidence_root:
            raise ValueError("runtime metric provenance evidence root does not match evidence")
        if self.input_tokens != evidence.input_tokens:
            raise ValueError("runtime metric provenance input token count does not match evidence")
        if self.output_tokens != evidence.output_tokens:
            raise ValueError("runtime metric provenance output token count does not match evidence")
        if self.estimated_cost_usd != evidence.estimated_cost_usd:
            raise ValueError("runtime metric provenance cost does not match evidence")

    def _computed_root(self) -> str:
        unsigned = self.model_dump(mode="json", exclude={"provenance_root"})
        return _root(unsigned)


def snapshot_adapter_metric_assertion(adapter: object) -> RuntimeMetricSourceAssertion | None:
    """Read and validate an optional adapter assertion exactly once before subject execution.

    Absence is valid and means source/pricing provenance is unknown. A present but malformed
    assertion is evaluator uncertainty and must be handled fail-closed by the caller.
    """
    try:
        raw = getattr(adapter, "runtime_metric_provenance_assertion")
    except AttributeError:
        return None
    except Exception as exc:
        raise ValueError("adapter runtime metric provenance assertion is unavailable") from exc
    try:
        if isinstance(raw, RuntimeMetricSourceAssertion):
            return RuntimeMetricSourceAssertion.model_validate(raw.model_dump(mode="json"))
        return RuntimeMetricSourceAssertion.model_validate(raw)
    except Exception as exc:
        raise ValueError("adapter runtime metric provenance assertion is invalid") from exc


def classify_metric_source(
    adapter: object,
    assertion: RuntimeMetricSourceAssertion | None,
) -> tuple[MetricTelemetrySource, RuntimeMetricSourceAssertion | None]:
    """Classify source without allowing an adapter assertion to self-upgrade authority."""
    from agent_evals.adapters.replay import EvidenceReplayAdapter

    if type(adapter) is EvidenceReplayAdapter:
        return MetricTelemetrySource.HISTORICAL_EVIDENCE_REPLAY, None

    # The evaluator recognizes this exact built-in producer path because its implementation reads
    # token counts from ``result.context_wrapper.usage``. This is still only unverified telemetry.
    from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter

    if type(adapter) is OpenAIAgentsAdapter:
        builtin = RuntimeMetricSourceAssertion(
            source_name="openai-agents-sdk:result.context_wrapper.usage",
        )
        if assertion is not None:
            # An exact built-in adapter currently has no supported pricing assertion surface.
            raise ValueError("built-in OpenAI metric provenance cannot be overridden by assertion")
        return MetricTelemetrySource.OPENAI_AGENTS_SDK_USAGE, builtin

    if assertion is not None:
        return MetricTelemetrySource.ADAPTER_ASSERTED, assertion
    return MetricTelemetrySource.UNKNOWN, None


def _root(material: dict[str, Any]) -> str:
    canonical = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_ROOT_DOMAIN + canonical).hexdigest()
