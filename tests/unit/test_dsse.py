from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from pydantic import ValidationError

from agent_evals.assurance.report import AssuranceReport
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.dsse import (
    ASSURANCE_REPORT_V6_PAYLOAD_TYPE,
    EVIDENCE_MANIFEST_V1_PAYLOAD_TYPE,
    DSSEEnvelope,
    DSSESignature,
    DSSEVerificationError,
    create_dsse_envelope,
    parse_dsse_envelope,
    pre_authentication_encode,
    sign_assurance_report,
    sign_evidence_manifest,
    verify_assurance_report_envelope,
    verify_dsse_envelope,
    verify_evidence_manifest_envelope,
)
from agent_evals.evidence.models import TrialEvidence, TrialVerdict
from agent_evals.evidence.store import ArtifactManifest
from agent_evals.gates.release import ReleasePolicy
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.grading import grade_deterministic_evidence
from agent_evals.runtime.sampling import (
    RandomnessStatus,
    SamplingPolicy,
    SessionSamplingMetadata,
    StoppingRule,
)
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport

_TEST_KEY = b"deterministic-test-only-dsse-key"
_UNTRUSTED_KEY = b"untrusted-deterministic-test-key"
_SECOND_TEST_KEY = b"second-deterministic-test-key"
_KEY_ID = "test-key-1"
_SECOND_KEY_ID = "test-key-2"
_SUBJECT = "a" * 64
_CAMPAIGN = "dsse-test-campaign"
_SCENARIO = EvaluationScenario(
    scenario_id="dsse.report",
    revision="1",
    kind=ScenarioKind.REGRESSION,
    objective="Validate authenticated assurance artifact envelopes.",
    required_outcomes={"status": "ok"},
)


def _sign(message: bytes) -> bytes:
    return hmac.new(_TEST_KEY, message, hashlib.sha256).digest()


def _verify(message: bytes, signature: bytes) -> bool:
    return hmac.compare_digest(_sign(message), signature)


def _sign_untrusted(message: bytes) -> bytes:
    return hmac.new(_UNTRUSTED_KEY, message, hashlib.sha256).digest()


def _sign_second(message: bytes) -> bytes:
    return hmac.new(_SECOND_TEST_KEY, message, hashlib.sha256).digest()


def _verify_second(message: bytes, signature: bytes) -> bool:
    return hmac.compare_digest(_sign_second(message), signature)


def _report() -> AssuranceReport:
    trial_id = f"campaign:{_CAMPAIGN}:attempt:0000"
    evidence = TrialEvidence(
        trial_id=trial_id,
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO.identity,
        final_state={"status": "ok"},
    )
    oracle_results = grade_deterministic_evidence(_SCENARIO, evidence)
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=oracle_results,
        verdict=TrialVerdict.PASS,
    )
    session = EvaluationSessionResult(
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO.identity,
        trials=(trial,),
        reliability=ReliabilityReport.from_verdicts((TrialVerdict.PASS,), k=1),
        campaign_id=_CAMPAIGN,
        runtime_adapter_name="dsse-test-runtime",
        subject_adapter="dsse-test-subject",
        subject_adapter_version="1",
        sampling_metadata=SessionSamplingMetadata(
            sampling_policy=SamplingPolicy.PREDECLARED_ALL_ATTEMPTS,
            randomness_status=RandomnessStatus.UNKNOWN,
            stopping_rule=StoppingRule.FIXED_HORIZON,
            planned_trials=1,
        ),
    )
    return AssuranceReport.from_session(
        session,
        scenario=_SCENARIO,
        release_policy=ReleasePolicy(
            min_resolved_trials=1,
            min_success_rate=0.0,
            min_wilson_low=0.0,
            max_critical_violations=0,
            max_blocked_trials=0,
            max_inconclusive_trials=0,
        ),
    )


def _manifest() -> ArtifactManifest:
    return ArtifactManifest(
        record_key="b" * 64,
        trial_id="trial-dsse",
        subject_identity="c" * 64,
        scenario_identity="d" * 64,
        evidence_root="e" * 64,
        payload_sha256="f" * 64,
        payload_bytes=123,
    )


def test_dsse_pae_matches_exact_v1_layout() -> None:
    assert pre_authentication_encode("text/plain", b"hello") == b"DSSEv1 10 text/plain 5 hello"


def test_dsse_pae_counts_utf8_bytes_not_code_points() -> None:
    payload_type = "application/example+Ω"
    encoded = payload_type.encode("utf-8")

    pae = pre_authentication_encode(payload_type, b"x")

    assert pae == b"DSSEv1 " + str(len(encoded)).encode() + b" " + encoded + b" 1 x"


def test_strict_envelope_parser_round_trips_valid_json() -> None:
    envelope = create_dsse_envelope(
        "application/test",
        b"payload",
        key_id=_KEY_ID,
        sign=_sign,
    )

    assert parse_dsse_envelope(envelope.model_dump_json()) == envelope


def test_strict_envelope_parser_rejects_duplicate_json_keys() -> None:
    envelope = create_dsse_envelope(
        "application/test",
        b"payload",
        key_id=_KEY_ID,
        sign=_sign,
    )
    raw = envelope.model_dump_json()
    duplicate = raw[:-1] + ',"payload":"cGF5bG9hZA=="}'

    with pytest.raises(DSSEVerificationError, match="strict validation"):
        parse_dsse_envelope(duplicate)


def test_verification_requires_nonempty_trusted_registry() -> None:
    envelope = create_dsse_envelope(
        "application/test",
        b"payload",
        key_id=_KEY_ID,
        sign=_sign,
    )

    with pytest.raises(DSSEVerificationError, match="at least one trusted verifier"):
        verify_dsse_envelope(envelope, trusted_verifiers={})


def test_generic_envelope_round_trip_requires_caller_trust() -> None:
    envelope = create_dsse_envelope(
        "application/test",
        b"payload",
        key_id=_KEY_ID,
        sign=_sign,
    )

    verified = verify_dsse_envelope(
        envelope,
        trusted_verifiers={_KEY_ID: _verify},
        expected_payload_type="application/test",
        expected_payload=b"payload",
    )

    assert verified.payload_type == "application/test"
    assert verified.payload == b"payload"
    assert verified.verified_key_ids == (_KEY_ID,)


def test_unknown_key_id_has_no_authority_without_trusted_cryptographic_match() -> None:
    envelope = create_dsse_envelope(
        "application/test",
        b"payload",
        key_id="untrusted-key",
        sign=_sign_untrusted,
    )

    with pytest.raises(DSSEVerificationError, match="no valid signature from a trusted key"):
        verify_dsse_envelope(envelope, trusted_verifiers={_KEY_ID: _verify})


def test_key_id_is_only_a_hint_and_actual_verifying_key_is_authoritative() -> None:
    envelope = create_dsse_envelope(
        "application/test",
        b"payload",
        key_id="forged-or-stale-hint",
        sign=_sign,
    )

    verified = verify_dsse_envelope(envelope, trusted_verifiers={_KEY_ID: _verify})

    assert verified.verified_key_ids == (_KEY_ID,)


def test_unknown_signature_can_coexist_with_valid_trusted_signature() -> None:
    payload = b"payload"
    payload_type = "application/test"
    trusted_sig = _sign(pre_authentication_encode(payload_type, payload))
    envelope = DSSEEnvelope(
        payloadType=payload_type,
        payload=base64.b64encode(payload).decode(),
        signatures=(
            DSSESignature(
                keyid="unknown",
                sig=base64.b64encode(b"untrusted-signature").decode(),
            ),
            DSSESignature(
                keyid=_KEY_ID,
                sig=base64.b64encode(trusted_sig).decode(),
            ),
        ),
    )

    verified = verify_dsse_envelope(envelope, trusted_verifiers={_KEY_ID: _verify})

    assert verified.verified_key_ids == (_KEY_ID,)


def test_invalid_signature_for_trusted_key_fails_closed() -> None:
    envelope = create_dsse_envelope(
        "application/test",
        b"payload",
        key_id=_KEY_ID,
        sign=_sign,
    )
    tampered = envelope.model_copy(
        update={
            "signatures": (
                DSSESignature(
                    keyid=_KEY_ID,
                    sig=base64.b64encode(b"0" * 32).decode(),
                ),
            )
        }
    )

    with pytest.raises(DSSEVerificationError, match="no valid signature from a trusted key"):
        verify_dsse_envelope(tampered, trusted_verifiers={_KEY_ID: _verify})


def test_trusted_verifier_exception_fails_closed() -> None:
    envelope = create_dsse_envelope(
        "application/test",
        b"payload",
        key_id=_KEY_ID,
        sign=_sign,
    )

    def broken_verifier(message: bytes, signature: bytes) -> bool:
        del message, signature
        raise RuntimeError("verifier unavailable")

    with pytest.raises(DSSEVerificationError, match="no valid signature from a trusted key"):
        verify_dsse_envelope(envelope, trusted_verifiers={_KEY_ID: broken_verifier})


def test_invalid_extra_signature_cannot_poison_valid_trusted_signature() -> None:
    payload = b"payload"
    payload_type = "application/test"
    message = pre_authentication_encode(payload_type, payload)
    envelope = DSSEEnvelope(
        payloadType=payload_type,
        payload=base64.b64encode(payload).decode(),
        signatures=(
            DSSESignature(
                keyid=_SECOND_KEY_ID,
                sig=base64.b64encode(b"0" * 32).decode(),
            ),
            DSSESignature(
                keyid=_KEY_ID,
                sig=base64.b64encode(_sign(message)).decode(),
            ),
        ),
    )

    verified = verify_dsse_envelope(
        envelope,
        trusted_verifiers={
            _KEY_ID: _verify,
            _SECOND_KEY_ID: _verify_second,
        },
    )

    assert verified.verified_key_ids == (_KEY_ID,)


def test_payload_tampering_invalidates_signature() -> None:
    envelope = create_dsse_envelope(
        "application/test",
        b"payload",
        key_id=_KEY_ID,
        sign=_sign,
    )
    tampered = envelope.model_copy(update={"payload": base64.b64encode(b"tampered").decode()})

    with pytest.raises(DSSEVerificationError, match="no valid signature from a trusted key"):
        verify_dsse_envelope(tampered, trusted_verifiers={_KEY_ID: _verify})


def test_expected_payload_and_type_are_verifier_owned_constraints() -> None:
    envelope = create_dsse_envelope(
        "application/test",
        b"payload",
        key_id=_KEY_ID,
        sign=_sign,
    )

    with pytest.raises(DSSEVerificationError, match="payload type"):
        verify_dsse_envelope(
            envelope,
            trusted_verifiers={_KEY_ID: _verify},
            expected_payload_type="application/other",
        )

    with pytest.raises(DSSEVerificationError, match="expected bytes"):
        verify_dsse_envelope(
            envelope,
            trusted_verifiers={_KEY_ID: _verify},
            expected_payload=b"other",
        )


def test_assurance_report_round_trip_preserves_existing_report_root() -> None:
    report = _report()
    original_root = report.report_root

    envelope = sign_assurance_report(report, key_id=_KEY_ID, sign=_sign)
    loaded = verify_assurance_report_envelope(
        envelope,
        trusted_verifiers={_KEY_ID: _verify},
    )

    assert loaded == report
    assert loaded.report_root == original_root
    assert envelope.payloadType == ASSURANCE_REPORT_V6_PAYLOAD_TYPE


def test_evidence_manifest_round_trip_preserves_existing_claims() -> None:
    manifest = _manifest()

    envelope = sign_evidence_manifest(manifest, key_id=_KEY_ID, sign=_sign)
    loaded = verify_evidence_manifest_envelope(
        envelope,
        trusted_verifiers={_KEY_ID: _verify},
    )

    assert loaded == manifest
    assert loaded.evidence_root == manifest.evidence_root
    assert loaded.payload_sha256 == manifest.payload_sha256
    assert envelope.payloadType == EVIDENCE_MANIFEST_V1_PAYLOAD_TYPE


def test_payload_type_prevents_cross_domain_substitution() -> None:
    evidence_envelope = sign_evidence_manifest(_manifest(), key_id=_KEY_ID, sign=_sign)

    with pytest.raises(DSSEVerificationError, match="not an assurance-report"):
        verify_assurance_report_envelope(
            evidence_envelope,
            trusted_verifiers={_KEY_ID: _verify},
        )

    report_envelope = sign_assurance_report(_report(), key_id=_KEY_ID, sign=_sign)
    with pytest.raises(DSSEVerificationError, match="payload type"):
        verify_evidence_manifest_envelope(
            report_envelope,
            trusted_verifiers={_KEY_ID: _verify},
        )


def test_signed_noncanonical_report_json_is_rejected_after_signature_verification() -> None:
    report = _report()
    noncanonical = json.dumps(
        report.model_dump(mode="json"),
        indent=2,
        sort_keys=False,
        allow_nan=False,
    ).encode()
    envelope = create_dsse_envelope(
        ASSURANCE_REPORT_V6_PAYLOAD_TYPE,
        noncanonical,
        key_id=_KEY_ID,
        sign=_sign,
    )

    with pytest.raises(DSSEVerificationError, match="not canonical JSON"):
        verify_assurance_report_envelope(
            envelope,
            trusted_verifiers={_KEY_ID: _verify},
        )


def test_signed_duplicate_json_key_is_rejected_by_strict_parser() -> None:
    report = _report()
    payload = report.model_dump_json().encode()
    duplicate = payload[:-1] + b',"schema_version":"agent-evals/assurance-report/v6"}'
    envelope = create_dsse_envelope(
        ASSURANCE_REPORT_V6_PAYLOAD_TYPE,
        duplicate,
        key_id=_KEY_ID,
        sign=_sign,
    )

    with pytest.raises(DSSEVerificationError, match="strict validation"):
        verify_assurance_report_envelope(
            envelope,
            trusted_verifiers={_KEY_ID: _verify},
        )


@pytest.mark.parametrize(
    "payload",
    [
        "%%%",
        "YQ",
        "YR==",
    ],
)
def test_envelope_rejects_malformed_or_noncanonical_payload_base64(payload: str) -> None:
    with pytest.raises(ValidationError, match="base64"):
        DSSEEnvelope(
            payloadType="application/test",
            payload=payload,
            signatures=(
                DSSESignature(
                    keyid=_KEY_ID,
                    sig=base64.b64encode(b"signature").decode(),
                ),
            ),
        )


def test_signature_rejects_empty_value() -> None:
    with pytest.raises(ValidationError):
        DSSESignature(keyid=_KEY_ID, sig="")


def test_envelope_rejects_duplicate_key_ids() -> None:
    encoded_sig = base64.b64encode(b"signature").decode()

    with pytest.raises(ValidationError, match="key IDs must be unique"):
        DSSEEnvelope(
            payloadType="application/test",
            payload=base64.b64encode(b"payload").decode(),
            signatures=(
                DSSESignature(keyid=_KEY_ID, sig=encoded_sig),
                DSSESignature(keyid=_KEY_ID, sig=encoded_sig),
            ),
        )


def test_envelope_requires_at_least_one_signature() -> None:
    with pytest.raises(ValidationError):
        DSSEEnvelope(
            payloadType="application/test",
            payload=base64.b64encode(b"payload").decode(),
            signatures=(),
        )


def test_signing_primitive_must_return_exact_bytes() -> None:
    with pytest.raises(TypeError, match="exact bytes"):
        create_dsse_envelope(
            "application/test",
            b"payload",
            key_id=_KEY_ID,
            sign=lambda message: "not-bytes",  # type: ignore[arg-type,return-value]
        )


def test_signing_primitive_must_not_return_empty_signature() -> None:
    with pytest.raises(ValueError, match="empty signature"):
        create_dsse_envelope(
            "application/test",
            b"payload",
            key_id=_KEY_ID,
            sign=lambda message: b"",
        )


def test_signing_rejects_empty_key_id() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        create_dsse_envelope(
            "application/test",
            b"payload",
            key_id="",
            sign=_sign,
        )


def test_pae_requires_exact_bytes_payload() -> None:
    with pytest.raises(TypeError, match="exact bytes"):
        pre_authentication_encode("application/test", bytearray(b"x"))  # type: ignore[arg-type]
