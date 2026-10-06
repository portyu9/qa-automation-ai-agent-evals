"""Versioned verification contracts layered above historical evidence schemas.

These contracts are additive. They do not reinterpret TrialEvidence/v2 or any existing receipt
root. A VerificationFactClaim is integrity material only; its producer label is not authority.
Only verify_fact_claim can produce the run-local VerifiedFact wrapper, and callers must supply
independent expected context plus the exact material bytes.

The run-local wrapper is a role-separation mechanism inside the evaluator process, not a
cryptographic sandbox against hostile Python code executing in the same interpreter.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FACT_SCHEMA: Literal["agent-evals/verification-fact/v1"] = "agent-evals/verification-fact/v1"
GRAPH_SCHEMA: Literal["agent-evals/verification-graph/v1"] = "agent-evals/verification-graph/v1"
CHAIN_SCHEMA: Literal["agent-evals/evidence-chain/v1"] = "agent-evals/evidence-chain/v1"
IDENTIFIER_POLICY = "agent-evals/identifier/nfc-v1"

_FACT_DOMAIN = b"agent-evals/verification-fact/v1\0"
_GRAPH_DOMAIN = b"agent-evals/verification-graph/v1\0"
_CHAIN_DOMAIN = b"agent-evals/evidence-chain/v1\0"
_ZERO_ROOT = "0" * 64
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_IDENTIFIER_UTF8 = 512
_MAX_FACT_MATERIAL = 2 * 1024 * 1024
_MAX_FACT_DEPENDENCIES = 256
_MAX_GRAPH_FACTS = 4096
_MAX_CHAIN_LINKS = 4096


class FactKind(StrEnum):
    """Semantic class of one verification fact."""

    EVIDENCE_INTEGRITY = "evidence_integrity"
    PRECONDITION = "precondition"
    ORACLE = "oracle"
    CRITICALITY = "criticality"
    OUTCOME = "outcome"
    RECEIPT = "receipt"


class FactProducerRole(StrEnum):
    """Non-authorizing provenance role label for one fact claim."""

    EVALUATOR = "evaluator"
    VERIFIER = "verifier"
    EXTERNAL = "external"
    HISTORICAL_REPLAY = "historical_replay"


class PrivilegedProducerRole(StrEnum):
    """Evaluator-local privileged producer roles.

    These capabilities are intentionally run-local and are not serialized into historical evidence.
    Existing exact-type producer checks remain authoritative during migration.
    """

    ATTACK_INJECTOR = "attack_injector"
    PROTOCOL_BRIDGE = "protocol_bridge"
    APPROVAL_CONTROLLER = "approval_controller"
    RETRIEVAL_BRIDGE = "retrieval_bridge"
    SIDE_EFFECT_OBSERVER = "side_effect_observer"
    SEMANTIC_VERIFIER = "semantic_verifier"


@dataclass(frozen=True, slots=True, init=False)
class ProducerCapability:
    """Capability issued by one exact ProducerCapabilityAuthority instance."""

    role: PrivilegedProducerRole
    producer_id: str
    _authority_token: object

    def __init__(
        self,
        *,
        role: PrivilegedProducerRole,
        producer_id: str,
        _authority_token: object,
        _issuer_token: object,
    ) -> None:
        if _issuer_token is not _PRODUCER_CAPABILITY_ISSUER:
            raise TypeError("ProducerCapability can only be issued by ProducerCapabilityAuthority")
        if type(role) is not PrivilegedProducerRole:
            raise TypeError("producer capability role must be an exact PrivilegedProducerRole")
        object.__setattr__(self, "role", role)
        object.__setattr__(
            self,
            "producer_id",
            canonical_identifier(producer_id, label="producer_id"),
        )
        object.__setattr__(self, "_authority_token", _authority_token)


_PRODUCER_CAPABILITY_ISSUER = object()


class ProducerCapabilityAuthority:
    """Run-local issuer/verifier for privileged producer capabilities.

    Authority is object-identity scoped. A capability from another authority instance is rejected
    even when its role and producer_id strings are identical.
    """

    __slots__ = ("__token",)

    def __init__(self) -> None:
        self.__token = object()

    def issue(self, *, role: PrivilegedProducerRole, producer_id: str) -> ProducerCapability:
        return ProducerCapability(
            role=role,
            producer_id=producer_id,
            _authority_token=self.__token,
            _issuer_token=_PRODUCER_CAPABILITY_ISSUER,
        )

    def require(
        self,
        capability: ProducerCapability,
        *,
        role: PrivilegedProducerRole,
        producer_id: str | None = None,
    ) -> None:
        if type(capability) is not ProducerCapability:
            raise ValueError("privileged producer requires an exact ProducerCapability")
        if capability._authority_token is not self.__token:
            raise ValueError("producer capability was issued by a different authority")
        if capability.role is not role:
            raise ValueError("producer capability role mismatch")
        if producer_id is not None:
            expected = canonical_identifier(producer_id, label="producer_id")
            if capability.producer_id != expected:
                raise ValueError("producer capability identity mismatch")


def canonical_identifier(value: str, *, label: str = "identifier") -> str:
    """Require the repository behavior-bearing identifier policy.

    Identifiers must already be NFC normalized. The evaluator rejects aliases instead of silently
    rewriting bytes that may participate in identities.
    """

    if type(value) is not str or not value:
        raise ValueError(f"{label} must be non-empty exact text")
    if value != value.strip():
        raise ValueError(f"{label} must not contain surrounding whitespace")
    if len(value.encode("utf-8")) > _MAX_IDENTIFIER_UTF8:
        raise ValueError(f"{label} exceeds the {_MAX_IDENTIFIER_UTF8}-byte UTF-8 limit")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError(f"{label} must already satisfy {IDENTIFIER_POLICY}")
    for char in value:
        category = unicodedata.category(char)
        if category.startswith("C") or category in {"Zl", "Zp"}:
            raise ValueError(f"{label} contains a forbidden Unicode code point")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _require_sha256(value: str, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256 hex")
    return value


def _fact_root(
    *,
    fact_kind: FactKind,
    fact_name: str,
    producer: FactProducerRole,
    subject_identity: str | None,
    scenario_identity: str | None,
    trial_id: str | None,
    dependencies: tuple[str, ...],
    material_sha256: str,
) -> str:
    material = {
        "schema_version": FACT_SCHEMA,
        "identifier_policy": IDENTIFIER_POLICY,
        "fact_kind": fact_kind.value,
        "fact_name": fact_name,
        "producer": producer.value,
        "subject_identity": subject_identity,
        "scenario_identity": scenario_identity,
        "trial_id": trial_id,
        "dependencies": list(dependencies),
        "material_sha256": material_sha256,
    }
    return hashlib.sha256(_FACT_DOMAIN + _canonical_json_bytes(material)).hexdigest()


def _chain_root(*, index: int, event_digest: str, previous_root: str) -> str:
    material = {
        "schema_version": CHAIN_SCHEMA,
        "index": index,
        "event_digest": event_digest,
        "previous_root": previous_root,
    }
    return hashlib.sha256(_CHAIN_DOMAIN + _canonical_json_bytes(material)).hexdigest()


class VerificationFactClaim(BaseModel):
    """Canonical integrity claim awaiting independent verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/verification-fact/v1"] = FACT_SCHEMA
    identifier_policy: Literal["agent-evals/identifier/nfc-v1"] = IDENTIFIER_POLICY
    fact_kind: FactKind
    fact_name: str
    producer: FactProducerRole
    subject_identity: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    scenario_identity: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    trial_id: str | None = None
    dependencies: tuple[str, ...] = Field(default=(), max_length=_MAX_FACT_DEPENDENCIES)
    material_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("fact_name")
    @classmethod
    def validate_fact_name(cls, value: str) -> str:
        return canonical_identifier(value, label="fact_name")

    @field_validator("trial_id")
    @classmethod
    def validate_trial_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return canonical_identifier(value, label="trial_id")

    @field_validator("dependencies")
    @classmethod
    def validate_dependencies(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for dependency in value:
            _require_sha256(dependency, "verification dependency")
        expected = tuple(sorted(set(value)))
        if value != expected:
            raise ValueError("verification dependencies must be unique canonical sorted roots")
        return value

    @model_validator(mode="after")
    def verify_root(self) -> Self:
        expected = _fact_root(
            fact_kind=self.fact_kind,
            fact_name=self.fact_name,
            producer=self.producer,
            subject_identity=self.subject_identity,
            scenario_identity=self.scenario_identity,
            trial_id=self.trial_id,
            dependencies=self.dependencies,
            material_sha256=self.material_sha256,
        )
        if not hmac.compare_digest(self.fact_root, expected):
            raise ValueError("verification fact root mismatch")
        return self

    @classmethod
    def from_material(
        cls,
        *,
        fact_kind: FactKind,
        fact_name: str,
        producer: FactProducerRole,
        material: bytes,
        subject_identity: str | None = None,
        scenario_identity: str | None = None,
        trial_id: str | None = None,
        dependencies: tuple[str, ...] = (),
    ) -> Self:
        if type(fact_kind) is not FactKind:
            raise ValueError("fact_kind must be an exact FactKind")
        if type(producer) is not FactProducerRole:
            raise ValueError("producer must be an exact FactProducerRole")
        if type(material) is not bytes:
            raise ValueError("verification fact material must be exact bytes")
        if len(material) > _MAX_FACT_MATERIAL:
            raise ValueError("verification fact material exceeds the bounded verification limit")
        fact_name = canonical_identifier(fact_name, label="fact_name")
        if trial_id is not None:
            trial_id = canonical_identifier(trial_id, label="trial_id")
        if subject_identity is not None:
            _require_sha256(subject_identity, "subject_identity")
        if scenario_identity is not None:
            _require_sha256(scenario_identity, "scenario_identity")
        canonical_dependencies = tuple(sorted(set(dependencies)))
        if canonical_dependencies != dependencies:
            raise ValueError("verification dependencies must be unique canonical sorted roots")
        for dependency in dependencies:
            _require_sha256(dependency, "verification dependency")
        digest = hashlib.sha256(material).hexdigest()
        root = _fact_root(
            fact_kind=fact_kind,
            fact_name=fact_name,
            producer=producer,
            subject_identity=subject_identity,
            scenario_identity=scenario_identity,
            trial_id=trial_id,
            dependencies=dependencies,
            material_sha256=digest,
        )
        return cls(
            fact_kind=fact_kind,
            fact_name=fact_name,
            producer=producer,
            subject_identity=subject_identity,
            scenario_identity=scenario_identity,
            trial_id=trial_id,
            dependencies=dependencies,
            material_sha256=digest,
            fact_root=root,
        )


_VERIFIED_FACT_CAPABILITY = object()


@dataclass(frozen=True, slots=True, init=False)
class VerifiedFact:
    """Run-local fact checked against independent expected material and context."""

    claim: VerificationFactClaim

    def __init__(self, claim: VerificationFactClaim, *, _capability: object) -> None:
        if _capability is not _VERIFIED_FACT_CAPABILITY:
            raise TypeError("VerifiedFact can only be issued by the verification boundary")
        if type(claim) is not VerificationFactClaim:
            raise TypeError("VerifiedFact requires an exact VerificationFactClaim")
        object.__setattr__(self, "claim", claim)

    @property
    def fact_root(self) -> str:
        return self.claim.fact_root


def verify_fact_claim(
    claim: VerificationFactClaim,
    *,
    expected_kind: FactKind,
    expected_name: str,
    expected_producer: FactProducerRole,
    material: bytes,
    expected_dependencies: tuple[str, ...] = (),
    expected_subject_identity: str | None = None,
    expected_scenario_identity: str | None = None,
    expected_trial_id: str | None = None,
) -> VerifiedFact:
    """Verify one claim against caller-owned expectations and exact material."""

    if type(claim) is not VerificationFactClaim:
        raise ValueError("claim must be an exact VerificationFactClaim")
    if type(expected_kind) is not FactKind or type(expected_producer) is not FactProducerRole:
        raise ValueError("verification expectations must use exact enum types")
    if type(material) is not bytes or len(material) > _MAX_FACT_MATERIAL:
        raise ValueError("verification material must be bounded exact bytes")
    expected_name = canonical_identifier(expected_name, label="expected fact_name")
    if expected_trial_id is not None:
        expected_trial_id = canonical_identifier(expected_trial_id, label="expected trial_id")
    canonical_dependencies = tuple(sorted(set(expected_dependencies)))
    if canonical_dependencies != expected_dependencies:
        raise ValueError("expected dependencies must be unique canonical sorted roots")
    for dependency in expected_dependencies:
        _require_sha256(dependency, "expected verification dependency")

    expected = VerificationFactClaim.from_material(
        fact_kind=expected_kind,
        fact_name=expected_name,
        producer=expected_producer,
        material=material,
        subject_identity=expected_subject_identity,
        scenario_identity=expected_scenario_identity,
        trial_id=expected_trial_id,
        dependencies=expected_dependencies,
    )
    if claim != expected:
        raise ValueError("verification fact does not match independent expected context/material")
    return VerifiedFact(claim, _capability=_VERIFIED_FACT_CAPABILITY)


@dataclass(frozen=True, slots=True)
class VerificationGraph:
    """Evaluator-local topological DAG of independently verified facts."""

    facts: tuple[VerifiedFact, ...]
    graph_root: str

    def __post_init__(self) -> None:
        expected = _verification_graph_root(self.facts)
        if not hmac.compare_digest(self.graph_root, expected):
            raise ValueError("verification graph root mismatch")

    @classmethod
    def from_verified(cls, facts: tuple[VerifiedFact, ...]) -> Self:
        return cls(facts=facts, graph_root=_verification_graph_root(facts))


def _verification_graph_root(facts: tuple[VerifiedFact, ...]) -> str:
    if not facts:
        raise ValueError("verification graph requires at least one fact")
    if len(facts) > _MAX_GRAPH_FACTS:
        raise ValueError("verification graph exceeds fact-count limit")
    seen: set[str] = set()
    roots: list[str] = []
    for fact in facts:
        if type(fact) is not VerifiedFact:
            raise ValueError("verification graph accepts only exact VerifiedFact values")
        root = fact.fact_root
        if root in seen:
            raise ValueError("verification graph contains duplicate fact roots")
        missing = [dependency for dependency in fact.claim.dependencies if dependency not in seen]
        if missing:
            raise ValueError(
                "verification fact dependency is missing or not topologically prior: "
                + ",".join(missing)
            )
        seen.add(root)
        roots.append(root)
    material = {"schema_version": GRAPH_SCHEMA, "fact_roots": roots}
    return hashlib.sha256(_GRAPH_DOMAIN + _canonical_json_bytes(material)).hexdigest()


_VERIFIED_CRITICALITY_ISSUER = object()


@dataclass(frozen=True, slots=True, init=False)
class VerifiedCriticalityRecord:
    """Evaluator-issued criticality summary bound to finalized session/reliability material."""

    subject_identity: str
    scenario_identity: str
    trial_evidence_roots: tuple[str, ...]
    reliability_sha256: str
    critical_violations: int

    def __init__(
        self,
        *,
        subject_identity: str,
        scenario_identity: str,
        trial_evidence_roots: tuple[str, ...],
        reliability_sha256: str,
        critical_violations: int,
        _issuer: object,
    ) -> None:
        if _issuer is not _VERIFIED_CRITICALITY_ISSUER:
            raise TypeError(
                "VerifiedCriticalityRecord can only be issued by evaluator release verification"
            )
        _require_sha256(subject_identity, "criticality subject_identity")
        _require_sha256(scenario_identity, "criticality scenario_identity")
        if not trial_evidence_roots:
            raise ValueError("criticality record requires finalized trial evidence roots")
        for root in trial_evidence_roots:
            _require_sha256(root, "criticality trial evidence root")
        if len(set(trial_evidence_roots)) != len(trial_evidence_roots):
            raise ValueError("criticality record trial evidence roots must be unique")
        _require_sha256(reliability_sha256, "criticality reliability_sha256")
        if (
            isinstance(critical_violations, bool)
            or not isinstance(critical_violations, int)
            or critical_violations < 0
        ):
            raise ValueError("critical_violations must be a non-negative integer")
        object.__setattr__(self, "subject_identity", subject_identity)
        object.__setattr__(self, "scenario_identity", scenario_identity)
        object.__setattr__(self, "trial_evidence_roots", trial_evidence_roots)
        object.__setattr__(self, "reliability_sha256", reliability_sha256)
        object.__setattr__(self, "critical_violations", critical_violations)


def _issue_verified_criticality_record(
    *,
    subject_identity: str,
    scenario_identity: str,
    trial_evidence_roots: tuple[str, ...],
    reliability_sha256: str,
    critical_violations: int,
) -> VerifiedCriticalityRecord:
    return VerifiedCriticalityRecord(
        subject_identity=subject_identity,
        scenario_identity=scenario_identity,
        trial_evidence_roots=trial_evidence_roots,
        reliability_sha256=reliability_sha256,
        critical_violations=critical_violations,
        _issuer=_VERIFIED_CRITICALITY_ISSUER,
    )


class EvidenceChainLink(BaseModel):
    """One optional previous-root link over an existing event digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-chain/v1"] = CHAIN_SCHEMA
    index: int = Field(ge=0, strict=True)
    event_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    chain_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, *, index: int, event_digest: str, previous_root: str) -> Self:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("evidence chain index must be a non-negative integer")
        _require_sha256(event_digest, "event_digest")
        _require_sha256(previous_root, "previous_root")
        return cls(
            index=index,
            event_digest=event_digest,
            previous_root=previous_root,
            chain_root=_chain_root(
                index=index,
                event_digest=event_digest,
                previous_root=previous_root,
            ),
        )

    @model_validator(mode="after")
    def verify_chain_root(self) -> Self:
        expected = _chain_root(
            index=self.index,
            event_digest=self.event_digest,
            previous_root=self.previous_root,
        )
        if not hmac.compare_digest(self.chain_root, expected):
            raise ValueError("evidence chain link root mismatch")
        return self


class EvidenceChain(BaseModel):
    """Optional streaming hash chain over existing event digests.

    This is not a Merkle membership proof and does not replace TrialEvidence/v2. It provides a
    bounded append-order commitment for consumers that need incremental verification.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-chain/v1"] = CHAIN_SCHEMA
    links: tuple[EvidenceChainLink, ...] = Field(min_length=1, max_length=_MAX_CHAIN_LINKS)
    final_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_event_digests(cls, event_digests: tuple[str, ...]) -> Self:
        if not event_digests:
            raise ValueError("evidence chain requires at least one event digest")
        if len(event_digests) > _MAX_CHAIN_LINKS:
            raise ValueError("evidence chain exceeds link-count limit")
        previous = _ZERO_ROOT
        links: list[EvidenceChainLink] = []
        for index, digest in enumerate(event_digests):
            link = EvidenceChainLink.create(
                index=index,
                event_digest=digest,
                previous_root=previous,
            )
            links.append(link)
            previous = link.chain_root
        return cls(links=tuple(links), final_root=previous)

    @model_validator(mode="after")
    def validate_chain(self) -> Self:
        previous = _ZERO_ROOT
        for index, link in enumerate(self.links):
            if type(link) is not EvidenceChainLink:
                raise ValueError("evidence chain requires exact EvidenceChainLink values")
            if link.index != index:
                raise ValueError("evidence chain indexes must be contiguous from zero")
            if not hmac.compare_digest(link.previous_root, previous):
                raise ValueError("evidence chain previous_root relation mismatch")
            previous = link.chain_root
        if not hmac.compare_digest(self.final_root, previous):
            raise ValueError("evidence chain final_root mismatch")
        return self
