"""Versioned scenario-registry metadata bound to immutable EvaluationScenario identities.

The registry is an index/quality contract, not a replacement for EvaluationScenario. It stores
scenario identities and structural fingerprints rather than raw private benchmark material.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.contracts.models import EvaluationScenario, ScenarioKind

_LEAKAGE_SCHEMA: Literal["agent-evals/benchmark-leakage-metadata/v1"] = (
    "agent-evals/benchmark-leakage-metadata/v1"
)
_PROVENANCE_SCHEMA: Literal["agent-evals/scenario-provenance/v1"] = (
    "agent-evals/scenario-provenance/v1"
)
_ENTRY_SCHEMA: Literal["agent-evals/scenario-registry-entry/v1"] = (
    "agent-evals/scenario-registry-entry/v1"
)
_REGISTRY_SCHEMA: Literal["agent-evals/scenario-registry/v1"] = (
    "agent-evals/scenario-registry/v1"
)
_ENTRY_DOMAIN = b"agent-evals/scenario-registry-entry/v1\0"
_REGISTRY_DOMAIN = b"agent-evals/scenario-registry/v1\0"


class ScenarioDifficulty(StrEnum):
    FOUNDATIONAL = "foundational"
    STANDARD = "standard"
    ADVANCED = "advanced"
    ADVERSARIAL = "adversarial"


class ScenarioLifecycle(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class BenchmarkExposure(StrEnum):
    """Disclosure/rotation class; a label does not make checked-in material private."""

    STABLE_PUBLIC = "stable_public"
    ROTATING_PRIVATE = "rotating_private"
    PRIVATE_HOLDOUT = "private_holdout"


class LeakageRisk(StrEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class ScenarioOrigin(StrEnum):
    AUTHORED = "authored"
    COUNTEREXAMPLE = "counterexample"
    MINIMIZED_FAILURE = "minimized_failure"
    METAMORPHIC_MUTANT = "metamorphic_mutant"


class RegistryFindingSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class RegistryFindingCode(StrEnum):
    EXACT_BEHAVIOR_DUPLICATE = "exact_behavior_duplicate"
    UNKNOWN_LEAKAGE_RISK = "unknown_leakage_risk"
    ACTIVE_DEPENDS_ON_DEPRECATED = "active_depends_on_deprecated"
    PUBLIC_HIGH_MEMORIZATION_RISK = "public_high_memorization_risk"


class BenchmarkLeakageMetadata(BaseModel):
    """Evaluator-owned leakage metadata; not proof of secrecy or contamination absence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/benchmark-leakage-metadata/v1"] = _LEAKAGE_SCHEMA
    exposure: BenchmarkExposure
    partition_id: str = Field(min_length=1, max_length=128)
    rotation_id: str | None = Field(default=None, min_length=1, max_length=128)
    contamination_risk: LeakageRisk = LeakageRisk.UNKNOWN
    memorization_risk: LeakageRisk = LeakageRisk.UNKNOWN
    review_revision: str = Field(min_length=1, max_length=128)
    notes_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("partition_id", "rotation_id", "review_revision")
    @classmethod
    def validate_identifiers(cls, value: str | None) -> str | None:
        if value is not None:
            _require_trimmed_text(value, label="benchmark metadata identifier")
        return value

    @model_validator(mode="after")
    def validate_exposure(self) -> Self:
        if self.exposure is BenchmarkExposure.ROTATING_PRIVATE and self.rotation_id is None:
            raise ValueError("rotating-private benchmark metadata requires rotation_id")
        if self.exposure is BenchmarkExposure.STABLE_PUBLIC and self.rotation_id is not None:
            raise ValueError("stable-public benchmark metadata cannot claim a rotation_id")
        return self


class ScenarioProvenance(BaseModel):
    """Promotion lineage for authored, counterexample, minimized, or metamorphic scenarios."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/scenario-provenance/v1"] = _PROVENANCE_SCHEMA
    origin: ScenarioOrigin = ScenarioOrigin.AUTHORED
    parent_scenario_identity: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_trial_id: str | None = Field(default=None, min_length=1, max_length=512)
    source_evidence_root: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_trial_id")
    @classmethod
    def validate_trial_id(cls, value: str | None) -> str | None:
        if value is not None:
            _require_trimmed_text(value, label="source_trial_id")
        return value

    @model_validator(mode="after")
    def validate_lineage(self) -> Self:
        has_trial = self.source_trial_id is not None
        has_evidence = self.source_evidence_root is not None
        if has_trial != has_evidence:
            raise ValueError("source trial identity and evidence root must appear together")

        if self.origin is ScenarioOrigin.AUTHORED:
            if self.parent_scenario_identity is not None or has_trial:
                raise ValueError("authored scenarios cannot claim derived promotion lineage")
            return self

        if self.parent_scenario_identity is None:
            raise ValueError("derived scenarios require an exact parent scenario identity")

        if self.origin in {ScenarioOrigin.COUNTEREXAMPLE, ScenarioOrigin.MINIMIZED_FAILURE}:
            if not has_trial:
                raise ValueError(
                    "counterexample/minimized promotion requires source trial and evidence root"
                )
        return self


class ScenarioRegistryEntry(BaseModel):
    """Registry metadata committed to one exact immutable scenario identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/scenario-registry-entry/v1"] = _ENTRY_SCHEMA
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    scenario_revision: str = Field(min_length=1, max_length=128)
    scenario_kind: ScenarioKind
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    behavioral_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_tags: tuple[str, ...] = Field(max_length=256)
    owner: str = Field(min_length=1, max_length=256)
    taxonomy: tuple[str, ...] = Field(min_length=1, max_length=64)
    population_scope: str = Field(min_length=1, max_length=4000)
    rationale: str = Field(min_length=1, max_length=8000)
    difficulty: ScenarioDifficulty
    prerequisites: tuple[str, ...] = Field(default=(), max_length=256)
    benchmark: BenchmarkLeakageMetadata
    provenance: ScenarioProvenance = Field(default_factory=ScenarioProvenance)
    lifecycle: ScenarioLifecycle = ScenarioLifecycle.ACTIVE
    deprecation_reason: str | None = Field(default=None, min_length=1, max_length=4000)
    superseded_by_scenario_identity: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    duplicate_waiver_reason: str | None = Field(default=None, min_length=1, max_length=4000)
    entry_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        scenario: EvaluationScenario,
        *,
        owner: str,
        taxonomy: tuple[str, ...],
        population_scope: str,
        rationale: str,
        difficulty: ScenarioDifficulty,
        benchmark: BenchmarkLeakageMetadata,
        prerequisites: tuple[str, ...] = (),
        provenance: ScenarioProvenance | None = None,
        lifecycle: ScenarioLifecycle = ScenarioLifecycle.ACTIVE,
        deprecation_reason: str | None = None,
        superseded_by_scenario_identity: str | None = None,
        duplicate_waiver_reason: str | None = None,
    ) -> Self:
        snapshot = _revalidate_scenario(scenario)
        validated_benchmark = _revalidate_benchmark(benchmark)
        validated_provenance = _revalidate_provenance(provenance or ScenarioProvenance())
        unsigned = {
            "schema_version": _ENTRY_SCHEMA,
            "scenario_id": snapshot.scenario_id,
            "scenario_revision": snapshot.revision,
            "scenario_kind": snapshot.kind.value,
            "scenario_identity": snapshot.identity,
            "behavioral_fingerprint": _behavioral_fingerprint(snapshot),
            "scenario_tags": tuple(sorted(snapshot.tags)),
            "owner": owner,
            "taxonomy": taxonomy,
            "population_scope": population_scope,
            "rationale": rationale,
            "difficulty": difficulty.value,
            "prerequisites": prerequisites,
            "benchmark": validated_benchmark.model_dump(mode="json"),
            "provenance": validated_provenance.model_dump(mode="json"),
            "lifecycle": lifecycle.value,
            "deprecation_reason": deprecation_reason,
            "superseded_by_scenario_identity": superseded_by_scenario_identity,
            "duplicate_waiver_reason": duplicate_waiver_reason,
        }
        return cls(
            scenario_id=snapshot.scenario_id,
            scenario_revision=snapshot.revision,
            scenario_kind=snapshot.kind,
            scenario_identity=snapshot.identity,
            behavioral_fingerprint=unsigned["behavioral_fingerprint"],
            scenario_tags=tuple(sorted(snapshot.tags)),
            owner=owner,
            taxonomy=taxonomy,
            population_scope=population_scope,
            rationale=rationale,
            difficulty=difficulty,
            prerequisites=prerequisites,
            benchmark=validated_benchmark,
            provenance=validated_provenance,
            lifecycle=lifecycle,
            deprecation_reason=deprecation_reason,
            superseded_by_scenario_identity=superseded_by_scenario_identity,
            duplicate_waiver_reason=duplicate_waiver_reason,
            entry_root=_entry_root(unsigned),
        )

    @field_validator("owner", "population_scope", "rationale")
    @classmethod
    def validate_text(cls, value: str) -> str:
        _require_trimmed_text(value, label="scenario registry text")
        return value

    @field_validator("deprecation_reason", "duplicate_waiver_reason")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is not None:
            _require_trimmed_text(value, label="scenario registry optional text")
        return value

    @field_validator("scenario_tags", "taxonomy")
    @classmethod
    def validate_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for label in value:
            _require_trimmed_text(label, label="scenario registry label")
        if len(set(value)) != len(value):
            raise ValueError("scenario registry labels must be unique")
        if value != tuple(sorted(value)):
            raise ValueError("scenario registry labels must be canonically sorted")
        return value

    @field_validator("prerequisites")
    @classmethod
    def validate_prerequisites(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for identity in value:
            _require_sha256(identity, label="scenario prerequisite")
        if len(set(value)) != len(value):
            raise ValueError("scenario prerequisites must be unique")
        if value != tuple(sorted(value)):
            raise ValueError("scenario prerequisites must be canonically sorted")
        return value

    @model_validator(mode="after")
    def validate_entry(self) -> Self:
        if self.scenario_identity in self.prerequisites:
            raise ValueError("scenario cannot depend on itself")
        if self.provenance.parent_scenario_identity == self.scenario_identity:
            raise ValueError("scenario provenance cannot name itself as parent")

        if self.lifecycle is ScenarioLifecycle.ACTIVE:
            if self.deprecation_reason is not None or self.superseded_by_scenario_identity is not None:
                raise ValueError("active scenario cannot carry deprecation metadata")
        else:
            if self.deprecation_reason is None:
                raise ValueError("deprecated scenario requires deprecation_reason")
            if self.superseded_by_scenario_identity == self.scenario_identity:
                raise ValueError("deprecated scenario cannot supersede itself")

        expected = _entry_root(self.model_dump(mode="json", exclude={"entry_root"}))
        if not hmac.compare_digest(expected, self.entry_root):
            raise ValueError("scenario registry entry root mismatch")
        return self

    def verify_scenario(self, scenario: EvaluationScenario) -> None:
        """Revalidate the raw scenario and require exact commitment equality."""

        snapshot = _revalidate_scenario(scenario)
        if snapshot.scenario_id != self.scenario_id or snapshot.revision != self.scenario_revision:
            raise ValueError("scenario registry key does not match supplied scenario")
        if snapshot.kind is not self.scenario_kind:
            raise ValueError("scenario registry kind does not match supplied scenario")
        if snapshot.identity != self.scenario_identity:
            raise ValueError("scenario registry identity does not match supplied scenario")
        if tuple(sorted(snapshot.tags)) != self.scenario_tags:
            raise ValueError("scenario registry tags do not match supplied scenario")
        if _behavioral_fingerprint(snapshot) != self.behavioral_fingerprint:
            raise ValueError("scenario registry behavioral fingerprint mismatch")


class ScenarioRegistry(BaseModel):
    """Canonical registry over metadata commitments, not raw private scenario bodies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/scenario-registry/v1"] = _REGISTRY_SCHEMA
    registry_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    revision: str = Field(min_length=1, max_length=128)
    entries: tuple[ScenarioRegistryEntry, ...] = Field(min_length=1, max_length=10_000)
    registry_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        registry_id: str,
        revision: str,
        entries: tuple[ScenarioRegistryEntry, ...],
    ) -> Self:
        validated = tuple(
            ScenarioRegistryEntry.model_validate_json(entry.model_dump_json())
            for entry in entries
        )
        canonical = _canonical_entries(validated)
        unsigned = _registry_material(
            registry_id=registry_id,
            revision=revision,
            entries=canonical,
        )
        return cls(
            registry_id=registry_id,
            revision=revision,
            entries=canonical,
            registry_root=_registry_root(unsigned),
        )

    @model_validator(mode="after")
    def validate_registry(self) -> Self:
        canonical = _canonical_entries(self.entries)
        if canonical != self.entries:
            raise ValueError("scenario registry entries are not in canonical order")

        identities = {entry.scenario_identity for entry in self.entries}
        if len(identities) != len(self.entries):
            raise ValueError("scenario registry contains duplicate scenario identities")

        keys = {(entry.scenario_id, entry.scenario_revision) for entry in self.entries}
        if len(keys) != len(self.entries):
            raise ValueError("scenario registry contains duplicate scenario id/revision keys")

        for entry in self.entries:
            missing = sorted(set(entry.prerequisites) - identities)
            if missing:
                raise ValueError(
                    f"scenario registry prerequisite is absent from registry: {missing!r}"
                )
            superseded = entry.superseded_by_scenario_identity
            if superseded is not None and superseded not in identities:
                raise ValueError("scenario supersession target is absent from registry")

        _reject_prerequisite_cycles(self.entries)
        expected = _registry_root(
            _registry_material(
                registry_id=self.registry_id,
                revision=self.revision,
                entries=self.entries,
            )
        )
        if not hmac.compare_digest(expected, self.registry_root):
            raise ValueError("scenario registry root mismatch")
        return self

    @property
    def identity(self) -> str:
        return self.registry_root

    def verify_scenarios(self, scenarios: tuple[EvaluationScenario, ...]) -> None:
        """Require an exact raw scenario for every registry commitment, with no extras."""

        snapshots = tuple(_revalidate_scenario(scenario) for scenario in scenarios)
        by_identity = {scenario.identity: scenario for scenario in snapshots}
        if len(by_identity) != len(snapshots):
            raise ValueError("supplied scenario corpus contains duplicate identities")
        registry_identities = {entry.scenario_identity for entry in self.entries}
        if set(by_identity) != registry_identities:
            raise ValueError("supplied scenario corpus does not exactly match registry identities")
        for entry in self.entries:
            entry.verify_scenario(by_identity[entry.scenario_identity])


class ScenarioRegistryFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: RegistryFindingCode
    severity: RegistryFindingSeverity
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    related_scenario_identity: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    detail: str = Field(min_length=1, max_length=2000)


def lint_scenario_registry(registry: ScenarioRegistry) -> tuple[ScenarioRegistryFinding, ...]:
    """Return deterministic quality findings without upgrading metadata labels into evidence."""

    validated = ScenarioRegistry.model_validate_json(registry.model_dump_json())
    findings: list[ScenarioRegistryFinding] = []
    by_identity = {entry.scenario_identity: entry for entry in validated.entries}

    by_fingerprint: dict[str, list[ScenarioRegistryEntry]] = {}
    for entry in validated.entries:
        by_fingerprint.setdefault(entry.behavioral_fingerprint, []).append(entry)
        if (
            entry.benchmark.contamination_risk is LeakageRisk.UNKNOWN
            or entry.benchmark.memorization_risk is LeakageRisk.UNKNOWN
        ):
            findings.append(
                ScenarioRegistryFinding(
                    code=RegistryFindingCode.UNKNOWN_LEAKAGE_RISK,
                    severity=RegistryFindingSeverity.WARNING,
                    scenario_identity=entry.scenario_identity,
                    detail="benchmark contamination or memorization risk remains unknown",
                )
            )
        if (
            entry.benchmark.exposure is BenchmarkExposure.STABLE_PUBLIC
            and entry.benchmark.memorization_risk is LeakageRisk.HIGH
        ):
            findings.append(
                ScenarioRegistryFinding(
                    code=RegistryFindingCode.PUBLIC_HIGH_MEMORIZATION_RISK,
                    severity=RegistryFindingSeverity.WARNING,
                    scenario_identity=entry.scenario_identity,
                    detail="stable-public scenario is labeled high memorization risk",
                )
            )
        if entry.lifecycle is ScenarioLifecycle.ACTIVE:
            for prerequisite in entry.prerequisites:
                if by_identity[prerequisite].lifecycle is ScenarioLifecycle.DEPRECATED:
                    findings.append(
                        ScenarioRegistryFinding(
                            code=RegistryFindingCode.ACTIVE_DEPENDS_ON_DEPRECATED,
                            severity=RegistryFindingSeverity.WARNING,
                            scenario_identity=entry.scenario_identity,
                            related_scenario_identity=prerequisite,
                            detail="active scenario depends on a deprecated prerequisite",
                        )
                    )

    for entries in by_fingerprint.values():
        if len(entries) < 2:
            continue
        ordered = sorted(entries, key=lambda entry: entry.scenario_identity)
        for index, entry in enumerate(ordered[:-1]):
            for related in ordered[index + 1 :]:
                if entry.duplicate_waiver_reason is None or related.duplicate_waiver_reason is None:
                    findings.append(
                        ScenarioRegistryFinding(
                            code=RegistryFindingCode.EXACT_BEHAVIOR_DUPLICATE,
                            severity=RegistryFindingSeverity.ERROR,
                            scenario_identity=entry.scenario_identity,
                            related_scenario_identity=related.scenario_identity,
                            detail=(
                                "distinct scenario identities have the same exact structural "
                                "behavioral fingerprint without bilateral duplicate waivers"
                            ),
                        )
                    )

    return tuple(
        sorted(
            findings,
            key=lambda finding: (
                finding.severity.value,
                finding.code.value,
                finding.scenario_identity,
                finding.related_scenario_identity or "",
            ),
        )
    )


def require_scenario_registry_quality(registry: ScenarioRegistry) -> None:
    """Fail when deterministic registry lint contains an ERROR finding."""

    errors = [
        finding
        for finding in lint_scenario_registry(registry)
        if finding.severity is RegistryFindingSeverity.ERROR
    ]
    if errors:
        codes = ",".join(sorted({finding.code.value for finding in errors}))
        raise ValueError(f"scenario registry quality errors: {codes}")


def scenario_registry_json_schema() -> dict[str, Any]:
    """Export the tooling schema; the schema itself is not a registry or trust assertion."""

    return ScenarioRegistry.model_json_schema()


def _canonical_entries(
    entries: tuple[ScenarioRegistryEntry, ...],
) -> tuple[ScenarioRegistryEntry, ...]:
    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                entry.scenario_id,
                entry.scenario_revision,
                entry.scenario_identity,
            ),
        )
    )


def _reject_prerequisite_cycles(entries: tuple[ScenarioRegistryEntry, ...]) -> None:
    dependencies = {entry.scenario_identity: entry.prerequisites for entry in entries}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identity: str) -> None:
        if identity in visited:
            return
        if identity in visiting:
            raise ValueError("scenario registry prerequisite graph contains a cycle")
        visiting.add(identity)
        for prerequisite in dependencies[identity]:
            visit(prerequisite)
        visiting.remove(identity)
        visited.add(identity)

    for identity in sorted(dependencies):
        visit(identity)


def _registry_material(
    *,
    registry_id: str,
    revision: str,
    entries: tuple[ScenarioRegistryEntry, ...],
) -> dict[str, object]:
    return {
        "schema_version": _REGISTRY_SCHEMA,
        "registry_id": registry_id,
        "revision": revision,
        "entry_roots": [entry.entry_root for entry in entries],
    }


def _behavioral_fingerprint(scenario: EvaluationScenario) -> str:
    material = scenario.model_dump(mode="python", exclude_none=True)
    material.pop("scenario_id", None)
    material.pop("revision", None)
    material.pop("tags", None)
    return _sha256_json(material)


def _entry_root(value: object) -> str:
    return hashlib.sha256(_ENTRY_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _registry_root(value: object) -> str:
    return hashlib.sha256(_REGISTRY_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _revalidate_scenario(value: EvaluationScenario) -> EvaluationScenario:
    if type(value) is not EvaluationScenario:
        raise ValueError("scenario registry requires exact EvaluationScenario values")
    return EvaluationScenario.model_validate_json(value.model_dump_json())


def _revalidate_benchmark(value: BenchmarkLeakageMetadata) -> BenchmarkLeakageMetadata:
    if type(value) is not BenchmarkLeakageMetadata:
        raise ValueError("scenario registry requires exact BenchmarkLeakageMetadata")
    return BenchmarkLeakageMetadata.model_validate_json(value.model_dump_json())


def _revalidate_provenance(value: ScenarioProvenance) -> ScenarioProvenance:
    if type(value) is not ScenarioProvenance:
        raise ValueError("scenario registry requires exact ScenarioProvenance")
    return ScenarioProvenance.model_validate_json(value.model_dump_json())


def _require_trimmed_text(value: str, *, label: str) -> None:
    if value != value.strip():
        raise ValueError(f"{label} must not contain surrounding whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{label} must not contain control characters")


def _require_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonicalize(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonicalize(value.model_dump(mode="python", exclude_none=True))
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("scenario registry JSON object keys must be strings")
        return {key: _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        normalized = [_canonicalize(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value
