# Evidence Persistence and Replay

## Purpose

`LocalEvidenceStore` turns an in-memory `TrialEvidence` object into a locally persisted record that is reverified before use. `EvidenceReplayAdapter` can then feed that exact historical evidence back through the deterministic assurance engine.

These capabilities solve two different problems:

- **persistence** preserves an evaluation observation with explicit integrity checks;
- **replay** regrades that historical observation under deterministic framework logic.

Neither capability establishes who originally wrote the bytes, proves that a provider is currently available, or re-executes a side effect.

## Three identities, three jobs

The store deliberately does not overload one hash with several meanings.

| Value | Derived from | What it establishes |
|---|---|---|
| `record_key` | canonical `trial_id`, `subject_identity`, `scenario_identity` | path-safe lookup identity for one evaluation attempt |
| `payload_sha256` | exact canonical serialized `TrialEvidence` bytes | byte-level payload integrity |
| `evidence_root` | domain-separated trial/subject/scenario identity, ordered event digests, and terminal observations | semantic evidence-envelope integrity |

The manifest binds all three. A valid payload hash with the wrong subject/scenario/trial identity is rejected. A valid record key with changed payload bytes is rejected. A structurally valid payload whose recomputed evidence root differs from the manifest is rejected.

`evidence_root` is still **not a digital signature**. Hashes detect change relative to a trusted reference; they do not authenticate the writer that created both the payload and the reference.

## Record layout

A record key is a lowercase 64-character SHA-256 digest. Operator-controlled `trial_id` text never becomes a filesystem path component.

```text
<store-root>/
└── records/
    └── ab/
        ├── ab...64hex.evidence.json
        ├── ab...64hex.manifest.json
        └── ab...64hex.lock        # exists only while a writer owns the record
```

The two-character fan-out keeps large stores from placing every artifact in one directory. Readers address records by the full `record_key`, not by scanning filenames.

## Write protocol

A normal write follows this sequence:

1. serialize `TrialEvidence` to canonical JSON;
2. enforce the configured payload byte ceiling;
3. derive the record key from the trial, subject, and scenario identity;
4. acquire an exclusive same-record lock using create-if-absent semantics;
5. reject an incomplete existing record instead of repairing it automatically;
6. allow an already-complete record only when it is exactly the same immutable evidence;
7. build and size-check the manifest;
8. stage the payload in a temporary file in the destination directory;
9. write all bytes and `fsync` the staged file;
10. publish the final filename with a hard-link operation that **fails if the destination already exists**;
11. `fsync` the containing directory where the platform exposes directory descriptors;
12. remove the staging link and sync the directory again;
13. repeat the same publication protocol for the manifest;
14. release the record lock.

The payload is published **before** the manifest. The manifest is the commit marker.

### Why no-clobber publication matters

A cooperative writer already honors the per-record lock. The final publication step nevertheless refuses to overwrite a destination that appears between staging and publication. This closes the classic check-then-replace race in which a competing local writer could otherwise be silently overwritten.

The test suite injects that race deliberately and verifies that the competing bytes survive while the store raises `EvidenceConflictError`.

## Crash and interruption semantics

The store is designed to fail closed rather than guess whether interrupted evidence is usable.

| Observable state | Interpretation |
|---|---|
| no payload, no manifest | no committed record |
| payload only | incomplete record; rejected |
| manifest only | incomplete record; rejected |
| payload + manifest | candidate committed record; every integrity check must still pass |
| stale `.lock` | writer state is ambiguous; new writes fail with `EvidenceStoreBusyError` |
| orphan temporary file | not addressable as a record and never substitutes for payload/manifest |

A stale lock or partial record requires explicit operator review. The store does not silently delete, repair, or overwrite ambiguous evidence.

## Read verification

`LocalEvidenceStore.read()` does not trust a filename just because it exists. It verifies the record in layers:

1. the requested key is exactly 64 lowercase hexadecimal characters;
2. the record bucket is not a symlink;
3. both payload and manifest exist;
4. payload and manifest are not symlinks;
5. `O_NOFOLLOW` is requested where the platform supports it;
6. opened artifacts are regular files;
7. file sizes remain within configured resource ceilings;
8. bounded reads detect a file that changes size during the read;
9. the manifest passes its strict schema with no extra fields;
10. the manifest's trial/subject/scenario identity derives the requested record key;
11. manifest payload length matches the bytes read;
12. manifest payload SHA-256 matches the bytes read;
13. the payload validates as strict `TrialEvidence`;
14. payload trial/subject/scenario identity matches the manifest;
15. the recomputed `evidence_root` matches the manifest.

Any failed layer prevents the bytes from becoming trusted evaluation evidence.

## Exact-identity replay

`EvidenceReplayAdapter` accepts recorded evidence only when all three execution identities match:

- requested `trial_id` equals the recorded trial ID;
- requested `SubjectFingerprint.identity` equals the recorded subject identity;
- requested `EvaluationScenario.identity` equals the recorded scenario identity.

A mismatch raises `ReplayIdentityError` at the adapter boundary. When all identities match, replay returns the recorded events, terminal state, output, timing, usage, and cost observations unchanged. Running that adapter through `TrialRunner` therefore re-applies evaluator-owned retrieval-delivery verification, approval-intent verification, side-effect-observation verification, protocol/semantic receipt checks where configured, plus the active deterministic oracle set to the same evidence envelope.

For an unchanged evidence model, a successful exact-identity replay reproduces the original `evidence_root`.

## Semantic judgments are historically revalidated

A persisted terminal `SEMANTIC_JUDGMENT` event is not trusted merely because its enclosing evidence envelope hashes correctly. Replay reconstructs the exact `TrialEvidence` that existed before that event, rederives its evidence root, and requires the embedded `SemanticJudgmentReceipt.subject_evidence_root` to match it. The receipt then revalidates exact scenario/subject identity, embedded rubric identity, judge profile, accepted calibration identity, bounded input digest, structured-response digest, criterion threshold semantics, derived decision, and outer receipt root.

The semantic event must be unique, terminal, emitted from the known evaluator source, and non-critical. If deterministic policy/outcome replay fails, historical semantic evidence cannot coexist with or rescue that failure. If deterministic replay passes, historical semantic PASS/FAIL/ABSTAIN is rederived as PASS/non-critical FAIL/INCONCLUSIVE respectively.

Replay does **not** call a semantic model when a valid historical semantic receipt is present. It proves only that the recorded semantic relation remains internally valid for the exact recorded evidence and scenario identity; it does not establish current provider liveness or that the judge would return the same response today. See [Calibrated Semantic Judging](SEMANTIC_JUDGING.md).

## Side-effect observations are semantically revalidated

A persisted `SIDE_EFFECT_OBSERVATION` is not trusted merely because the enclosing evidence root is valid. When the exact scenario carries `SideEffectIdempotencySpec`, `TrialRunner` requires exactly one recognized non-critical observation event after exactly two matching target request/result pairs.

The verifier rechecks receipt schema/root, scenario and contract identity, exact tool and logical operation, distinct call IDs, strict duplicate-key-rejecting canonical arguments, logical-key digests, one result per attempt, continuous before/after effect chronology, and strict `request1 < result1 < request2 < result2 < observation` ordering. It then reconstructs the expected receipt from scenario-owned material and the persisted attempt digests. Malformed, missing, duplicated, foreign, or ambiguous relations become `side_effect_observation_unverified / EVALUATION_ERROR / BLOCKED`.

Replay does **not** execute the subject callback or call the evaluator's effect reader. It proves only that the historical two-attempt observation remains internally valid for the exact recorded scenario and evidence. A verified duplicate physical mutation remains deterministic critical subject `FAIL` through `SideEffectIdempotencyOracle`. See [Side-Effect Idempotency Assurance](SIDE_EFFECT_IDEMPOTENCY.md).

## Native approval-intent receipts are semantically revalidated

A persisted `APPROVAL_DECISION` event is not trusted merely because the surrounding `TrialEvidence` has a valid payload hash/evidence root or because `ApprovalIntentReceipt` passes structural validation.

When the exact scenario declares `ApprovalIntentSpec`, `TrialRunner` revalidates the historical request → decision → continuation relation before deterministic grading. The verifier requires:

- exactly one decision event when a bound decision exists;
- receipt scenario identity equal to the current exact scenario;
- receipt decision/agent/tool equal to the scenario intent;
- a referenced prior `APPROVAL_REQUEST` at the exact bound evidence sequence;
- exact agent, tool, call ID, canonical finite-JSON argument digest, and normalized resource identity;
- accepted authority epoch derived from semantically valid prior handoffs rather than a raw handoff count;
- exact accepted handoff-path hash, preventing same-depth sibling-path replay;
- on `APPROVE`, exactly one matching resumed executable request and exactly one matching non-rejection result;
- on clean `REJECT`, exactly one matching continuation result explicitly marked as rejection and no protected executable request.

If an exact rejected invocation does reach executable `TOOL_REQUEST` evidence, the verifier preserves that resolved chronology so `PolicyOracle` can grade execution-after-rejection as critical subject `FAIL`. It is not hidden behind evaluator uncertainty.

Malformed/root-invalid receipts, decision/request ordering errors, changed arguments/resource, authority epoch/path mismatch, duplicate/missing continuation, or ambiguous result identity become `approval_intent_unverified / EVALUATION_ERROR / BLOCKED`.

Replay does **not** recreate a human review, authenticated approver, or SDK interruption. It rechecks whether the historical normalized evidence still proves the exact evaluator-owned approval relation. See [Native HITL Approval Intent](APPROVAL_INTENT.md).

## Retrieval-delivery receipts are semantically revalidated

A persisted `RETRIEVAL_DELIVERY` event is not trusted merely because the surrounding evidence envelope hashes correctly. When a scenario carries `RetrievalContractSpec`, `TrialRunner` requires exactly one retrieval delivery and rederives it from the scenario-owned base corpus, exact query, ranker profile, optional poison relation, target call identity, and persisted model-visible result.

The verifier requires one exact target `TOOL_REQUEST`, strict duplicate-key-rejecting JSON arguments containing only the bound query, one matching `TOOL_RESULT`, and strict `TOOL_REQUEST < RETRIEVAL_DELIVERY < TOOL_RESULT` chronology. It reconstructs the expected baseline/active ranking and `RetrievalDeliveryReceipt`; mismatch, ambiguity, malformed receipt/root, foreign source, changed scenario identity, or an unreconstructable model-visible result becomes `retrieval_delivery_unverified / EVALUATION_ERROR / BLOCKED`.

Replay does not rerun retrieval. Because retrieval behavior-bearing material participates in `EvaluationScenario.identity`, changing corpus/query/ranker/poison configuration invalidates exact-identity replay before old evidence can be treated as current. See [Retrieval Provenance and Poisoning Assurance](RETRIEVAL_ASSURANCE.md).

## Protocol-delivery receipts are semantically revalidated

Byte-level and evidence-root integrity are necessary but not sufficient for a persisted cross-domain MCP claim. A recorded `PROTOCOL_DELIVERY` event is not trusted as opaque JSON merely because the enclosing `TrialEvidence` is structurally valid.

Before subject grading, the evaluator dispatches each known protocol-delivery source to its exact typed receipt contract and revalidates its semantic root and relation:

| Source | Revalidated receipt | Relation rechecked |
|---|---|---|
| `bridge:mcp-agent:tool-metadata` | `MCPAgentToolMetadataReceipt` | exact discovery-description/model-visible-definition binding, target schema-digest equality, and pre-behavior delivery chronology |
| `bridge:mcp-agent:tool-result` | `MCPAgentToolResultReceipt` | exact result-bridge identity and model-visible output binding |
| `bridge:mcp-agent:tool-error-recovery` | `MCPAgentToolErrorRecoveryReceipt` | exact error/retry identities, causal chronology, argument and recovery bindings |
| `bridge:mcp-agent:tool-schema-drift` | `MCPAgentToolSchemaDriftReceipt` | exact schema/argument/observation digests, strict protocol chronology, and host-refreshed adaptation binding |
| `bridge:mcp-agent:tool-identity-drift` | `MCPAgentToolIdentityDriftReceipt` | exact original→replacement identity binding, model-visible identity-set digests, strict call/result and protocol chronology, argument/rejection/recovery bindings |

The metadata replay verifier does not recreate MCP discovery or a model request. It rechecks the typed receipt's exact `TOOL_METADATA_POISON` kind, protocol revision and `tools/list:<tool>:description` observation point, description digest relation, tool identity, schema-digest relation, scenario identity, semantic root, and chronology. Leading pre-model `ATTACK_DELIVERY` is permitted, but metadata `PROTOCOL_DELIVERY` appearing after normalized model/agent behavior fails closed.

The schema-drift replay verifier does not recreate a refresh. It checks that the historical receipt still proves the exact recorded relation: bound v1/cached/v2 schema digests, stale/recovery argument digests, matching protocol/model-visible observations, distinct call identities, strict `initial-list < swap < stale-call < cache-invalidation < refreshed-list < recovery-call` chronology, and a valid domain-separated root.

The identity-drift replay verifier likewise does not reconnect to MCP or recreate a rename/cache refresh. It revalidates the nested `TOOL_IDENTITY_DRIFT` protocol receipt, exact original and replacement identities, initial/refreshed model-visible controlled identity sets, distinct stale/recovery call IDs, strict finite canonical argument digests, protocol/model rejection and recovery digests, the same six-leg protocol chronology, scenario identity, and domain-separated bridge root. A historical receipt therefore proves only that the persisted run contained that exact host-refreshed identity-adaptation relation; it does not assert current MCP registry or model behavior. See [MCP Tool-Identity Drift Assurance](MCP_IDENTITY_DRIFT.md).

Unknown `PROTOCOL_DELIVERY` sources fail closed until an explicit verifier exists. Malformed typed receipts, invalid roots, impossible chronology, or receipt scenario identity that differs from the enclosing `TrialEvidence.scenario_identity` block evaluation instead of being treated as trusted historical evidence.

This distinction matters because persistence can preserve a claim without making that claim semantically true. Replay therefore rechecks the envelope plus every evaluator-owned receipt relation required by the scenario before deterministic subject grading.

## Replay is not re-execution

Replay answers:

> Given these recorded observations for this exact trial/subject/scenario identity, what does the current deterministic assurance logic conclude?

Replay does **not** answer:

- can the provider execute successfully now?;
- would the subject model make the same decision now?;
- would a semantic judge produce the same judgment now?;
- does a remote side effect still exist now?;
- is an external dependency currently healthy?;
- did a specific human, service, or machine originally produce these bytes?;
- would nondeterministic behavior reproduce on another attempt?;
- would a native approval interruption or human review happen the same way now?;
- would the same two callbacks or effect-reader snapshots produce the same side-effect relation now?;
- would an evaluator-owned or external retrieval system produce the same ranking/context now?;
- would an MCP server still expose the same result, error, schema, tool identity, cache state, or authorization behavior now?;
- would a host perform the same schema- or identity-drift cache invalidation now?

Those questions require fresh execution, fresh environment observation, or authenticated provenance—not replay.

## Exception confidentiality

Adapter/runtime failures are converted to `BLOCKED` evidence without retaining `str(exception)` and without hashing the exception text. Runtime-error evidence keeps only the exception type and `detail_retained: false`.

This matters once evidence is durable: provider exceptions can contain request bodies, URLs, identifiers, credentials, or low-entropy secrets. Even hashing raw secret-bearing messages can create an offline guessing surface.

## Example

```python
import asyncio
from pathlib import Path

from agent_evals.adapters.replay import EvidenceReplayAdapter
from agent_evals.evidence.store import LocalEvidenceStore
from agent_evals.runtime.evaluator import TrialRunner

# `evaluated`, `subject`, and `scenario` come from a completed TrialRunner execution.
store = LocalEvidenceStore(Path("artifacts/evidence"))
manifest = store.write(evaluated.evidence)

replay = EvidenceReplayAdapter.from_store(store, manifest.record_key)
regraded = asyncio.run(
    TrialRunner().run(
        replay,
        subject=subject,
        scenario=scenario,
        trial_id=evaluated.evidence.trial_id,
    )
)

assert regraded.evidence.evidence_root == evaluated.evidence.evidence_root
```

The example deliberately uses the original trial ID. Rewrapping old observations under a new trial identity would destroy the provenance property the evidence root is designed to preserve.

## Threat model and non-claims

The local store protects against accidental corruption and several classes of local path/race misuse. It is not a hostile-host attestation system.

It currently does **not** provide:

- digital signatures or MACs;
- authenticated writer identity;
- authenticated approver identity;
- trusted timestamps;
- remote attestation;
- WORM/object-lock enforcement;
- encryption at rest;
- key management;
- cross-host replication or distributed durability;
- retention/deletion policy enforcement;
- a tamper-evident transparency log anchored outside the store root.

An actor with arbitrary write access to the store root can replace a payload and manifest coherently. Because that actor can recompute ordinary hashes, local hash verification alone cannot distinguish that rewrite from an authorized publisher. Environments that require adversarial writer resistance need an external trust anchor such as signatures, keyed authentication, immutable object storage, or remote attestation.

The hard-link publication primitive also depends on filesystem support for hard links. A filesystem that cannot provide the no-clobber primitive causes publication to fail rather than silently fall back to overwrite semantics.

## Operational guidance

- Put the evidence root on a filesystem whose ownership and access controls match the evaluation control-plane trust boundary.
- Treat partial records and stale locks as incidents to review, not clutter to auto-delete.
- Preserve manifests with their payloads; neither is a substitute for the other.
- Do not use replay as a live-provider, live-HITL, or live-MCP smoke test.
- Do not interpret a matching SHA-256 as publisher or approver authentication.
- If evidence must survive a compromised host, export it to a separately authenticated or immutable system.

[← Documentation hub](README.md)
