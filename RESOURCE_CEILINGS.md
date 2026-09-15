# Evaluator resource ceilings

The evaluator applies explicit resource ceilings before trust-critical JSON canonicalization and hashing. These ceilings are an ingestion and denial-of-service safety policy. They do not change the historical `TrialEvidence/v2` evidence-root domain or the canonical/root algorithm for material that remains within the current limits.

## Default limits

| Material | Maximum nesting depth | Maximum JSON nodes | Maximum UTF-8 material bytes |
| --- | ---: | ---: | ---: |
| `EvidenceEvent.payload` | 32 | 8,192 | 256 KiB |
| `TrialEvidence.final_state` | 32 | 32,768 | 1 MiB |
| Receipt material covered by the shared guard | 48 | 65,536 | 2 MiB |

A `TrialEvidence` envelope additionally permits at most **4,096 events** and at most **1 MiB of UTF-8** in `final_output`.

Guarded JSON integer values additionally permit at most **4,096 decimal digits**. The validator applies a cheap integer-magnitude check before decimal rendering, then verifies the exact rendered digit count. This keeps grossly oversized Python integers from forcing unbounded decimal conversion before the evaluator can reject them.

The JSON-material byte budget counts UTF-8 bytes of string values and object keys plus a bounded representation of scalar literals. It is a pre-canonicalization safety budget, not a promise that the eventual serialized representation has exactly the same byte count. Node-count and depth ceilings bound structural overhead separately.

## Where the guard applies

`EvidenceEvent.payload` and `TrialEvidence.final_state` are checked before the framework performs their existing sorted-JSON detach/canonicalize round trip. Event-count validation runs before Pydantic validates each nested event, and final-output byte validation runs before evidence-root traversal.

The common receipt-material guard is applied before canonical receipt hashing for the higher-variance nested receipt domains in the assurance kernel: attack delivery, semantic judgment, retrieval delivery, and side-effect idempotency. Those receipt domains and canonicalization algorithms remain unchanged for accepted material. Other current receipt models are already structurally bounded by their typed scalar fields and bounded tuples; future receipt domains containing variable JSON material should use the shared guard before canonical hashing.

The guard is iterative rather than recursively walking Python containers. It rejects excessive depth, excessive nodes, excessive UTF-8 material, excessive integer digits, reference cycles, unsupported JSON value types, and non-finite floating-point values before sorted JSON serialization is invoked. Repeated aliases that are not cycles remain valid JSON-by-value material.

Trust-critical JSON material must use exact built-in `dict`, `list`, `tuple`, `str`, `int`, `float`, `bool`, and `None` values. Python subclasses are rejected before the guard calls potentially overridable length, iteration, mapping, encoding, or scalar-rendering behavior. This is intentionally stricter than treating arbitrary Python objects that happen to serialize like JSON as trusted canonicalization input.

## Statistical computational limits

The deterministic statistical kernels also enforce evaluator-owned computational ceilings before avoidable copying or expensive arithmetic:

| Statistical input | Maximum |
| --- | ---: |
| verdicts in one `ReliabilityReport.from_verdicts(...)` call | 100,000 trials |
| pairs in one `PairedComparison.compare(...)` call | 100,000 pairs |
| discordant outcomes accepted by the exact McNemar helper | 100,000 outcomes |
| reliability retry depth `k` | 1,000,000 |

Statistical vectors must be exact built-in `list` or `tuple` objects. This prevents a hostile sequence subclass from running attacker-controlled `__len__` or iteration behavior before the evaluator has established the size bound. Reliability counting is one pass over the admitted vector. Paired comparison validates and classifies pairs in one pass rather than materializing a duplicate combined verdict tuple.

The two-sided exact McNemar/binomial test retains the same statistical hypothesis and decision rule, but its lower-tail calculation now starts from one exact binomial coefficient and walks adjacent probability masses by their recurrence ratio. It no longer recomputes a large `comb(...)` independently for every tail index. The public result remains a finite float in `[0, 1]`; mathematically tiny tails may underflow to `0.0`, as already allowed by the prior large-count numeric hardening.

The `k` ceiling is an evaluator computational policy around the existing algebraic `pass@k` and `pass^k` transforms. It does not make those transforms release authority, establish independence, or imply that one million retries are operationally meaningful.

## Runtime outcome semantics

When a live adapter returns material that cannot be normalized inside these limits, the framework treats that as evaluator uncertainty. `TrialRunner` emits its existing `invalid_adapter_result` evaluation error and returns `BLOCKED` before deterministic or semantic grading. Resource-limit rejection is not evidence that the subject failed its task and must not be converted into `FAIL`.

`BLOCKED` and `INCONCLUSIVE` remain distinct from subject `FAIL` throughout reporting and release policy.

Statistical API limit violations are invalid evaluator inputs and raise validation errors before a statistical report/comparison exists. They are not silently converted into PASS, FAIL, BLOCKED, or INCONCLUSIVE trial verdicts.

## Historical compatibility

The accepted-material `TrialEvidence/v2` root algorithm is unchanged. The new limits nevertheless tighten the normal evaluator's admissible input domain. Historical evidence that was valid under an older release but exceeds the current safety policy is not silently grandfathered into ordinary live/replay evaluation. The exact-built-in and integer-digit requirements are part of that current safety policy as well: logically JSON-like Python subclass objects or unusually large integers that older in-process callers may have passed are rejected before canonicalization today.

If such material must be examined, it should be handled through an explicitly isolated legacy inspection or migration tool with its own operator-controlled resource envelope rather than by disabling the normal evaluator's safety ceilings.

This policy is intentionally separate from schema migration: applying a resource ceiling does not reinterpret an old evidence root, and exceeding a current ceiling does not make an old hash invalid as an integrity value produced under its original environment.

## Complexity boundary

The structural, byte, scalar, and exact-type checks bound the amount and shape of material admitted to the existing sorted-JSON canonicalizer. Adversarial tests cover deep/cyclic/wide input, reverse-order maps, hostile Python subclasses, exact/over integer digits, and rejection before canonicalization for over-budget material. The canonical JSON algorithm and all existing evidence/receipt root domains remain unchanged for accepted material.

Statistical tests cover exact/over vector and retry ceilings, large discordant counts, a balanced tail at the maximum admitted discordance, malformed values, and unresolved-verdict semantics. Dedicated wall-clock performance regression policy remains separately tracked from these deterministic admission and operation bounds.

## Nonclaims

These ceilings do **not** establish constant-time or constant-memory behavior, eliminate every algorithmic-complexity attack, bound memory consumed by a provider or network stack before data reaches Python, prove operating-system isolation, or replace dedicated performance/fuzz/stress work.

Statistical ceilings and recurrence arithmetic do not prove IID behavior, independence, stationarity, population representativeness, provider behavior, or calibration validity. They do not widen release authority and do not turn `BLOCKED` / `INCONCLUSIVE` into subject `FAIL`.

Evidence and receipt hashes remain integrity identities only. They are not signatures, authenticated producer identities, billing/provider attestations, non-repudiation proofs, or proof that a remote system enforced the evaluator's limits.
