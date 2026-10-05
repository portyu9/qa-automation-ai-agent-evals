# Authenticated DSSE Artifact Envelopes

## Purpose

The framework's content-addressed roots remain integrity identities. They detect content changes but do not, by themselves, identify an authorized publisher. The optional DSSE layer in `agent_evals.dsse` adds a separate authentication relation around exact assurance-report or evidence-manifest bytes without changing any historical root algorithm.

This separation is intentional:

```text
report_root / evidence_root / payload_sha256
    = content integrity and identity

DSSE signature + caller-owned trusted verifier policy
    = authentication of the exact signed artifact bytes under that trust policy
```

A signed artifact still carries all of its existing self-validation requirements. Authentication does not replace report rederivation, evidence-store integrity checks, replay, deterministic grading, or release policy.

## Supported payload domains

The initial envelope layer recognizes three explicit media types:

| Artifact | DSSE payload type |
|---|---|
| Assurance Report v6 | `application/vnd.agent-evals.assurance-report.v6+json` |
| Assurance Report v7 | `application/vnd.agent-evals.assurance-report.v7+json` |
| Evidence manifest v1 | `application/vnd.agent-evals.evidence-manifest.v1+json` |

Payload types are part of DSSE pre-authentication encoding. A valid signature over one domain cannot be silently reinterpreted as another artifact class.

Historical report and evidence schemas are unchanged. In particular, adding or removing an outer DSSE envelope never changes `report_root`, `evidence_root`, evidence-store `record_key`, or manifest `payload_sha256`.

## Exact DSSE pre-authentication encoding

The implementation uses DSSE v1 pre-authentication encoding:

```text
DSSEv1 SP LEN(payloadType) SP payloadType SP LEN(payload) SP payload
```

Both lengths are decimal byte counts. The payload type is UTF-8 encoded before its length is calculated. The payload is signed as exact bytes.

Envelope parsing is bounded and fail-closed. The implementation requires:

- non-empty bounded payload type;
- canonical base64 for payload and signatures;
- at least one and at most the configured maximum number of signatures;
- unique non-empty bounded key IDs;
- non-empty bounded decoded signatures;
- a bounded decoded payload.

Alternate base64 spellings that decode to the same bytes are rejected rather than normalized.

## Verifier-owned trust

The envelope does not contain a trusted public key, certificate authority decision, or trust level. `keyid` is only a lookup label.

Verification requires a caller-supplied mapping from trusted key IDs to verification functions. The verifier applies these rules:

1. an unknown key ID has no authority and is ignored;
2. a signature naming a trusted key must verify successfully;
3. an exception or invalid signature from a trusted verifier fails closed;
4. at least one trusted signature must verify;
5. a valid signature from an unknown/untrusted key does not satisfy the policy.

This prevents extensibility from becoming self-declared trust. An attacker cannot add a key to the envelope and thereby make that key trusted.

The caller remains responsible for deciding which verification functions and key IDs are trusted in a given deployment.

## Assurance-report verification

`sign_assurance_report(...)` signs the exact canonical JSON representation of the current report object.

`verify_assurance_report_envelope(...)` establishes the relation in this order:

1. require a recognized assurance-report payload type;
2. verify the DSSE signature under caller-owned trusted-verifier policy;
3. strictly decode signed JSON with duplicate-key, non-finite-number, Unicode-scalar, and nesting checks;
4. load the exact v6 or v7 Pydantic model;
5. let the report model rederive its existing trial, provenance, reliability, gate, and report-root constraints;
6. canonicalize the validated report again and require byte-for-byte equality with the signed payload.

A signed but non-canonical serialization is therefore rejected. A cryptographically authentic malformed or internally inconsistent report does not become a valid assurance report.

The signature authenticates the exact report artifact under the selected trusted key policy. It does not prove that the subject, provider, environment, judge, target system, or human approver was independently authenticated unless a separate evidence contract establishes that fact.

## Evidence-manifest verification

`sign_evidence_manifest(...)` signs the exact canonical JSON representation of `ArtifactManifest`.

`verify_evidence_manifest_envelope(...)` authenticates and strictly validates that manifest under caller-owned trusted-verifier policy.

The signed manifest binds claims including:

- record key;
- trial/subject/scenario identities;
- evidence root;
- payload SHA-256;
- payload byte length.

The signature does not replace `LocalEvidenceStore.read()`. Store verification must still establish that the actual persisted payload has the manifest's exact byte length and SHA-256, parses as strict `TrialEvidence`, matches the bound identities, and rederives the same evidence root.

Consequently:

```text
valid signed manifest + missing/tampered payload
    != valid stored evidence
```

A manifest signature authenticates the manifest claims under the configured key policy; it does not attest to current filesystem state or external target state.

## Cryptographic-provider boundary

The core module deliberately accepts caller-provided signing and verification callables rather than selecting a universal key system. This keeps cryptographic mechanism separate from trust policy and permits deployments to integrate an appropriate HSM, KMS, Sigstore, offline key, or other reviewed implementation.

The repository's deterministic tests use a local test-only signing primitive solely to exercise DSSE framing and trust semantics. That fixture is not a production key-management recommendation.

## Non-claims

The DSSE envelope layer does not itself provide:

- key generation, custody, HSM/KMS policy, or secret storage;
- trusted-key distribution or trust-store bootstrap;
- certificate-chain or organizational identity policy;
- key rotation or revocation;
- trusted timestamps or freshness;
- transparency-log inclusion/monitoring;
- signer authorization beyond the caller's configured trusted-verifier mapping;
- non-repudiation as a legal or organizational claim;
- remote target attestation;
- provider/model identity attestation;
- authenticated human approval identity;
- automatic signing of every locally persisted record;
- retroactive authentication of historical unsigned artifacts.

A historical unsigned report or evidence record remains unsigned. Its existing hashes continue to provide exactly the integrity claim they always provided.

## Relationship to release provenance

The trusted-main release workflow has a separate Sigstore/SLSA provenance domain for retained release files. That workflow binds repository/workflow/source/run provenance to release artifacts.

The framework-level DSSE layer serves a different purpose: it can authenticate an individual assurance report or evidence manifest under an explicitly supplied verifier trust policy. Neither domain silently upgrades the other.

A release provenance attestation does not mean every historical assurance report was signed. Likewise, a signed assurance report does not by itself establish how a release package was built.

[← Documentation hub](README.md)
