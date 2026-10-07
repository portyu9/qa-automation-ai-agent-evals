# Durable Evidence Minimization

## Purpose

Durable evidence persistence has a different trust boundary from operational logging. The framework
already suppresses a bounded set of secret forms before non-authoritative diagnostic sinks. That
does **not** prove that persisted `TrialEvidence` is minimized.

The persistence stores therefore run a separate, versioned minimization contract **before** durable
payload bytes, content-addressed keys, manifests, or persisted evidence roots are committed.

The governing rule is:

```text
diagnostic secret suppression != durable evidence minimization
```

## Policy identity

`EvidenceMinimizationPolicy` is versioned as
`agent-evals/evidence-minimization-policy/v1`. Its canonical policy identity binds:

- the enabled bounded credential recognizers;
- the canonical set of operator-declared PII paths;
- the traversal ceiling;
- the redaction-count ceiling.

Policy identity does not contain classified values.

The built-in credential recognizers are intentionally bounded. They cover sensitive-key variants and
selected token forms such as bearer credentials, OpenAI-style `sk-` tokens, GitHub tokens, AWS
access-key identifiers, and explicit password/token/secret assignments. This is a deterministic
minimization mechanism, **not** a complete credential detector.

## Operator-declared PII paths

Operator PII classification uses a strict JSON-Pointer-like grammar over only the free-form evidence
surfaces that the persistence layer is allowed to rewrite:

- `/final_state/...`;
- `/final_output`, which classifies the complete output string;
- `/events/<index|*>/payload/...`.

`~0` and `~1` escaping follow JSON Pointer semantics. The only wildcard is the event index.
Paths have explicit byte, segment, count, traversal, and redaction ceilings. Duplicate or overlapping
paths fail policy validation rather than relying on order-dependent behavior.

Operator-declared PII classification is distinct from heuristic recognition. Declaring a path says
that the operator has chosen to classify that field. It does not mean the framework discovered the
field independently or proved that every PII field has been identified.

## Redaction-safe versus authority-bearing material

The persistence layer may redact classified values from:

- `final_state`;
- `final_output`;
- non-critical `STATE`, `OUTPUT`, `EVALUATION_ERROR`, and `RUNTIME_ERROR` event payloads.

Other event kinds carry or may carry authority, protocol, approval, side-effect, retrieval, semantic,
or policy meaning. Critical events are also authority-sensitive regardless of kind.

When credential or operator-declared PII material intersects one of those authority-bearing payloads,
persistence fails closed. The framework does **not** silently rewrite an approval, receipt, handoff,
tool/protocol observation, semantic judgment, or other authority-bearing event and then claim the
result is equivalent replay evidence.

This is deliberately non-compensatory: data minimization cannot rescue an artifact by changing the
meaning of the authority evidence that would have been persisted.

## Markers and raw-value handling

Classified values are replaced by fixed class markers:

```text
[REDACTED:CREDENTIAL]
[REDACTED:OPERATOR_PII]
```

The original value is never copied into a marker. Persistence errors describe only the class/boundary
failure and do not echo the classified value.

The minimization receipt contains:

- exact policy identity;
- canonical counts for the bounded sensitive-data classes;
- the resulting minimized evidence root;
- a domain-separated receipt root.

It deliberately does **not** contain the original evidence root, a raw-value digest, a secret
fingerprint, or any other stable derivative of classified material. Hashing a credential is not a
safe substitute for deleting it from durable evidence.

## Persistence ordering

`LocalEvidenceStore`, `HardenedPosixEvidenceStore`, and
`ContentAddressedEvidenceStore` invoke minimization inside their normal `write()` path.

The ordering is:

1. detach and validate the incoming `TrialEvidence`;
2. apply the bounded minimization policy;
3. reconstruct and validate the minimized `TrialEvidence`;
4. derive the minimized evidence root;
5. only then derive local payload hashes/record material or content-addressed blob keys;
6. only then cross the filesystem/backend durable-write boundary.

`write_with_receipt()` exposes the associated minimization receipt without changing the historical
`write()` return type.

For evidence containing no classified material, the minimized evidence is byte-for-byte equivalent
under the existing canonical representation and retains the historical `TrialEvidence/v2`
`evidence_root`. The framework does not reinterpret existing unredacted v2 roots.

## Determinism and idempotence

Policy paths are canonicalized and sorted. Re-applying the same policy to already minimized evidence
produces the same evidence and the same receipt.

A fixed marker is treated as already minimized material. Idempotence does not turn that marker into
proof that the pre-minimized value was correctly classified by some earlier system; the receipt
establishes only the deterministic transformation relationship for the evidence presented to this
persistence boundary.

## Explicit non-claims

Durable minimization is **not** proof of:

- complete PII discovery;
- de-identification or anonymization;
- GDPR, HIPAA, PCI, SOC, or other regulatory compliance;
- consent or lawful processing;
- data residency or geographic storage policy;
- absence of sensitive information outside the configured/recognized classes;
- authenticated provenance for the stored artifact;
- reversibility or semantic equivalence to the unredacted raw evidence.

The transformation is intentionally lossy. A minimized persisted artifact supports the semantics that
remain after redaction. If required authority-bearing material cannot be retained safely, persistence
fails rather than minting a misleading replayable artifact.

## Relationship to operational observability

`src/agent_evals/runtime/observability.py` keeps its existing non-authoritative sink suppression.
That layer remains useful for diagnostics, but it neither invokes nor substitutes for the durable
persistence policy described here.

Likewise, this persistence policy does not upgrade operational telemetry into evaluation evidence.
BLOCKED versus FAIL semantics, evidence producer authority, receipt domains, release authority, and
all existing hash-versus-authentication non-claims remain unchanged.
