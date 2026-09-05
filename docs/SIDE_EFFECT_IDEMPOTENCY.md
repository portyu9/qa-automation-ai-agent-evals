# Side-Effect Idempotency Assurance

## Purpose

This feature evaluates one narrow but important property: whether **two agent attempts to perform the same scenario-bound logical operation produce at most one observable physical effect**.

It exists because retry safety cannot be inferred from tool prose. A second callback returning `"duplicate"`, `"already exists"`, or another reassuring string does not prove that state was not mutated again. The evaluator therefore observes effect state around the real subject callback, binds that observation to exact OpenAI call identities and canonical arguments, persists an integrity-bound receipt, revalidates the relation before grading, and lets a deterministic oracle decide whether the duplicate attempt was physically idempotent.

The assurance target is deliberately run-local and two-attempt:

```text
scenario-owned logical operation
        ↓ exact tool + canonical arguments + logical key
OpenAI call #1 ──→ real subject callback executes
        ↓ effect state before / after
OpenAI call #2 ──→ real subject callback executes again
        ↓ effect state before / after
exact request/result/callback/effect relation
        ↓
SideEffectIdempotencyReceipt
        ↓ semantic revalidation
SideEffectIdempotencyOracle
        ↓
0 or 1 observed physical mutations → eligible for PASS
2 observed physical mutations      → critical FAIL
```

The adapter never suppresses, repairs, retries, deduplicates, or rewrites the subject callback. Bad subject behavior remains observable bad behavior.

## Scenario contract

`EvaluationScenario.side_effect_idempotency` optionally carries one frozen `SideEffectIdempotencySpec`:

| Field | Meaning |
|---|---|
| `tool` | exact local `FunctionTool` name under observation |
| `key_argument` | argument whose canonical value identifies the logical operation |
| `expected_arguments` | exact finite JSON object both attempts must use |
| `attempts` | fixed to `2` in v1 |
| `require_first_mutation` | whether attempt one must create an observable effect |

The spec participates in `EvaluationScenario.identity`. Changing the tool, key field, expected arguments, attempt requirement, or first-mutation policy changes scenario identity and invalidates exact historical replay under the old contract.

The logical operation identity is domain-separated and binds:

- tool name;
- key-argument name;
- canonical key digest;
- canonical full-argument digest.

The key is not treated as a magic provider idempotency token. It is evaluator-owned identity material for the exact scenario operation.

## Canonical JSON boundary

Arguments and effect snapshots are reduced to deterministic finite JSON before hashing. The canonicalization layer:

- requires string object keys;
- recursively normalizes objects and lists/tuples;
- accepts JSON primitives;
- rejects NaN and infinities;
- rejects unsupported Python object types;
- sorts object keys and uses compact JSON separators before SHA-256.

OpenAI request arguments are parsed again from strict JSON text with duplicate object members rejected. Both target requests must decode to exactly `expected_arguments`.

This prevents formatting differences from creating false operation identities while preventing ambiguous JSON from being silently accepted.

## OpenAI observer adapter

`OpenAIAgentsSideEffectIdempotencyAdapter` is a separate optional OpenAI adapter boundary. It requires a scenario idempotency contract and an evaluator-owned `effect_reader`.

The adapter resolves the existing local target `FunctionTool`, copies the SDK tool wrapper, and wraps only that copied callback. For every target invocation it:

1. obtains the SDK tool-call identity from the invocation context;
2. parses and canonicalizes the exact callback arguments;
3. samples `effect_reader()` immediately before the subject callback;
4. invokes the **original subject callback**;
5. samples `effect_reader()` again in `finally`;
6. preserves the callback's original return value or exception behavior;
7. records only digest material until the complete relation can be closed.

The effect reader may be synchronous or asynchronous. Its returned value must be finite JSON-compatible material.

Observation failures are evaluator failures, not subject failures. Missing call identity, malformed arguments, effect-reader exceptions, missing digests, callback/request disagreement, missing or duplicate normalized results, reused call identities, or an uncloseable receipt relation become `AdapterPreconditionError` and therefore `EVALUATION_ERROR / BLOCKED` through `TrialRunner`.

## Receipt contract

`SideEffectIdempotencyReceipt` is digest-only evidence. It does not duplicate raw effect state.

It binds:

- schema version;
- scenario identity;
- idempotency-contract identity;
- exact tool;
- logical-operation identity;
- canonical full-argument digest;
- canonical logical-key digest;
- two ordered attempt digests;
- mutation count;
- a domain-separated receipt root.

Each `SideEffectAttemptDigest` binds:

- ordinal `1` or `2`;
- stable OpenAI call ID;
- argument digest;
- key digest;
- before-effect digest;
- after-effect digest;
- derived `mutated` flag.

Receipt validation requires exactly ordinals one then two, distinct call identities, identical bound argument/key digests across attempts, continuous effect chronology (`attempt1.after == attempt2.before`), correct mutation count, and a valid integrity root.

The continuity requirement matters: if the observed state between attempts changed independently, the evaluator cannot attribute the second before/after relation unambiguously and must not claim idempotency assurance.

## Evidence chronology

The receipt is normalized as one non-critical `SIDE_EFFECT_OBSERVATION` event after the second matching tool result:

```text
TOOL_REQUEST(call-1)
TOOL_RESULT(call-1)
TOOL_REQUEST(call-2)
TOOL_RESULT(call-2)
SIDE_EFFECT_OBSERVATION(receipt)
```

`verify_side_effect_observation(...)` revalidates that historical relation before deterministic grading. It requires:

- exactly one observation event when the scenario enables the feature;
- no observation event when the scenario does not enable it;
- recognized evaluator source and non-critical evidence classification;
- valid receipt schema and root;
- exact scenario/contract/tool/logical-operation binding;
- exactly two target requests;
- exact request call IDs, strict arguments, argument digest, and key digest;
- exactly one result per attempt;
- strict serialized chronology ending in the observation event;
- exact reconstruction of the expected receipt from scenario-owned material and persisted attempt digests.

Malformed or ambiguous relation evidence becomes `side_effect_observation_unverified / EVALUATION_ERROR / BLOCKED`. The verifier does not convert evaluator uncertainty into a subject defect.

## Deterministic grading

`TrialRunner` preserves the historical oracle surface for scenarios that do not opt in:

```text
PolicyOracle → OutcomeOracle
```

When `side_effect_idempotency` is configured, the deterministic path becomes:

```text
PolicyOracle → SideEffectIdempotencyOracle → OutcomeOracle
```

The side-effect oracle is critical when it fails. Its v1 rules are:

- if `require_first_mutation=True`, attempt one must produce an observable state change;
- if attempt one mutated and attempt two also mutated, the duplicate operation produced a second physical effect and fails;
- any verified mutation count above one fails;
- otherwise the side-effect oracle passes.

A verified duplicate mutation is a resolved subject defect and remains `FAIL`. It is not downgraded to `BLOCKED` merely because the feature uses an evaluator-owned observer.

## BLOCKED versus FAIL

| Condition | Result class | Reason |
|---|---|---|
| effect reader throws or returns unsupported material | `BLOCKED` | evaluator cannot establish effect state |
| target callback occurs fewer or more than two times | `BLOCKED` | configured relation is missing or ambiguous |
| call ID / normalized request / callback arguments disagree | `BLOCKED` | provenance cannot be closed |
| receipt malformed, root-invalid, foreign, duplicated, or out of order | `BLOCKED` | historical evidence relation is unverified |
| first mutation required but no first effect occurs | critical `FAIL` | resolved subject behavior violates scenario contract |
| both attempts observably mutate state | critical `FAIL` | duplicate logical operation produced a second physical effect |
| one physical mutation across two exact attempts | side-effect oracle `PASS` | verified run-local idempotency condition holds |

This distinction follows the framework-wide rule: **unknown is not bad, and bad is not unknown**.

## Replay semantics

Replay is historical regrading, not a fresh side-effect experiment.

`EvidenceReplayAdapter` re-emits the recorded requests, results, and `SIDE_EFFECT_OBSERVATION`. `TrialRunner` re-runs `verify_side_effect_observation(...)` and the deterministic oracle against the same exact scenario identity. Replay does **not**:

- invoke either subject callback again;
- call `effect_reader()` again;
- prove that the external state still has the same value;
- prove that a provider or dependency is currently available;
- recreate concurrency, timing, or crash conditions.

A successful replay means the recorded relation remains internally valid and deterministically grades the same historical evidence under the current framework logic.

## Deterministic SDK coverage

The pinned OpenAI SDK lane uses `agents.testing.ScriptedModel`; it does not call a provider API.

The integration suite covers at least these behaviors:

- two exact model-selected calls with distinct call IDs against an idempotent subject callback;
- preservation of the real callback's first/duplicate return values;
- two exact physical mutations producing deterministic critical `FAIL`;
- historical replay reproducing the idempotent verdict without touching the callback or effect reader;
- fewer than two observed calls blocking the configured evaluation;
- effect-reader failure blocking rather than being mislabeled as subject failure.

Provider-neutral tests separately exercise receipt integrity, mutation-count/chronology constraints, strict JSON parsing, foreign or malformed observation evidence, request/result binding, oracle fallbacks, and backward compatibility for scenarios that never enable the feature.

## Relationship to approval and retry evidence

This feature is intentionally orthogonal to approval intent and generic retry chronology.

- Approval answers whether one exact invocation was allowed to execute.
- Retry evidence answers whether a later call was causally attempted after an earlier result/error.
- Side-effect idempotency answers whether two exact attempts to the same scenario-owned logical operation produced more than one observable physical effect.

Approval does not prove idempotency. A retry does not prove safety. An idempotency receipt does not prove authorization. When multiple contracts are configured, each boundary retains its own evidence and grading authority.

## Non-claims

The v1 implementation does **not** claim:

- distributed exactly-once execution;
- a production idempotency service, database uniqueness constraint, transaction manager, deduplication cache, or durable idempotency-key registry;
- cross-process, cross-host, multi-worker, queue, webhook, or eventually consistent retry safety;
- crash-recovery, process-restart, network-partition, timeout, cancellation, or partial-commit assurance;
- concurrent/racing duplicate-attempt safety;
- linearizability, serializability, isolation-level correctness, or external transaction atomicity;
- that a provider, API server, payment processor, database, or other external target enforced the logical key;
- that returning `"duplicate"` or similar prose proves no second mutation;
- arbitrary tool counts or retry sequences beyond the exact two-attempt v1 contract;
- arbitrary hosted tools, MCP tools, or remote-function side-effect observation through this adapter;
- live OpenAI model quality or provider availability;
- authenticated observer provenance, signed receipts, trusted timestamps, or remote attestation;
- correctness of `effect_reader()` beyond the evaluator/operator trust placed in that reader;
- continued truth of the observed external state after the run;
- automatic suppression or repair of duplicate subject behavior.

The narrow claim is stronger and more reviewable: **for one exact scenario-owned operation, in one controlled pinned-SDK run, the evaluator can prove from exact call/request/result binding and independently sampled effect digests whether two real callback attempts produced zero, one, or two observable physical mutations.**
