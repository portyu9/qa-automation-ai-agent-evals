"""Versioned target-population and sampling-frame provenance."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_POPULATION_SCHEMA: Literal["agent-evals/population-provenance/v1"] = (
    "agent-evals/population-provenance/v1"
)
_FRAME_SCHEMA: Literal["agent-evals/population-frame/v1"] = "agent-evals/population-frame/v1"
_FRAME_DOMAIN = b"agent-evals/population-frame/v1\0"
_CANONICAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_BASIS_LENGTH = 2_000


class PopulationProvenanceError(ValueError):
    """Population provenance is malformed, contradictory, or unsupported."""


class PopulationStatus(StrEnum):
    """Strength of the population/sampling-frame provenance claim."""

    IDENTIFIED = "identified"
    EXTERNALLY_DECLARED = "externally_declared"
    UNKNOWN = "unknown"


class PopulationFrame(BaseModel):
    """Canonical reference to one externally defined, versioned population/frame.

    ``definition_identity`` is expected to identify the external definition material. The derived
    ``frame_identity`` binds that digest to a canonical namespace/name/revision tuple. Neither hash
    authenticates who supplied the definition or proves that observed attempts are representative
    of the referenced population.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/population-frame/v1"] = _FRAME_SCHEMA
    namespace: str = Field(min_length=1, max_length=128)
    population_id: str = Field(min_length=1, max_length=128)
    revision: str = Field(min_length=1, max_length=128)
    definition_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_identity: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("namespace", "population_id", "revision")
    @classmethod
    def validate_canonical_identifier(cls, value: str) -> str:
        if _CANONICAL_ID_RE.fullmatch(value) is None:
            raise ValueError(
                "population frame identifiers must be lowercase ASCII letters/digits plus '.', "
                "'_' or '-', starting with a letter or digit"
            )
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = _frame_identity(self.model_dump(mode="python", exclude={"frame_identity"}))
        if self.frame_identity != expected:
            raise ValueError("population frame identity does not match canonical frame material")
        return self

    @classmethod
    def create(
        cls,
        *,
        namespace: str,
        population_id: str,
        revision: str,
        definition_identity: str,
    ) -> PopulationFrame:
        if (
            not isinstance(definition_identity, str)
            or _SHA256_RE.fullmatch(definition_identity) is None
        ):
            raise PopulationProvenanceError(
                "population definition identity must be a lowercase SHA-256 hex digest"
            )
        unsigned: dict[str, Any] = {
            "schema_version": _FRAME_SCHEMA,
            "namespace": namespace,
            "population_id": population_id,
            "revision": revision,
            "definition_identity": definition_identity,
        }
        try:
            return cls.model_validate({**unsigned, "frame_identity": _frame_identity(unsigned)})
        except ValueError as exc:
            raise PopulationProvenanceError("population frame material is not canonical") from exc


class PopulationProvenance(BaseModel):
    """Explicit population assumption without self-declared verification.

    ``identified`` means only that a canonical versioned frame reference is present.
    ``externally_declared`` preserves a bounded caller/operator statement without converting it to
    evaluator-owned evidence. ``unknown`` carries no population claim.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/population-provenance/v1"] = _POPULATION_SCHEMA
    status: PopulationStatus
    frame: PopulationFrame | None = None
    basis: str | None = Field(default=None, max_length=_MAX_BASIS_LENGTH)

    @field_validator("basis")
    @classmethod
    def validate_basis(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise ValueError("population provenance basis must be non-empty and trimmed")
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.status is PopulationStatus.IDENTIFIED:
            if type(self.frame) is not PopulationFrame:
                raise ValueError("identified population provenance requires a canonical frame")
            if self.basis is not None:
                raise ValueError(
                    "identified population provenance must not carry declaration basis"
                )
        elif self.status is PopulationStatus.EXTERNALLY_DECLARED:
            if self.frame is not None:
                raise ValueError(
                    "externally declared population must not claim an identified frame"
                )
            if self.basis is None:
                raise ValueError("externally declared population requires a bounded basis")
        elif self.status is PopulationStatus.UNKNOWN:
            if self.frame is not None or self.basis is not None:
                raise ValueError("unknown population provenance must not carry a population claim")
        else:
            raise ValueError("unsupported population provenance status")
        return self

    @classmethod
    def identified(cls, frame: PopulationFrame) -> PopulationProvenance:
        if type(frame) is not PopulationFrame:
            raise PopulationProvenanceError(
                "identified population requires an exact PopulationFrame instance"
            )
        return cls(status=PopulationStatus.IDENTIFIED, frame=frame)

    @classmethod
    def externally_declared(cls, basis: str) -> PopulationProvenance:
        try:
            return cls(status=PopulationStatus.EXTERNALLY_DECLARED, basis=basis)
        except ValueError as exc:
            raise PopulationProvenanceError("external population declaration is malformed") from exc

    @classmethod
    def unknown(cls) -> PopulationProvenance:
        return cls(status=PopulationStatus.UNKNOWN)

    @property
    def population_identity(self) -> str | None:
        return self.frame.frame_identity if self.frame is not None else None


def validate_population_provenance(value: object) -> PopulationProvenance:
    """Require exact, self-consistent versioned population provenance."""
    if type(value) is not PopulationProvenance:
        raise PopulationProvenanceError(
            "population provenance must be an exact PopulationProvenance instance"
        )
    try:
        return PopulationProvenance.model_validate(value.model_dump(mode="python"))
    except ValueError as exc:
        raise PopulationProvenanceError("population provenance is malformed") from exc


def _frame_identity(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_FRAME_DOMAIN + canonical).hexdigest()
