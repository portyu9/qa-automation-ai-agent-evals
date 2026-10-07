from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import ValidationError

import agent_evals.evidence.store as store_module
from agent_evals.evidence.blob_store import (
    ContentAddressedEvidenceStore,
    EvidenceBlobBackend,
    canonical_evidence_bytes,
)
from agent_evals.evidence.minimization import (
    EvidenceMinimizationError,
    EvidenceMinimizationPolicy,
    EvidenceMinimizationReceipt,
    SensitiveDataClass,
    minimize_evidence_for_persistence,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.evidence.store import LocalEvidenceStore

SUBJECT = "a" * 64
SCENARIO = "b" * 64


def _event(
    sequence: int,
    *,
    kind: EvidenceKind = EvidenceKind.STATE,
    payload: dict[str, object] | None = None,
    critical: bool = False,
) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=kind,
        source="fixture",
        payload=payload or {"status": "ok"},
        critical=critical,
    )


def _evidence(
    *,
    events: tuple[EvidenceEvent, ...] = (),
    final_state: dict[str, object] | None = None,
    final_output: str | None = None,
) -> TrialEvidence:
    return TrialEvidence(
        trial_id="minimization",
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        events=events,
        final_state=final_state or {"status": "ok"},
        final_output=final_output,
    )


def _count(receipt: EvidenceMinimizationReceipt, classification: SensitiveDataClass) -> int:
    return next(
        item.count for item in receipt.classifications if item.classification is classification
    )


def test_default_policy_preserves_unclassified_trial_evidence_root() -> None:
    original = _evidence(
        events=(_event(0, payload={"answer": "safe"}),),
        final_state={"status": "safe"},
        final_output="safe",
    )

    prepared = minimize_evidence_for_persistence(original)

    assert prepared.evidence == original.snapshot()
    assert prepared.evidence.evidence_root == original.evidence_root
    assert prepared.receipt.result_evidence_root == original.evidence_root
    assert _count(prepared.receipt, SensitiveDataClass.CREDENTIAL) == 0
    assert _count(prepared.receipt, SensitiveDataClass.OPERATOR_PII) == 0


def test_benign_token_metric_keys_are_not_treated_as_credentials() -> None:
    original = _evidence(
        final_state={
            "output_tokens": 17,
            "token_count": 23,
            "tokenizer": "cl100k_base",
        }
    )

    prepared = minimize_evidence_for_persistence(original)

    assert prepared.evidence == original.snapshot()
    assert _count(prepared.receipt, SensitiveDataClass.CREDENTIAL) == 0


@pytest.mark.parametrize(
    "key",
    [
        "API-Key",
        "api_key",
        "refresh.token",
        "PRIVATE KEY",
        "Authorization",
        "user-token",
    ],
)
def test_sensitive_key_variants_are_redacted_without_secret_fingerprints(key: str) -> None:
    secret = "top-secret-value-12345"
    original = _evidence(final_state={key: secret, "safe": "visible"})

    prepared = minimize_evidence_for_persistence(original)
    serialized_evidence = prepared.evidence.model_dump_json()
    serialized_receipt = prepared.receipt.model_dump_json()

    assert secret not in serialized_evidence
    assert secret not in serialized_receipt
    assert prepared.evidence.final_state[key] == "[REDACTED:CREDENTIAL]"
    assert prepared.evidence.final_state["safe"] == "visible"
    assert _count(prepared.receipt, SensitiveDataClass.CREDENTIAL) == 1


@pytest.mark.parametrize(
    "text",
    [
        "prefix Bearer abcdefghijklmnop suffix",
        "token sk-abcdefghijklmnop embedded",
        "github ghp_abcdefghijklmnop token",
        "pat github_pat_abcdefghijklmnop",
        "aws AKIAABCDEFGHIJKLMNOP",
        "password=abcdefghijklmnop",
    ],
)
def test_embedded_credential_forms_redact_the_entire_free_form_scalar(text: str) -> None:
    prepared = minimize_evidence_for_persistence(_evidence(final_output=f"safe {text} tail"))

    assert prepared.evidence.final_output == "[REDACTED:CREDENTIAL]"
    assert text not in prepared.evidence.model_dump_json()


def test_operator_paths_use_strict_json_pointer_and_event_wildcard() -> None:
    original = _evidence(
        events=(
            _event(0, payload={"person": {"email": "one@example.test"}}),
            _event(1, payload={"person": {"email": "two@example.test"}}),
        ),
        final_state={"customer/record": {"email": "state@example.test"}},
        final_output="final@example.test",
    )
    policy = EvidenceMinimizationPolicy(
        operator_pii_paths=(
            "/events/*/payload/person/email",
            "/final_state/customer~1record/email",
            "/final_output",
        )
    )

    prepared = minimize_evidence_for_persistence(original, policy=policy)

    assert prepared.evidence.events[0].payload["person"]["email"] == "[REDACTED:OPERATOR_PII]"
    assert prepared.evidence.events[1].payload["person"]["email"] == "[REDACTED:OPERATOR_PII]"
    assert prepared.evidence.final_state["customer/record"]["email"] == "[REDACTED:OPERATOR_PII]"
    assert prepared.evidence.final_output == "[REDACTED:OPERATOR_PII]"
    assert _count(prepared.receipt, SensitiveDataClass.OPERATOR_PII) == 4
    serialized = prepared.evidence.model_dump_json() + prepared.receipt.model_dump_json()
    assert "one@example.test" not in serialized
    assert "two@example.test" not in serialized
    assert "state@example.test" not in serialized
    assert "final@example.test" not in serialized


def test_credential_in_authority_bearing_event_fails_closed_without_echoing_secret() -> None:
    secret = "ghp_abcdefghijklmnop"
    original = _evidence(
        events=(
            _event(
                0,
                kind=EvidenceKind.APPROVAL,
                payload={"authorization": secret},
            ),
        )
    )

    with pytest.raises(EvidenceMinimizationError) as error:
        minimize_evidence_for_persistence(original)

    assert "authority-bearing" in str(error.value)
    assert secret not in str(error.value)


def test_critical_free_form_event_fails_closed_instead_of_rewriting_semantics() -> None:
    secret = "sk-abcdefghijklmnop"
    original = _evidence(
        events=(
            _event(
                0,
                kind=EvidenceKind.STATE,
                payload={"message": f"credential {secret}"},
                critical=True,
            ),
        )
    )

    with pytest.raises(EvidenceMinimizationError, match="authority-bearing"):
        minimize_evidence_for_persistence(original)


def test_operator_pii_path_into_authority_event_fails_closed() -> None:
    original = _evidence(
        events=(
            _event(
                0,
                kind=EvidenceKind.APPROVAL_DECISION,
                payload={"person": {"email": "reviewer@example.test"}},
            ),
        )
    )
    policy = EvidenceMinimizationPolicy(operator_pii_paths=("/events/0/payload/person/email",))

    with pytest.raises(EvidenceMinimizationError, match="authority-bearing"):
        minimize_evidence_for_persistence(original, policy=policy)


def test_conflicting_operator_pii_and_credential_classification_fails_closed() -> None:
    original = _evidence(final_state={"password": "abcdefghijklmnop"})
    policy = EvidenceMinimizationPolicy(operator_pii_paths=("/final_state/password",))

    with pytest.raises(EvidenceMinimizationError, match="conflicts with credential"):
        minimize_evidence_for_persistence(original, policy=policy)


@pytest.mark.parametrize(
    "paths",
    [
        ("not-a-pointer",),
        ("/final_output/nested",),
        ("/events/01/payload/email",),
        ("/events/0/not-payload/email",),
        ("/events/0/payload/*",),
        ("/final_state/~2bad",),
        ("/final_state/person", "/final_state/person/email"),
        ("/events/*/payload/person", "/events/1/payload/person/email"),
    ],
)
def test_malformed_ambiguous_or_overlapping_operator_paths_fail_policy_validation(
    paths: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError):
        EvidenceMinimizationPolicy(operator_pii_paths=paths)


def test_redaction_and_traversal_budgets_fail_closed() -> None:
    with pytest.raises(EvidenceMinimizationError, match="redaction ceiling"):
        minimize_evidence_for_persistence(
            _evidence(final_state={"password": "one-secret", "api_key": "two-secret"}),
            policy=EvidenceMinimizationPolicy(max_redactions=1),
        )

    with pytest.raises(EvidenceMinimizationError, match="traversal"):
        minimize_evidence_for_persistence(
            _evidence(final_state={"outer": {"inner": {"value": "safe"}}}),
            policy=EvidenceMinimizationPolicy(max_traversal_nodes=1),
        )


def test_minimization_is_deterministic_and_idempotent() -> None:
    policy = EvidenceMinimizationPolicy(operator_pii_paths=("/final_state/person/email",))
    original = _evidence(
        final_state={
            "person": {"email": "person@example.test"},
            "api-key": "top-secret-value",
        },
        final_output="Bearer abcdefghijklmnop",
    )

    first = minimize_evidence_for_persistence(original, policy=policy)
    second = minimize_evidence_for_persistence(first.evidence, policy=policy)

    assert second.evidence == first.evidence
    assert second.receipt == first.receipt
    assert (
        policy.policy_id
        == EvidenceMinimizationPolicy(operator_pii_paths=("/final_state/person/email",)).policy_id
    )


def test_minimization_receipt_detects_tampering_and_has_no_raw_fingerprint() -> None:
    secret = "ghp_abcdefghijklmnop"
    prepared = minimize_evidence_for_persistence(_evidence(final_state={"token": secret}))
    dumped = prepared.receipt.model_dump(mode="json")
    dumped["receipt_root"] = "0" * 64

    with pytest.raises(ValidationError, match="receipt root mismatch"):
        EvidenceMinimizationReceipt.model_validate(dumped)

    assert secret not in prepared.receipt.model_dump_json()


def test_local_store_round_trip_persists_only_minimized_evidence(tmp_path: Path) -> None:
    secret = "ghp_abcdefghijklmnop"
    policy = EvidenceMinimizationPolicy(operator_pii_paths=("/final_state/person/email",))
    store = LocalEvidenceStore(
        tmp_path / "evidence",
        minimization_policy=policy,
    )

    manifest, receipt = store.write_with_receipt(
        _evidence(
            final_state={
                "person": {"email": "person@example.test"},
                "api_key": secret,
            }
        )
    )
    loaded = store.read(manifest.record_key)

    serialized = loaded.evidence.model_dump_json()
    assert secret not in serialized
    assert "person@example.test" not in serialized
    assert loaded.evidence.final_state["api_key"] == "[REDACTED:CREDENTIAL]"
    assert loaded.evidence.final_state["person"]["email"] == "[REDACTED:OPERATOR_PII]"
    assert loaded.evidence.evidence_root == receipt.result_evidence_root


def test_local_store_minimizes_before_any_durable_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "ghp_abcdefghijklmnop"
    observed: list[bytes] = []

    def spy_materialize(path: Path, content: bytes) -> None:
        del path
        observed.append(bytes(content))

    monkeypatch.setattr(store_module, "_atomic_materialize", spy_materialize)
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest, receipt = store.write_with_receipt(
        _evidence(
            final_state={"api_key": secret},
            final_output=f"Bearer {secret}",
        )
    )

    assert observed
    assert all(secret.encode() not in content for content in observed)
    assert manifest.evidence_root == receipt.result_evidence_root
    assert _count(receipt, SensitiveDataClass.CREDENTIAL) == 2


@dataclass
class _SpyingBackend(EvidenceBlobBackend):
    objects: dict[str, bytes] = field(default_factory=dict)
    observed_writes: list[tuple[str, bytes]] = field(default_factory=list)

    def put_if_absent(self, key: str, content: bytes) -> bool:
        self.observed_writes.append((key, bytes(content)))
        if key in self.objects:
            return False
        self.objects[key] = bytes(content)
        return True

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def list_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.objects))

    def delete(self, key: str) -> bool:
        return self.objects.pop(key, None) is not None


def test_content_addressed_store_minimizes_before_content_key_or_backend_write() -> None:
    secret = "sk-abcdefghijklmnop"
    backend = _SpyingBackend()
    store = ContentAddressedEvidenceStore(backend, compression="gzip")

    manifest, receipt = store.write_with_receipt(
        _evidence(
            events=(_event(0, payload={"password": secret}),),
            final_output=f"credential {secret}",
        )
    )

    assert backend.observed_writes
    assert all(secret.encode() not in content for _, content in backend.observed_writes)
    loaded = store.read(manifest.logical_sha256)
    assert manifest.logical_sha256 == hashlib.sha256(canonical_evidence_bytes(loaded)).hexdigest()
    assert secret not in loaded.model_dump_json()
    assert manifest.evidence_root == receipt.result_evidence_root
    assert loaded.evidence_root == receipt.result_evidence_root


def test_policy_rejects_non_materialized_over_budget_and_non_string_paths() -> None:
    with pytest.raises(ValidationError, match="bounded materialized collection"):
        EvidenceMinimizationPolicy.model_validate(
            {"operator_pii_paths": "/final_state/email"}
        )

    with pytest.raises(ValidationError, match="path count"):
        EvidenceMinimizationPolicy(
            operator_pii_paths=tuple(
                f"/final_state/field{index}" for index in range(65)
            )
        )

    with pytest.raises(ValidationError, match="exact strings"):
        EvidenceMinimizationPolicy.model_validate(
            {"operator_pii_paths": ["/final_state/email", 7]}
        )

    with pytest.raises(ValidationError, match="unique"):
        EvidenceMinimizationPolicy(
            operator_pii_paths=("/final_state/email", "/final_state/email")
        )


def test_receipt_rejects_noncanonical_classification_order() -> None:
    prepared = minimize_evidence_for_persistence(
        _evidence(final_state={"api_key": "secret-value"})
    )
    dumped = prepared.receipt.model_dump(mode="json")
    dumped["classifications"] = list(reversed(dumped["classifications"]))

    with pytest.raises(ValidationError, match="complete and canonical"):
        EvidenceMinimizationReceipt.model_validate(dumped)


def test_minimizer_rejects_trial_and_policy_subclasses() -> None:
    class DerivedEvidence(TrialEvidence):
        pass

    class DerivedPolicy(EvidenceMinimizationPolicy):
        pass

    derived_evidence = DerivedEvidence.model_validate(
        _evidence().model_dump(mode="python")
    )

    with pytest.raises(TypeError, match="exact TrialEvidence"):
        minimize_evidence_for_persistence(derived_evidence)

    with pytest.raises(TypeError, match="exact EvidenceMinimizationPolicy"):
        minimize_evidence_for_persistence(_evidence(), policy=DerivedPolicy())


def test_final_output_path_handles_absence_conflict_and_idempotent_marker() -> None:
    policy = EvidenceMinimizationPolicy(operator_pii_paths=("/final_output",))

    absent = minimize_evidence_for_persistence(_evidence(), policy=policy)
    assert _count(absent.receipt, SensitiveDataClass.OPERATOR_PII) == 0

    with pytest.raises(EvidenceMinimizationError, match="conflicts with credential"):
        minimize_evidence_for_persistence(
            _evidence(final_output="Bearer abcdefghijklmnop"),
            policy=policy,
        )

    first = minimize_evidence_for_persistence(
        _evidence(final_output="person@example.test"),
        policy=policy,
    )
    second = minimize_evidence_for_persistence(first.evidence, policy=policy)
    assert second == first


def test_missing_and_out_of_range_declared_paths_are_deterministic_noops() -> None:
    policy = EvidenceMinimizationPolicy(
        operator_pii_paths=(
            "/events/9/payload/email",
            "/final_state/missing/deep",
            "/final_state/present/missing",
        )
    )
    original = _evidence(
        events=(_event(0, payload={"email": "safe@example.test"}),),
        final_state={"present": {"value": "safe"}},
    )

    prepared = minimize_evidence_for_persistence(original, policy=policy)

    assert prepared.evidence == original.snapshot()
    assert _count(prepared.receipt, SensitiveDataClass.OPERATOR_PII) == 0


def test_declared_paths_support_list_replacement_and_fail_on_bad_container_shape() -> None:
    valid_policy = EvidenceMinimizationPolicy(
        operator_pii_paths=("/final_state/people/0/email",)
    )
    prepared = minimize_evidence_for_persistence(
        _evidence(final_state={"people": [{"email": "person@example.test"}]}),
        policy=valid_policy,
    )
    assert prepared.evidence.final_state["people"][0]["email"] == "[REDACTED:OPERATOR_PII]"

    with pytest.raises(EvidenceMinimizationError, match="JSON container shape"):
        minimize_evidence_for_persistence(
            _evidence(final_state={"people": [{"email": "person@example.test"}]}),
            policy=EvidenceMinimizationPolicy(
                operator_pii_paths=("/final_state/people/not-an-index/email",)
            ),
        )

    out_of_range = minimize_evidence_for_persistence(
        _evidence(final_state={"people": [{"email": "person@example.test"}]}),
        policy=EvidenceMinimizationPolicy(
            operator_pii_paths=("/final_state/people/4/email",)
        ),
    )
    assert _count(out_of_range.receipt, SensitiveDataClass.OPERATOR_PII) == 0

    with pytest.raises(EvidenceMinimizationError, match="non-container"):
        minimize_evidence_for_persistence(
            _evidence(final_state={"person": "scalar"}),
            policy=EvidenceMinimizationPolicy(
                operator_pii_paths=("/final_state/person/email",)
            ),
        )


@pytest.mark.parametrize(
    "target",
    [
        {"nested": {"api_key": "secret-value"}},
        [{"password": "secret-value"}],
    ],
)
def test_operator_pii_parent_conflicts_with_nested_credentials(target: object) -> None:
    with pytest.raises(EvidenceMinimizationError, match="conflicts with credential"):
        minimize_evidence_for_persistence(
            _evidence(final_state={"profile": target}),
            policy=EvidenceMinimizationPolicy(
                operator_pii_paths=("/final_state/profile",)
            ),
        )


def test_operator_pii_can_replace_noncredential_scalar_and_credentials_walk_lists() -> None:
    pii = minimize_evidence_for_persistence(
        _evidence(final_state={"age": 42}),
        policy=EvidenceMinimizationPolicy(operator_pii_paths=("/final_state/age",)),
    )
    assert pii.evidence.final_state["age"] == "[REDACTED:OPERATOR_PII]"

    credential = minimize_evidence_for_persistence(
        _evidence(final_state={"items": [{"service_token": "secret-value"}]})
    )
    assert credential.evidence.final_state["items"][0]["service_token"] == "[REDACTED:CREDENTIAL]"


@pytest.mark.parametrize(
    "path",
    [
        "/final_state",
        "/unknown/email",
        "/final_state//email",
        "/events/not-an-index/payload/email",
    ],
)
def test_additional_invalid_operator_path_shapes_fail_closed(path: str) -> None:
    with pytest.raises(ValidationError):
        EvidenceMinimizationPolicy(operator_pii_paths=(path,))


def test_disjoint_specific_event_paths_are_not_falsely_treated_as_overlapping() -> None:
    policy = EvidenceMinimizationPolicy(
        operator_pii_paths=(
            "/events/0/payload/person/email",
            "/events/1/payload/person/email",
        )
    )
    original = _evidence(
        events=(
            _event(0, payload={"person": {"email": "one@example.test"}}),
            _event(1, payload={"person": {"email": "two@example.test"}}),
        )
    )

    prepared = minimize_evidence_for_persistence(original, policy=policy)

    assert _count(prepared.receipt, SensitiveDataClass.OPERATOR_PII) == 2


def test_store_constructor_rejects_policy_subclasses(tmp_path: Path) -> None:
    class DerivedPolicy(EvidenceMinimizationPolicy):
        pass

    with pytest.raises(TypeError, match="exact EvidenceMinimizationPolicy"):
        LocalEvidenceStore(
            tmp_path / "evidence",
            minimization_policy=DerivedPolicy(),
        )
