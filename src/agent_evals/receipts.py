"""Common receipt envelope metadata without collapsing domain-specific trust."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.evidence.models import EvidenceEvent

_RECEIPT_PROTOCOL: Literal["agent-evals/receipt-envelope/v1"] = "agent-evals/receipt-envelope/v1"
_RECEIPT_DOMAIN = b"agent-evals/receipt-envelope/v1\0"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


class ReceiptEnvelopeV1(BaseModel):
    """Content-addressed metadata for an already domain-specific receipt.

    The envelope proves only that this metadata and payload digest were bound together. It does not
    replace or upgrade the semantic verifier for the embedded receipt domain and is not a signature.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/receipt-envelope/v1"] = _RECEIPT_PROTOCOL
    receipt_schema: str = Field(pattern=r"^agent-evals/[a-z0-9._/-]+/v[0-9]+$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    envelope_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_event(cls, event: EvidenceEvent) -> Self:
        if type(event) is not EvidenceEvent:
            raise ValueError("receipt envelope requires an exact EvidenceEvent")
        schema = event.payload.get("schema_version")
        root = event.payload.get("receipt_root")
        if not isinstance(schema, str) or not isinstance(root, str):
            raise ValueError("receipt event payload must expose schema_version and receipt_root")
        payload_sha256 = hashlib.sha256(_canonical_bytes(event.payload)).hexdigest()
        unsigned: dict[str, Any] = {
            "schema_version": _RECEIPT_PROTOCOL,
            "receipt_schema": schema,
            "receipt_root": root,
            "event_digest": event.digest,
            "payload_sha256": payload_sha256,
        }
        envelope_root = hashlib.sha256(
            _RECEIPT_DOMAIN + _canonical_bytes(unsigned)
        ).hexdigest()
        return cls(**unsigned, envelope_root=envelope_root)

    @model_validator(mode="after")
    def verify_envelope_root(self) -> Self:
        unsigned = self.model_dump(mode="json", exclude={"envelope_root"})
        expected = hashlib.sha256(
            _RECEIPT_DOMAIN + _canonical_bytes(unsigned)
        ).hexdigest()
        if self.envelope_root != expected:
            raise ValueError("receipt envelope root mismatch")
        return self
