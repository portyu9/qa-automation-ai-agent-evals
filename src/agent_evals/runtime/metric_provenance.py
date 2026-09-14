"""Evaluator-owned provenance for adapter-reported token and cost telemetry.

The historical ``TrialEvidence/v2`` envelope already binds terminal token/cost scalars into its
root.  This module deliberately does not change that schema or reinterpret its hashes.  Instead it
adds a separate versioned sidecar that states what the evaluator can actually claim about those
numbers: by default they are unverified adapter/runtime telemetry, with optional bounded source and
pricing assertions.  The sidecar root is an integrity binding, not authentication or billing
attestation.
"""

from __future__ import annotations

import hashlib
import json
import sys
from enum import StrEnum
from typing import Literal, Protocol, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.adapters.replay import EvidenceReplayAdapter
from agent_evals.evidence.models import TrialEvidence

_SCHEMA_VERSION = "agent-evals/runtime-metric-provenance/v1"
_ROOT_DOMAIN = b"agent-evals/runtime-metric-provenance/v1\0"
_MAX_SOURCE_LENGTH = 256
_MAX_VERSION_LENGTH = 128


class MetricAuthority(StrEnum):
    """Authority granted to terminal token/cost telemetry."""

    UNVERIFIED_TELEMETRY = "unverified_telemetry"


class MetricOrigin(StrEnum):
    """How the current evaluator obtained the historical terminal metric scalars."""

    ADAPTER_BOUNDARY = "adapter_boundary"
    HISTORICAL_REPLAY = "historical_replay"


class PricingProvenanceStatus(StrEnum):
    """Whether a pricing basis is available for an adapter-reported cost scalar."""

    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    ADAPTER_ASSERTED = "adapter_asserted"


class MetricProvenanceError(ValueError):
    """An adapter metric-source assertion cannot be accepted safely."""


class AdapterMetricProvenanceAssertion(BaseModel):
    """Bounded source metadata an adapter may report without acquiring evaluator authority.

    Adapters cannot choose an authority class.  Even a fully populated assertion remains nested
    beneath :class:`MetricAuthority.UNVERIFIED_TELEMETRY` in the evaluator-owned sidecar.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    token_source: str | None = None
    token_source_version: str | None = None
    pricing_status: PricingProvenanceStatus = PricingProvenanceStatus.UNKNOWN
    pricing_source: str | None = None
    pricing_version: str | None = None

    @field_validator("token_source", "pricing_source")
    @classmethod
    def validate_source(cls, value: str | None) -> str | None:
        return _bounded_text(value, field_name="metric source", maximum=_MAX_SOURCE_LENGTH)

    @field_validator("token_source_version", "pricing_version")
    @classmethod
    def validate_version(cls, value: str | None) -> str | None:
        return _bounded_text(value, field_name="metric version", maximum=_MAX_VERSION_LENGTH)

    @model_validator(mode="after")
    def validate_relations(self) -> Self:
        if self.token_source is None and self.token_source_version is not None:
            raise ValueError("token source version requires a token source")
        if self.pricing_status is PricingProvenanceStatus.ADAPTER_ASSERTED:
            if self.pricing_source is None or self.pricing_version is None:
                raise ValueError("adapter-asserted pricing requires source and version")
        elif self.pricing_source is not None or self.pricing_version is not None:
            raise ValueError("pricing source/version require adapter_asserted pricing status")
        return self


class RuntimeMetricProvenance(BaseModel):
    """Evaluator-owned sidecar binding terminal token/cost telemetry to its exact evidence root."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    schema_version: Literal["agent-evals/runtime-metric-provenance/v1"] = (
        "agent-evals/runtime-metric-provenance/v1"
    )
    trial_id: str = Field(min_length=1)
    evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_adapter_name: str
    origin: MetricOrigin
    authority: Literal[MetricAuthority.UNVERIFIED_TELEMETRY] = MetricAuthority.UNVERIFIED_TELEMETRY
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    estimated_cost_usd: float = Field(ge=0.0, allow_inf_nan=False, strict=True)
    token_source: str | None = None
    token_source_version: str | None = None
    pricing_status: PricingProvenanceStatus = PricingProvenanceStatus.UNKNOWN
    pricing_source: str | None = None
    pricing_version: str | None = None
    provenance_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("runtime_adapter_name")
    @classmethod
    def validate_adapter_name(cls, value: str) -> str:
        validated = _bounded_text(
            value,
            field_name="runtime adapter name",
            maximum=_MAX_SOURCE_LENGTH,
        )
        if validated is None:
            raise ValueError("runtime adapter name is required")
        return validated

    @field_validator("token_source", "pricing_source")
    @classmethod
    def validate_source(cls, value: str | None) -> str | None:
        return _bounded_text(value, field_name="metric source", maximum=_MAX_SOURCE_LENGTH)

    @field_validator("token_source_version", "pricing_version")
    @classmethod
    def validate_version(cls, value: str | None) -> str | None:
        return _bounded_text(value, field_name="metric version", maximum=_MAX_VERSION_LENGTH)

    @model_validator(mode="after")
    def validate_relations_and_root(self) -> Self:
        if self.token_source is None and self.token_source_version is not None:
            raise ValueError("token source version requires a token source")
        if self.pricing_status is PricingProvenanceStatus.ADAPTER_ASSERTED:
            if self.pricing_source is None or self.pricing_version is None:
                raise ValueError("adapter-asserted pricing requires source and version")
        elif self.pricing_source is not None or self.pricing_version is not None:
            raise ValueError("pricing source/version require adapter_asserted pricing status")
        if self.origin is MetricOrigin.HISTORICAL_REPLAY and (
            self.token_source is not None
            or self.token_source_version is not None
            or self.pricing_status is not PricingProvenanceStatus.UNKNOWN
            or self.pricing_source is not None
            or self.pricing_version is not None
        ):
            raise ValueError(
                "historical v2 replay cannot invent original token or pricing provenance"
            )
        expected = _provenance_root(self._unsigned_payload())
        if self.provenance_root != expected:
            raise ValueError("runtime metric provenance root does not match bound material")
        return self

    @classmethod
    def create(
        cls,
        evidence: TrialEvidence,
        *,
        runtime_adapter_name: str,
        origin: MetricOrigin,
        assertion: AdapterMetricProvenanceAssertion | None,
    ) -> RuntimeMetricProvenance:
        if origin is MetricOrigin.HISTORICAL_REPLAY:
            assertion = None
        material = {
            "schema_version": _SCHEMA_VERSION,
            "trial_id": evidence.trial_id,
            "evidence_root": evidence.evidence_root,
            "runtime_adapter_name": runtime_adapter_name,
            "origin": origin,
            "authority": MetricAuthority.UNVERIFIED_TELEMETRY,
            "input_tokens": evidence.input_tokens,
            "output_tokens": evidence.output_tokens,
            "estimated_cost_usd": evidence.estimated_cost_usd,
            "token_source": None if assertion is None else assertion.token_source,
            "token_source_version": None if assertion is None else assertion.token_source_version,
            "pricing_status": (
                PricingProvenanceStatus.UNKNOWN if assertion is None else assertion.pricing_status
            ),
            "pricing_source": None if assertion is None else assertion.pricing_source,
            "pricing_version": None if assertion is None else assertion.pricing_version,
        }
        return cls.model_validate({**material, "provenance_root": _provenance_root(material)})

    def validate_against_evidence(self, evidence: TrialEvidence) -> None:
        """Revalidate the sidecar and its exact relation to one finalized evidence envelope."""
        validated = type(self).model_validate(self.model_dump(mode="python"))
        if validated.trial_id != evidence.trial_id:
            raise MetricProvenanceError("metric provenance trial identity does not match evidence")
        if validated.evidence_root != evidence.evidence_root:
            raise MetricProvenanceError("metric provenance evidence root does not match evidence")
        if (
            validated.input_tokens != evidence.input_tokens
            or validated.output_tokens != evidence.output_tokens
            or validated.estimated_cost_usd != evidence.estimated_cost_usd
        ):
            raise MetricProvenanceError("metric provenance values do not match terminal evidence")

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "trial_id": self.trial_id,
            "evidence_root": self.evidence_root,
            "runtime_adapter_name": self.runtime_adapter_name,
            "origin": self.origin,
            "authority": self.authority,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "token_source": self.token_source,
            "token_source_version": self.token_source_version,
            "pricing_status": self.pricing_status,
            "pricing_source": self.pricing_source,
            "pricing_version": self.pricing_version,
        }


def resolve_metric_provenance(
    adapter: object,
) -> tuple[str, MetricOrigin, AdapterMetricProvenanceAssertion | None]:
    """Resolve bounded metric source metadata without granting the adapter authority.

    Exact evidence replay is handled first and can never upgrade historical v2 scalars.  Known
    built-in OpenAI adapter classes receive a fixed SDK usage-surface label only when the runtime
    class object is the canonical class exported by its already-loaded module.  Other adapters may
    expose ``metric_provenance_assertion``; the evaluator revalidates that object strictly.
    """
    runtime_adapter_name = _adapter_name(adapter)
    if type(adapter) is EvidenceReplayAdapter:
        return runtime_adapter_name, MetricOrigin.HISTORICAL_REPLAY, None

    if _is_builtin_openai_adapter(type(adapter)):
        return (
            runtime_adapter_name,
            MetricOrigin.ADAPTER_BOUNDARY,
            AdapterMetricProvenanceAssertion(
                token_source="openai-agents-sdk:context_wrapper.usage",
                pricing_status=PricingProvenanceStatus.UNAVAILABLE,
            ),
        )

    try:
        raw_assertion = getattr(adapter, "metric_provenance_assertion", None)
    except Exception as exc:  # pragma: no cover - defensive adapter boundary
        raise MetricProvenanceError(
            "adapter metric provenance assertion could not be read"
        ) from exc
    if raw_assertion is None:
        return runtime_adapter_name, MetricOrigin.ADAPTER_BOUNDARY, None
    try:
        assertion = AdapterMetricProvenanceAssertion.model_validate(raw_assertion)
    except Exception as exc:
        raise MetricProvenanceError("adapter metric provenance assertion is invalid") from exc
    return runtime_adapter_name, MetricOrigin.ADAPTER_BOUNDARY, assertion


class _NamedAdapter(Protocol):
    @property
    def name(self) -> str: ...


def _adapter_name(adapter: object) -> str:
    try:
        name = cast(_NamedAdapter, adapter).name
    except Exception as exc:  # pragma: no cover - defensive adapter boundary
        raise MetricProvenanceError("runtime adapter name could not be read") from exc
    validated = _bounded_text(
        name,
        field_name="runtime adapter name",
        maximum=_MAX_SOURCE_LENGTH,
    )
    if validated is None:
        raise MetricProvenanceError("runtime adapter name is required")
    return validated


def _is_builtin_openai_adapter(adapter_type: type[object]) -> bool:
    identity = (adapter_type.__module__, adapter_type.__name__)
    if identity not in _BUILTIN_OPENAI_ADAPTER_IDENTITIES:
        return False
    module = sys.modules.get(adapter_type.__module__)
    return module is not None and getattr(module, adapter_type.__name__, None) is adapter_type


_BUILTIN_OPENAI_ADAPTER_IDENTITIES = frozenset(
    {
        ("agent_evals.adapters.openai_agents", "OpenAIAgentsAdapter"),
        ("agent_evals.adapters.openai_handoff_authority", "OpenAIAgentsHandoffAuthorityAdapter"),
        ("agent_evals.adapters.openai_hitl_approval", "OpenAIAgentsHITLApprovalAdapter"),
        (
            "agent_evals.adapters.openai_mcp_tool_error_recovery",
            "OpenAIAgentsMCPToolErrorRecoveryAdapter",
        ),
        (
            "agent_evals.adapters.openai_mcp_tool_identity_drift",
            "OpenAIAgentsMCPToolIdentityDriftAdapter",
        ),
        (
            "agent_evals.adapters.openai_mcp_tool_metadata",
            "OpenAIAgentsMCPToolMetadataAdapter",
        ),
        (
            "agent_evals.adapters.openai_mcp_tool_result",
            "OpenAIAgentsMCPToolResultAdapter",
        ),
        (
            "agent_evals.adapters.openai_mcp_tool_schema_drift",
            "OpenAIAgentsMCPToolSchemaDriftAdapter",
        ),
        (
            "agent_evals.adapters.openai_mcp_tool_stale_cache",
            "OpenAIAgentsMCPToolStaleCacheAdapter",
        ),
        ("agent_evals.adapters.openai_retrieval", "OpenAIAgentsRetrievalAdapter"),
        (
            "agent_evals.adapters.openai_side_effect_idempotency",
            "OpenAIAgentsSideEffectIdempotencyAdapter",
        ),
    }
)


def _bounded_text(value: object, *, field_name: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or None")
    if not value or len(value) > maximum or value.strip() != value:
        raise ValueError(f"{field_name} must contain 1..{maximum} trimmed characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


def _provenance_root(material: dict[str, object]) -> str:
    canonical = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(_ROOT_DOMAIN + canonical).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"unsupported metric provenance value: {type(value).__name__}")
