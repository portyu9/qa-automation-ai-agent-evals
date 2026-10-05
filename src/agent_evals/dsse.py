"""Optional DSSE envelopes for authenticated assurance artifacts.

The framework's existing report roots, evidence roots, and evidence manifests are integrity
identities. This module adds an optional authentication envelope without changing those historical
formats. Trust is verifier-owned: envelope key IDs can only select a verifier from a caller-supplied
trusted registry and never carry their own trust authority.

Cryptographic key generation, storage, distribution, rotation, revocation, timestamping, and
transparency-log policy remain outside this module. Callers provide the signing and verification
primitives that implement their selected cryptographic trust system.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from agent_evals._strict_json import StrictJsonError, strict_json_loads
from agent_evals.assurance.report import AssuranceReport
from agent_evals.assurance.report_v7 import AssuranceReportV7
from agent_evals.evidence.store import ArtifactManifest

ASSURANCE_REPORT_V6_PAYLOAD_TYPE = "application/vnd.agent-evals.assurance-report.v6+json"
ASSURANCE_REPORT_V7_PAYLOAD_TYPE = "application/vnd.agent-evals.assurance-report.v7+json"
EVIDENCE_MANIFEST_V1_PAYLOAD_TYPE = "application/vnd.agent-evals.evidence-manifest.v1+json"

MAX_DSSE_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_DSSE_SIGNATURE_BYTES = 16 * 1024
MAX_DSSE_SIGNATURES = 16
MAX_DSSE_TRUSTED_VERIFIERS = 256
MAX_DSSE_ENVELOPE_BYTES = 24 * 1024 * 1024
MAX_DSSE_PAYLOAD_TYPE_UTF8_BYTES = 512
MAX_DSSE_KEY_ID_UTF8_BYTES = 1_024

SignatureFunction: TypeAlias = Callable[[bytes], bytes]
SignatureVerifier: TypeAlias = Callable[[bytes, bytes], bool]
AssuranceReportArtifact: TypeAlias = AssuranceReport | AssuranceReportV7


class DSSEVerificationError(ValueError):
    """A DSSE envelope did not establish the caller-requested authenticated relation."""


class DSSESignature(BaseModel):
    """One bounded DSSE signature entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    keyid: str = Field(min_length=1, strict=True)
    sig: str = Field(min_length=1, strict=True)

    @field_validator("keyid")
    @classmethod
    def validate_keyid(cls, value: str) -> str:
        encoded = value.encode("utf-8")
        if len(encoded) > MAX_DSSE_KEY_ID_UTF8_BYTES:
            raise ValueError(
                f"DSSE keyid exceeds maximum UTF-8 bytes {MAX_DSSE_KEY_ID_UTF8_BYTES}"
            )
        return value

    @field_validator("sig")
    @classmethod
    def validate_signature_base64(cls, value: str) -> str:
        decoded = _decode_canonical_base64(
            value,
            label="DSSE signature",
            max_decoded_bytes=MAX_DSSE_SIGNATURE_BYTES,
        )
        if not decoded:
            raise ValueError("DSSE signature bytes must not be empty")
        return value


class DSSEEnvelope(BaseModel):
    """Strict bounded DSSE JSON envelope.

    The field spelling intentionally follows the DSSE envelope grammar. The envelope carries no
    certificate, public key, or trust-level field: a key ID is only a lookup label into verifier
    policy supplied separately by the caller.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    payloadType: str = Field(min_length=1, strict=True)
    payload: str = Field(strict=True)
    signatures: tuple[DSSESignature, ...] = Field(
        min_length=1,
        max_length=MAX_DSSE_SIGNATURES,
    )

    @field_validator("payloadType")
    @classmethod
    def validate_payload_type(cls, value: str) -> str:
        encoded = value.encode("utf-8")
        if len(encoded) > MAX_DSSE_PAYLOAD_TYPE_UTF8_BYTES:
            raise ValueError(
                "DSSE payload type exceeds maximum UTF-8 bytes "
                f"{MAX_DSSE_PAYLOAD_TYPE_UTF8_BYTES}"
            )
        return value

    @field_validator("payload")
    @classmethod
    def validate_payload_base64(cls, value: str) -> str:
        _decode_canonical_base64(
            value,
            label="DSSE payload",
            max_decoded_bytes=MAX_DSSE_PAYLOAD_BYTES,
        )
        return value

    @model_validator(mode="after")
    def require_unique_keyids(self) -> Self:
        keyids = tuple(signature.keyid for signature in self.signatures)
        if len(set(keyids)) != len(keyids):
            raise ValueError("DSSE signature key IDs must be unique")
        return self


@dataclass(frozen=True, slots=True)
class VerifiedDSSEPayload:
    """Payload bytes plus the caller-trusted key IDs that verified them."""

    payload_type: str
    payload: bytes
    verified_key_ids: tuple[str, ...]


def parse_dsse_envelope(value: bytes | str) -> DSSEEnvelope:
    """Strictly decode the repository's bounded DSSE JSON envelope profile."""

    if type(value) is bytes:
        raw_bytes = value
    elif type(value) is str:
        try:
            raw_bytes = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise DSSEVerificationError(
                "DSSE envelope JSON must contain only Unicode scalar values"
            ) from exc
    else:
        raise DSSEVerificationError("DSSE envelope JSON must be exact bytes or text")
    if len(raw_bytes) > MAX_DSSE_ENVELOPE_BYTES:
        raise DSSEVerificationError(
            f"DSSE envelope exceeds maximum bytes {MAX_DSSE_ENVELOPE_BYTES}"
        )
    try:
        raw = strict_json_loads(
            raw_bytes,
            label="DSSE envelope",
            require_object=True,
        )
        return DSSEEnvelope.model_validate(raw)
    except (StrictJsonError, ValidationError) as exc:
        raise DSSEVerificationError("DSSE envelope failed strict validation") from exc


def pre_authentication_encode(payload_type: str, payload: bytes) -> bytes:
    """Return DSSE v1 pre-authentication encoding for one payload.

    The layout is DSSEv1, a space, the byte length of the payload type, the payload type,
    the byte length of the payload, and the payload, with spaces between each component.
    Lengths count bytes, not characters.
    """

    payload_type_bytes = _payload_type_bytes(payload_type)
    _require_exact_payload_bytes(payload)
    if len(payload) > MAX_DSSE_PAYLOAD_BYTES:
        raise ValueError(f"DSSE payload exceeds maximum bytes {MAX_DSSE_PAYLOAD_BYTES}")
    return b"".join(
        (
            b"DSSEv1 ",
            str(len(payload_type_bytes)).encode("ascii"),
            b" ",
            payload_type_bytes,
            b" ",
            str(len(payload)).encode("ascii"),
            b" ",
            payload,
        )
    )


def create_dsse_envelope(
    payload_type: str,
    payload: bytes,
    *,
    key_id: str,
    sign: SignatureFunction,
) -> DSSEEnvelope:
    """Sign one exact payload with a caller-owned signing primitive."""

    message = pre_authentication_encode(payload_type, payload)
    if type(key_id) is not str or not key_id:
        raise ValueError("DSSE key ID must be a non-empty exact string")
    signature = sign(message)
    if type(signature) is not bytes:
        raise TypeError("DSSE signing primitive must return exact bytes")
    if not signature:
        raise ValueError("DSSE signing primitive returned an empty signature")
    if len(signature) > MAX_DSSE_SIGNATURE_BYTES:
        raise ValueError(
            f"DSSE signing primitive returned more than {MAX_DSSE_SIGNATURE_BYTES} bytes"
        )
    return DSSEEnvelope(
        payloadType=payload_type,
        payload=base64.b64encode(payload).decode("ascii"),
        signatures=(
            DSSESignature(
                keyid=key_id,
                sig=base64.b64encode(signature).decode("ascii"),
            ),
        ),
    )


def verify_dsse_envelope(
    envelope: DSSEEnvelope,
    *,
    trusted_verifiers: Mapping[str, SignatureVerifier],
    expected_payload_type: str | None = None,
    expected_payload: bytes | None = None,
) -> VerifiedDSSEPayload:
    """Verify an envelope against caller-owned trust policy.

    DSSE key IDs are unauthenticated hints. They influence verifier ordering but never establish
    signer identity. The authoritative key IDs returned on success are the caller-trusted keys
    whose verifier actually accepted a signature.
    """

    payload = _decode_canonical_base64(
        envelope.payload,
        label="DSSE payload",
        max_decoded_bytes=MAX_DSSE_PAYLOAD_BYTES,
    )
    if expected_payload_type is not None and envelope.payloadType != expected_payload_type:
        raise DSSEVerificationError(
            "DSSE payload type does not match the verifier-requested domain"
        )
    if expected_payload is not None:
        _require_exact_payload_bytes(expected_payload)
        if not hmac.compare_digest(payload, expected_payload):
            raise DSSEVerificationError("DSSE payload does not match expected bytes")

    trusted_items = _trusted_verifier_items(trusted_verifiers)
    message = pre_authentication_encode(envelope.payloadType, payload)
    verified_key_ids: list[str] = []
    for signature in envelope.signatures:
        signature_bytes = _decode_canonical_base64(
            signature.sig,
            label="DSSE signature",
            max_decoded_bytes=MAX_DSSE_SIGNATURE_BYTES,
        )
        candidates = trusted_items
        if signature.keyid:
            hinted = tuple(item for item in trusted_items if item[0] == signature.keyid)
            if hinted:
                candidates = hinted + tuple(
                    item for item in trusted_items if item[0] != signature.keyid
                )

        for trusted_key_id, verifier in candidates:
            try:
                valid = verifier(message, signature_bytes)
            except Exception:
                continue
            if valid is True:
                if trusted_key_id not in verified_key_ids:
                    verified_key_ids.append(trusted_key_id)
                break

    if not verified_key_ids:
        raise DSSEVerificationError("DSSE envelope has no valid signature from a trusted key")
    return VerifiedDSSEPayload(
        payload_type=envelope.payloadType,
        payload=payload,
        verified_key_ids=tuple(verified_key_ids),
    )


def sign_assurance_report(
    report: AssuranceReportArtifact,
    *,
    key_id: str,
    sign: SignatureFunction,
) -> DSSEEnvelope:
    """Create a DSSE envelope over exact canonical assurance-report JSON."""

    if isinstance(report, AssuranceReportV7):
        payload_type = ASSURANCE_REPORT_V7_PAYLOAD_TYPE
    elif isinstance(report, AssuranceReport):
        payload_type = ASSURANCE_REPORT_V6_PAYLOAD_TYPE
    else:
        raise TypeError("unsupported assurance report type for DSSE signing")
    return create_dsse_envelope(
        payload_type,
        _canonical_model_json(report),
        key_id=key_id,
        sign=sign,
    )


def verify_assurance_report_envelope(
    envelope: DSSEEnvelope,
    *,
    trusted_verifiers: Mapping[str, SignatureVerifier],
) -> AssuranceReportArtifact:
    """Authenticate, strictly parse, canonically bind, and revalidate an assurance report."""

    if envelope.payloadType == ASSURANCE_REPORT_V6_PAYLOAD_TYPE:
        model_type: type[AssuranceReport] | type[AssuranceReportV7] = AssuranceReport
    elif envelope.payloadType == ASSURANCE_REPORT_V7_PAYLOAD_TYPE:
        model_type = AssuranceReportV7
    else:
        raise DSSEVerificationError("DSSE envelope is not an assurance-report payload type")

    verified = verify_dsse_envelope(
        envelope,
        trusted_verifiers=trusted_verifiers,
        expected_payload_type=envelope.payloadType,
    )
    try:
        raw = strict_json_loads(
            verified.payload,
            label="signed assurance report",
            require_object=True,
        )
        report = model_type.model_validate(raw)
    except (StrictJsonError, ValidationError) as exc:
        raise DSSEVerificationError("signed assurance report failed strict validation") from exc

    canonical = _canonical_model_json(report)
    if not hmac.compare_digest(canonical, verified.payload):
        raise DSSEVerificationError("signed assurance report payload is not canonical JSON")
    return report


def sign_evidence_manifest(
    manifest: ArtifactManifest,
    *,
    key_id: str,
    sign: SignatureFunction,
) -> DSSEEnvelope:
    """Create a DSSE envelope over exact canonical evidence-manifest JSON."""

    if not isinstance(manifest, ArtifactManifest):
        raise TypeError("unsupported evidence manifest type for DSSE signing")
    return create_dsse_envelope(
        EVIDENCE_MANIFEST_V1_PAYLOAD_TYPE,
        _canonical_model_json(manifest),
        key_id=key_id,
        sign=sign,
    )


def verify_evidence_manifest_envelope(
    envelope: DSSEEnvelope,
    *,
    trusted_verifiers: Mapping[str, SignatureVerifier],
) -> ArtifactManifest:
    """Authenticate and strictly revalidate one evidence manifest.

    The signed manifest authenticates the manifest claims under the caller's trusted key policy.
    The evidence payload itself remains subject to ordinary store verification against the
    manifest's payload SHA-256, byte length, identities, and evidence root.
    """

    verified = verify_dsse_envelope(
        envelope,
        trusted_verifiers=trusted_verifiers,
        expected_payload_type=EVIDENCE_MANIFEST_V1_PAYLOAD_TYPE,
    )
    try:
        raw = strict_json_loads(
            verified.payload,
            label="signed evidence manifest",
            require_object=True,
        )
        manifest = ArtifactManifest.model_validate(raw)
    except (StrictJsonError, ValidationError) as exc:
        raise DSSEVerificationError("signed evidence manifest failed strict validation") from exc

    canonical = _canonical_model_json(manifest)
    if not hmac.compare_digest(canonical, verified.payload):
        raise DSSEVerificationError("signed evidence manifest payload is not canonical JSON")
    return manifest


def _canonical_model_json(model: BaseModel) -> bytes:
    return json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _trusted_verifier_items(
    trusted_verifiers: Mapping[str, SignatureVerifier],
) -> tuple[tuple[str, SignatureVerifier], ...]:
    items = tuple(trusted_verifiers.items())
    if not items:
        raise DSSEVerificationError("DSSE verification requires at least one trusted verifier")
    if len(items) > MAX_DSSE_TRUSTED_VERIFIERS:
        raise DSSEVerificationError(
            "DSSE trusted verifier registry exceeds maximum entries "
            f"{MAX_DSSE_TRUSTED_VERIFIERS}"
        )
    for key_id, verifier in items:
        if type(key_id) is not str or not key_id:
            raise DSSEVerificationError(
                "DSSE trusted verifier key IDs must be non-empty exact strings"
            )
        if not callable(verifier):
            raise DSSEVerificationError(
                f"DSSE trusted verifier for key {key_id!r} is not callable"
            )
    return items


def _payload_type_bytes(payload_type: str) -> bytes:
    if type(payload_type) is not str or not payload_type:
        raise ValueError("DSSE payload type must be a non-empty exact string")
    try:
        encoded = payload_type.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("DSSE payload type must contain only Unicode scalar values") from exc
    if len(encoded) > MAX_DSSE_PAYLOAD_TYPE_UTF8_BYTES:
        raise ValueError(
            "DSSE payload type exceeds maximum UTF-8 bytes "
            f"{MAX_DSSE_PAYLOAD_TYPE_UTF8_BYTES}"
        )
    return encoded


def _require_exact_payload_bytes(payload: bytes) -> None:
    if type(payload) is not bytes:
        raise TypeError("DSSE payload must be exact bytes")


def _decode_canonical_base64(
    value: str,
    *,
    label: str,
    max_decoded_bytes: int,
) -> bytes:
    if type(value) is not str:
        raise ValueError(f"{label} must be exact base64 text")
    max_encoded_chars = 4 * ((max_decoded_bytes + 2) // 3)
    if len(value) > max_encoded_chars:
        raise ValueError(f"{label} exceeds maximum decoded bytes {max_decoded_bytes}")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise ValueError(f"{label} must be canonical base64") from exc
    if len(decoded) > max_decoded_bytes:
        raise ValueError(f"{label} exceeds maximum decoded bytes {max_decoded_bytes}")
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError(f"{label} must use canonical base64 encoding")
    return decoded
