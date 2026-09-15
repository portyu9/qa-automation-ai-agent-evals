# Evaluator resource ceilings

The evaluator applies explicit resource ceilings before trust-critical JSON canonicalization and hashing. These ceilings are an ingestion and denial-of-service safety policy. They do not change the historical `TrialEvidence/v2` evidence-root domain or the canonical/root algorithm for material that remains within the current limits.

## Default limits

| Material | Maximum nesting depth | Maximum JSON nodes | Maximum UTF-8 material bytes |
| --- | ---: | ---: | ---: |
| `EvidenceEvent.payload` | 32 | 8,192 | 256 KiB |
| `TrialEvidence.final_state` | 32 | 32,768 | 1 MiB |
| Receipt material covered by the shared guard | 48 | 65,536 | 2 MiB |

A `TrialEvidence` envelope additionally permits at most **4,096 events** and at most **1 MiB of UTF-8** in `final_output`.

The JSON-material byte budget counts UTF-8 bytes of string values and object keys plus a bounded representation of scalar literals. It is a pre-canonicalization safety budget, not a promise that the eventual serialized representation has exactly the same byte count. Node-count and depth ceilings bound structural overhead separately.

## Where the guard applies

`EvidenceEvent.payload` and `TrialEvidence.final_state` are checked before the framework performs their existing sorted-JSON detach/canonicalize round trip. Event-count validation runs before Pydantic validates each nested event, and final-output byte validation runs before evidence-root traversal.

The common receipt-material guard is applied before canonical receipt hashing for the higher-variance nested receipt domains in the assurance kernel: attack delivery, semantic judgment, retrieval delivery, and side-effect idempotency. Those receipt domains and canonicalization algorithms remain unchanged for accepted material. Other current receipt models are already structurally bounded by their typed scalar fields and bounded tuples; future receipt domains containing variable JSON material should use the shared guard before canonical hashing.

The guard is iterative rather than recursively walking Python containers. It rejects excessive depth, excessive nodes, excessive UTF-8 material, reference cycles, unsupported JSON value types, and non-finite floating-point values before sorted JSON serialization is invoked. Repeated aliases that are not cycles remain valid JSON-by-value material.

## Runtime outcome semantics

When a live adapter returns material that cannot be normalized inside these limits, the framework treats that as evaluator uncertainty. `TrialRunner` emits its existing `invalid_adapter_result` evaluation error and returns `BLOCKED` before deterministic or semantic grading. Resource-limit rejection is not evidence that the subject failed its task and must not be converted into `FAIL`.

`BLOCKED` and `INCONCLUSIVE` remain distinct from subject `FAIL` throughout reporting and release policy.

## Historical compatibility

The accepted-material `TrialEvidence/v2` root algorithm is unchanged. The new limits nevertheless tighten the normal evaluator's admissible input domain. Historical evidence that was valid under an older release but exceeds the current safety policy is not silently grandfathered into ordinary live/replay evaluation. If such material must be examined, it should be handled through an explicitly isolated legacy inspection or migration tool with its own operator-controlled resource envelope rather than by disabling the normal evaluator's safety ceilings.

This policy is intentionally separate from schema migration: applying a resource ceiling does not reinterpret an old evidence root, and exceeding a current ceiling does not make an old hash invalid as an integrity value produced under its original environment.

## Nonclaims

These ceilings do **not** establish constant-time or constant-memory behavior, eliminate every algorithmic-complexity attack, bound memory consumed by a provider or network stack before data reaches Python, prove operating-system isolation, or complete the broader complexity/fuzz work tracked separately from this resource-ceiling slice.

Evidence and receipt hashes remain integrity identities only. They are not signatures, authenticated producer identities, billing/provider attestations, non-repudiation proofs, or proof that a remote system enforced the evaluator's limits.
