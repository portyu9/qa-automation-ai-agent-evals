"""Deterministic data minimization before durable TrialEvidence persistence.

This module deliberately separates durable-evidence minimization from operational log suppression.
It recognizes a bounded set of credential forms and operator-declared PII paths, rewrites only
explicitly redaction-safe evidence surfaces, and fails closed when classified material intersects
authority-bearing/critical event payloads.

The policy does not claim complete PII discovery, de-identification, legal compliance, consent,
residency, or authentication. Redaction markers and receipt roots never retain the classified raw
values or fingerprints derived from those values.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence

_POLICY_SCHEMA: Literal["agent-evals/evidence-minimization-policy/v1"] = (
    "agent-evals/evidence-minimization-policy/v1"
)
_RECEIPT_SCHEMA: Literal["agent-evals/evidence-minimization-receipt/v1"] = (
    "agent-evals/evidence-minimization-receipt/v1"
)
_POLICY_DOMAIN = b"agent-evals/evidence-minimization-policy/v1\x00"
_RECEIPT_DOMAIN = b"agent-evals/evidence-minimization-receipt/v1\x00"
_MAX_DECLARED_PATHS = 64
_MAX_PATH_UTF8_BYTES = 512
_MAX_PATH_SEGMENTS = 32
_MAX_TRAVERSAL_NODES = 100_000
_MAX_REDACTIONS = 16_384

_CREDENTIAL_MARKER = "[REDACTED:CREDENTIAL]"
_OPERATOR_PII_MARKER = "[REDACTED:OPERATOR_PII]"

_SENSITIVE_KEY_PARTS = (
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "privatekey",
    "refreshtoken",
    "secret",
    "setcookie",
    "token",
)
_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}\b"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"(?i)\bgithub_pat_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|secret|password)"
        r"\s*[:=]\s*\S{8,}"
    ),
)

_REDACTABLE_EVENT_KINDS = frozenset(
    {
        EvidenceKind.STATE,
        EvidenceKind.OUTPUT,
        EvidenceKind.EVALUATION_ERROR,
        EvidenceKind.RUNTIME_ERROR,
    }
)


class SensitiveDataClass(StrEnum):
    """Bounded classification labels emitted by the persistence policy."""

    CREDENTIAL = "credential"
    OPERATOR_PII = "operator_pii"


class EvidenceMinimizationError(RuntimeError):
    """Evidence cannot be safely minimized under the configured persistence policy."""


class SensitiveMatchCount(BaseModel):
    """Count of one classification without retaining classified material."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    classification: SensitiveDataClass
    count: int = Field(ge=0, strict=True)


class EvidenceMinimizationPolicy(BaseModel):
    """Versioned deterministic policy for one durable persistence boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-minimization-policy/v1"] = _POLICY_SCHEMA
    credential_heuristics: Literal[True] = True
    operator_pii_paths: tuple[str, ...] = Field(default=(), max_length=_MAX_DECLARED_PATHS)
    max_traversal_nodes: int = Field(
        default=50_000,
        gt=0,
        le=_MAX_TRAVERSAL_NODES,
        strict=True,
    )
    max_redactions: int = Field(default=4_096, gt=0, le=_MAX_REDACTIONS, strict=True)

    @field_validator("operator_pii_paths", mode="before")
    @classmethod
    def validate_operator_paths(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("operator PII paths must be a bounded materialized collection")
        if len(value) > _MAX_DECLARED_PATHS:
            raise ValueError("operator PII path count exceeds configured policy ceiling")

        parsed: list[_ParsedPath] = []
        canonical: list[str] = []
        for raw_path in value:
            if type(raw_path) is not str:
                raise ValueError("operator PII paths must be exact strings")
            item = _parse_operator_path(raw_path)
            parsed.append(item)
            canonical.append(item.canonical)

        if len(set(canonical)) != len(canonical):
            raise ValueError("operator PII paths must be unique")

        for index, left in enumerate(parsed):
            for right in parsed[index + 1 :]:
                if _paths_overlap(left, right):
                    raise ValueError("operator PII paths must not overlap")

        return tuple(sorted(canonical))

    @property
    def policy_id(self) -> str:
        material = _canonical_json_bytes(self.model_dump(mode="json"))
        return hashlib.sha256(_POLICY_DOMAIN + material).hexdigest()


class EvidenceMinimizationReceipt(BaseModel):
    """Integrity receipt over policy identity, bounded counts, and the resulting evidence root."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-minimization-receipt/v1"] = _RECEIPT_SCHEMA
    policy_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    classifications: tuple[SensitiveMatchCount, ...] = Field(min_length=2, max_length=2)
    result_evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        policy: EvidenceMinimizationPolicy,
        counts: _RedactionCounts,
        result_evidence_root: str,
    ) -> Self:
        classifications = counts.as_models()
        material = {
            "schema_version": _RECEIPT_SCHEMA,
            "policy_id": policy.policy_id,
            "classifications": [item.model_dump(mode="json") for item in classifications],
            "result_evidence_root": result_evidence_root,
        }
        return cls(
            policy_id=policy.policy_id,
            classifications=classifications,
            result_evidence_root=result_evidence_root,
            receipt_root=hashlib.sha256(
                _RECEIPT_DOMAIN + _canonical_json_bytes(material)
            ).hexdigest(),
        )

    @model_validator(mode="after")
    def verify_receipt(self) -> Self:
        expected_classes = tuple(SensitiveDataClass)
        actual_classes = tuple(item.classification for item in self.classifications)
        if actual_classes != expected_classes:
            raise ValueError("minimization classifications must be complete and canonical")
        material = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "classifications": [item.model_dump(mode="json") for item in self.classifications],
            "result_evidence_root": self.result_evidence_root,
        }
        expected = hashlib.sha256(_RECEIPT_DOMAIN + _canonical_json_bytes(material)).hexdigest()
        if expected != self.receipt_root:
            raise ValueError("evidence minimization receipt root mismatch")
        return self


@dataclass(frozen=True, slots=True)
class EvidencePersistencePreparation:
    """Detached evidence plus its non-secret-bearing persistence minimization receipt."""

    evidence: TrialEvidence
    receipt: EvidenceMinimizationReceipt


@dataclass(frozen=True, slots=True)
class _ParsedPath:
    scope: Literal["final_state", "final_output", "events"]
    event_selector: int | Literal["*"] | None
    tail: tuple[str, ...]
    canonical: str


@dataclass(slots=True)
class _TraversalBudget:
    limit: int
    visited: int = 0

    def consume(self) -> None:
        self.visited += 1
        if self.visited > self.limit:
            raise EvidenceMinimizationError(
                "evidence minimization traversal exceeds configured node ceiling"
            )


@dataclass(slots=True)
class _RedactionCounts:
    credential: int = 0
    operator_pii: int = 0

    @property
    def total(self) -> int:
        return self.credential + self.operator_pii

    def add(self, classification: SensitiveDataClass, *, limit: int) -> None:
        if classification is SensitiveDataClass.CREDENTIAL:
            self.credential += 1
        else:
            self.operator_pii += 1
        if self.total > limit:
            raise EvidenceMinimizationError(
                "evidence minimization exceeds configured redaction ceiling"
            )

    def as_models(self) -> tuple[SensitiveMatchCount, ...]:
        return (
            SensitiveMatchCount(
                classification=SensitiveDataClass.CREDENTIAL,
                count=self.credential,
            ),
            SensitiveMatchCount(
                classification=SensitiveDataClass.OPERATOR_PII,
                count=self.operator_pii,
            ),
        )


def minimize_evidence_for_persistence(
    evidence: TrialEvidence,
    *,
    policy: EvidenceMinimizationPolicy | None = None,
) -> EvidencePersistencePreparation:
    """Return detached minimized evidence before any persistence identity or bytes are committed."""

    if type(evidence) is not TrialEvidence:
        raise TypeError("evidence minimization requires an exact TrialEvidence value")
    active_policy = policy or EvidenceMinimizationPolicy()
    if type(active_policy) is not EvidenceMinimizationPolicy:
        raise TypeError("evidence minimization requires an exact EvidenceMinimizationPolicy")

    snapshot = evidence.snapshot()
    budget = _TraversalBudget(active_policy.max_traversal_nodes)
    counts = _RedactionCounts()

    final_state = copy.deepcopy(snapshot.final_state)
    final_output = snapshot.final_output
    payloads = [copy.deepcopy(event.payload) for event in snapshot.events]

    parsed_paths = tuple(_parse_operator_path(path) for path in active_policy.operator_pii_paths)
    for path in parsed_paths:
        if path.scope == "final_output":
            if final_output is None:
                continue
            budget.consume()
            if _string_has_credential(final_output):
                raise EvidenceMinimizationError(
                    "operator PII classification conflicts with credential classification"
                )
            if final_output != _OPERATOR_PII_MARKER:
                final_output = _OPERATOR_PII_MARKER
            counts.add(SensitiveDataClass.OPERATOR_PII, limit=active_policy.max_redactions)
            continue

        if path.scope == "final_state":
            _redact_declared_path(
                final_state,
                path.tail,
                allow_redaction=True,
                budget=budget,
                counts=counts,
                max_redactions=active_policy.max_redactions,
            )
            continue

        selected_indexes = (
            range(len(snapshot.events)) if path.event_selector == "*" else (path.event_selector,)
        )
        for index in selected_indexes:
            if index is None or index < 0 or index >= len(snapshot.events):
                continue
            event = snapshot.events[index]
            _redact_declared_path(
                payloads[index],
                path.tail,
                allow_redaction=_event_payload_redactable(event),
                budget=budget,
                counts=counts,
                max_redactions=active_policy.max_redactions,
            )

    final_state = _transform_credentials(
        final_state,
        allow_redaction=True,
        budget=budget,
        counts=counts,
        max_redactions=active_policy.max_redactions,
    )
    if final_output is not None:
        final_output = _transform_credential_string(
            final_output,
            allow_redaction=True,
            counts=counts,
            max_redactions=active_policy.max_redactions,
        )

    minimized_events: list[EvidenceEvent] = []
    for index, event in enumerate(snapshot.events):
        minimized_payload = _transform_credentials(
            payloads[index],
            allow_redaction=_event_payload_redactable(event),
            budget=budget,
            counts=counts,
            max_redactions=active_policy.max_redactions,
        )
        minimized_events.append(
            EvidenceEvent.model_validate(
                {
                    **event.model_dump(mode="python"),
                    "payload": minimized_payload,
                }
            )
        )

    minimized = TrialEvidence.model_validate(
        {
            **snapshot.model_dump(mode="python"),
            "events": tuple(minimized_events),
            "final_state": final_state,
            "final_output": final_output,
        }
    )
    receipt = EvidenceMinimizationReceipt.create(
        policy=active_policy,
        counts=counts,
        result_evidence_root=minimized.evidence_root,
    )
    return EvidencePersistencePreparation(evidence=minimized, receipt=receipt)


def _event_payload_redactable(event: EvidenceEvent) -> bool:
    return not event.critical and event.kind in _REDACTABLE_EVENT_KINDS


def _redact_declared_path(
    root: Any,
    tail: tuple[str, ...],
    *,
    allow_redaction: bool,
    budget: _TraversalBudget,
    counts: _RedactionCounts,
    max_redactions: int,
) -> None:
    parent = root
    for segment in tail[:-1]:
        budget.consume()
        resolved = _resolve_child(parent, segment)
        if resolved is _MISSING:
            return
        parent = resolved

    budget.consume()
    segment = tail[-1]
    target = _resolve_child(parent, segment)
    if target is _MISSING:
        return
    if not allow_redaction:
        raise EvidenceMinimizationError(
            "operator PII path intersects an authority-bearing event payload"
        )
    if _contains_credential(target, key_hint=segment, budget=budget):
        raise EvidenceMinimizationError(
            "operator PII classification conflicts with credential classification"
        )

    if target != _OPERATOR_PII_MARKER:
        _replace_child(parent, segment, _OPERATOR_PII_MARKER)
    counts.add(SensitiveDataClass.OPERATOR_PII, limit=max_redactions)


_MISSING = object()


def _resolve_child(parent: Any, segment: str) -> Any:
    if isinstance(parent, dict):
        return parent.get(segment, _MISSING)
    if isinstance(parent, list):
        index = _canonical_list_index(segment)
        if index is None:
            raise EvidenceMinimizationError(
                "operator PII path is incompatible with JSON container shape"
            )
        if index >= len(parent):
            return _MISSING
        return parent[index]
    raise EvidenceMinimizationError("operator PII path traverses a non-container JSON value")


def _replace_child(parent: Any, segment: str, replacement: str) -> None:
    if isinstance(parent, dict):
        parent[segment] = replacement
        return
    if isinstance(parent, list):
        index = _canonical_list_index(segment)
        if index is None or index >= len(parent):
            raise EvidenceMinimizationError(
                "operator PII path is incompatible with JSON container shape"
            )
        parent[index] = replacement
        return
    raise EvidenceMinimizationError("operator PII path cannot replace a non-container JSON value")


def _canonical_list_index(segment: str) -> int | None:
    if not segment or not segment.isascii() or not segment.isdigit():
        return None
    if len(segment) > 1 and segment.startswith("0"):
        return None
    return int(segment)


def _transform_credentials(
    value: Any,
    *,
    allow_redaction: bool,
    budget: _TraversalBudget,
    counts: _RedactionCounts,
    max_redactions: int,
) -> Any:
    budget.consume()

    if isinstance(value, dict):
        transformed: dict[str, Any] = {}
        for key, child in value.items():
            if _sensitive_key(key):
                if not allow_redaction and child != _CREDENTIAL_MARKER:
                    raise EvidenceMinimizationError(
                        "credential material intersects an authority-bearing event payload"
                    )
                transformed[key] = _CREDENTIAL_MARKER
                counts.add(SensitiveDataClass.CREDENTIAL, limit=max_redactions)
                continue
            transformed[key] = _transform_credentials(
                child,
                allow_redaction=allow_redaction,
                budget=budget,
                counts=counts,
                max_redactions=max_redactions,
            )
        return transformed

    if isinstance(value, list):
        return [
            _transform_credentials(
                item,
                allow_redaction=allow_redaction,
                budget=budget,
                counts=counts,
                max_redactions=max_redactions,
            )
            for item in value
        ]

    if isinstance(value, str):
        return _transform_credential_string(
            value,
            allow_redaction=allow_redaction,
            counts=counts,
            max_redactions=max_redactions,
        )

    if value is None or type(value) in (bool, int, float):
        return value
    raise EvidenceMinimizationError("evidence minimization encountered an unsupported JSON value")


def _transform_credential_string(
    value: str,
    *,
    allow_redaction: bool,
    counts: _RedactionCounts,
    max_redactions: int,
) -> str:
    if value == _CREDENTIAL_MARKER:
        counts.add(SensitiveDataClass.CREDENTIAL, limit=max_redactions)
        return value
    if not _string_has_credential(value):
        return value
    if not allow_redaction:
        raise EvidenceMinimizationError(
            "credential material intersects an authority-bearing event payload"
        )
    counts.add(SensitiveDataClass.CREDENTIAL, limit=max_redactions)
    return _CREDENTIAL_MARKER


def _contains_credential(
    value: Any,
    *,
    key_hint: str | None,
    budget: _TraversalBudget,
) -> bool:
    budget.consume()
    if key_hint is not None and _sensitive_key(key_hint):
        return True
    if isinstance(value, dict):
        return any(
            _contains_credential(child, key_hint=key, budget=budget) for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_credential(child, key_hint=None, budget=budget) for child in value)
    if isinstance(value, str):
        return value == _CREDENTIAL_MARKER or _string_has_credential(value)
    if value is None or type(value) in (bool, int, float):
        return False
    raise EvidenceMinimizationError(
        "evidence minimization encountered an unsupported JSON value"
    )


def _sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _string_has_credential(value: str) -> bool:
    return any(pattern.search(value) is not None for pattern in _CREDENTIAL_PATTERNS)


def _parse_operator_path(path: str) -> _ParsedPath:
    if not path or not path.startswith("/") or len(path.encode("utf-8")) > _MAX_PATH_UTF8_BYTES:
        raise ValueError("operator PII path is malformed or exceeds its byte ceiling")

    encoded_segments = path[1:].split("/")
    if (
        not encoded_segments
        or len(encoded_segments) > _MAX_PATH_SEGMENTS
        or any(segment == "" for segment in encoded_segments)
    ):
        raise ValueError("operator PII path has invalid segment structure")
    segments = tuple(_decode_pointer_segment(segment) for segment in encoded_segments)

    if segments[0] == "final_output":
        if len(segments) != 1:
            raise ValueError("final_output PII path must classify the whole text value")
        return _ParsedPath(
            scope="final_output",
            event_selector=None,
            tail=(),
            canonical="/final_output",
        )

    if segments[0] == "final_state":
        if len(segments) < 2:
            raise ValueError("final_state PII path must target a nested JSON value")
        tail = segments[1:]
        return _ParsedPath(
            scope="final_state",
            event_selector=None,
            tail=tail,
            canonical="/final_state/" + "/".join(_encode_pointer_segment(item) for item in tail),
        )

    if segments[0] == "events":
        if len(segments) < 4 or segments[2] != "payload":
            raise ValueError("event PII path must target /events/<index|*>/payload/...")
        selector_raw = segments[1]
        selector: int | Literal["*"]
        if selector_raw == "*":
            selector = "*"
        else:
            parsed_index = _canonical_list_index(selector_raw)
            if parsed_index is None:
                raise ValueError("event PII path index must be '*' or a canonical integer")
            selector = parsed_index
        tail = segments[3:]
        if not tail or "*" in tail:
            raise ValueError("wildcards are allowed only for the event index")
        canonical_selector = "*" if selector == "*" else str(selector)
        return _ParsedPath(
            scope="events",
            event_selector=selector,
            tail=tail,
            canonical=(
                f"/events/{canonical_selector}/payload/"
                + "/".join(_encode_pointer_segment(item) for item in tail)
            ),
        )

    raise ValueError("operator PII path must target final_state, final_output, or event payload")


def _decode_pointer_segment(segment: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(segment):
        character = segment[index]
        if character != "~":
            output.append(character)
            index += 1
            continue
        if index + 1 >= len(segment) or segment[index + 1] not in ("0", "1"):
            raise ValueError("operator PII path contains invalid JSON Pointer escaping")
        output.append("~" if segment[index + 1] == "0" else "/")
        index += 2
    decoded = "".join(output)
    if not decoded:
        raise ValueError("operator PII path segments must not be empty")
    return decoded


def _encode_pointer_segment(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def _paths_overlap(left: _ParsedPath, right: _ParsedPath) -> bool:
    if left.scope != right.scope:
        return False
    if left.scope == "final_output":
        return True
    if left.scope == "events" and not _event_selectors_overlap(
        left.event_selector, right.event_selector
    ):
        return False
    return _is_prefix(left.tail, right.tail) or _is_prefix(right.tail, left.tail)


def _event_selectors_overlap(
    left: int | Literal["*"] | None,
    right: int | Literal["*"] | None,
) -> bool:
    return left == "*" or right == "*" or left == right


def _is_prefix(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return len(left) <= len(right) and right[: len(left)] == left


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
