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

A mismatch raises `ReplayIdentityError` at the adapter boundary. When all identities match, replay returns the recorded events, terminal state, output, timing, usage, and cost observations unchanged. Running that adapter through `TrialRunner` therefore re-applies the deterministic policy and outcome oracles to the same evidence envelope.

For an unchanged evidence model, a successful exact-identity replay reproduces the original `evidence_root`.

## Replay is not re-execution

Replay answers:

> Given these recorded observations for this exact trial/subject/scenario identity, what does the current deterministic assurance logic conclude?

Replay does **not** answer:

- can the provider execute successfully now?;
- would the model make the same decision now?;
- does a remote side effect still exist now?;
- is an external dependency currently healthy?;
- did a specific human, service, or machine originally produce these bytes?;
- would nondeterministic behavior reproduce on another attempt?

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
- Do not use replay as a live-provider smoke test.
- Do not interpret a matching SHA-256 as publisher authentication.
- If evidence must survive a compromised host, export it to a separately authenticated or immutable system.

[← Documentation hub](README.md)
