from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.runtime.population import (
    PopulationFrame,
    PopulationProvenance,
    PopulationProvenanceError,
    PopulationStatus,
    validate_population_provenance,
)

_DEFINITION = "a" * 64


def _frame(**overrides: object) -> PopulationFrame:
    data: dict[str, object] = {
        "namespace": "scenario-suite",
        "population_id": "payments-regression",
        "revision": "2026.09",
        "definition_identity": _DEFINITION,
    }
    data.update(overrides)
    return PopulationFrame.create(**data)  # type: ignore[arg-type]


def test_identified_population_binds_versioned_definition_material() -> None:
    frame = _frame()
    provenance = PopulationProvenance.identified(frame)

    assert provenance.status is PopulationStatus.IDENTIFIED
    assert provenance.population_identity == frame.frame_identity
    assert provenance.basis is None
    assert frame == _frame()
    assert frame.frame_identity != _frame(revision="2026.10").frame_identity
    assert frame.frame_identity != _frame(definition_identity="b" * 64).frame_identity


def test_population_frame_rejects_noncanonical_names_and_forged_identity() -> None:
    with pytest.raises(PopulationProvenanceError, match="canonical"):
        _frame(namespace="Scenario-Suite")
    with pytest.raises(PopulationProvenanceError, match="lowercase SHA-256"):
        _frame(definition_identity="not-a-digest")

    payload = _frame().model_dump(mode="json")
    payload["revision"] = "2026.10"
    with pytest.raises(ValidationError, match="identity does not match"):
        PopulationFrame.model_validate(payload)


def test_population_provenance_keeps_declaration_and_unknown_distinct() -> None:
    declared = PopulationProvenance.externally_declared(
        "Operator states traffic sample represents the September production cohort."
    )
    unknown = PopulationProvenance.unknown()

    assert declared.status is PopulationStatus.EXTERNALLY_DECLARED
    assert declared.population_identity is None
    assert unknown.status is PopulationStatus.UNKNOWN
    assert unknown.basis is None


def test_population_provenance_rejects_trust_class_confusion() -> None:
    frame = _frame()
    with pytest.raises(ValidationError, match="must not carry declaration basis"):
        PopulationProvenance(
            status=PopulationStatus.IDENTIFIED,
            frame=frame,
            basis="human claim",
        )
    with pytest.raises(ValidationError, match="must not claim an identified frame"):
        PopulationProvenance(
            status=PopulationStatus.EXTERNALLY_DECLARED,
            frame=frame,
            basis="human claim",
        )
    with pytest.raises(ValidationError, match="must not carry a population claim"):
        PopulationProvenance(status=PopulationStatus.UNKNOWN, frame=frame)


def test_population_provenance_rejects_missing_basis_and_extra_fields() -> None:
    with pytest.raises(ValidationError, match="requires a bounded basis"):
        PopulationProvenance(status=PopulationStatus.EXTERNALLY_DECLARED)

    payload = PopulationProvenance.unknown().model_dump(mode="json")
    payload["population_known"] = True
    with pytest.raises(ValidationError):
        PopulationProvenance.model_validate(payload)


def test_runtime_validation_requires_exact_population_provenance_type() -> None:
    provenance = PopulationProvenance.unknown()
    assert validate_population_provenance(provenance) == provenance

    with pytest.raises(PopulationProvenanceError, match="exact PopulationProvenance"):
        validate_population_provenance(provenance.model_dump(mode="json"))
