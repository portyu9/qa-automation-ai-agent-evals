# Evidence Backup, Replication, and Observed WORM Behavior

## Purpose

The content-addressed evidence store already separates logical evidence identity from storage
representation and requires immutable put-if-absent semantics. This layer adds a versioned backup
snapshot plus verified multi-target replication without letting a storage backend declare itself
trusted.

The governing rule is:

```text
backend configuration or capability claim
    != observed storage behavior
```

A successful replication receipt means the framework copied the exact snapshot envelopes to every
named target and read the exact bytes back through the configured backend API. It does not
authenticate the target provider or establish a durability service-level agreement.

## Backup snapshot

`create_backup_snapshot()` enumerates the source content-addressed store and binds each object to:

- its logical SHA-256 key over canonical uncompressed `TrialEvidence`;
- the independently revalidated `evidence_root`;
- the SHA-256 digest of the exact stored envelope bytes;
- the exact stored-envelope length.

Every exact envelope is revalidated through the existing `ContentAddressedEvidenceStore` decoder
before it enters the snapshot. Objects are sorted by logical key and committed by the
domain-separated `agent-evals/evidence-backup-snapshot/v1` root.

This preserves the existing distinction between logical evidence identity and storage
representation. Gzip versus uncompressed storage does not change the logical key, while the backup
snapshot still binds the exact representation that will be replicated.

## Backend conformance probe

Before source evidence is copied, each target receives an expendable **valid synthetic
`TrialEvidence` blob**. The probe then observes three behaviors:

1. read-after-write returns the exact valid sentinel;
2. a second conflicting `put_if_absent` for the same key is refused and does not change bytes;
3. deletion behavior is attempted and observed.

The synthetic evidence carries only a digest of the caller-provided challenge, not the raw
challenge. Target labels are operator-supplied routing labels; they are not authenticated storage
identities.

### Narrow WORM observation

A target receives `worm_observed=true` only when all of the following happen in one probe:

- the sentinel was written and read back exactly;
- no-clobber behavior was observed;
- `delete(sentinel_key)` explicitly returned `False`;
- the same exact sentinel remained readable and independently valid after the failed deletion.

A backend exception, timeout, metadata field, class attribute, configuration flag, marketing claim,
or provider capability response does **not** earn WORM credit.

A deletion-resistant probe sentinel necessarily remains in that target's immutable namespace. It is
itself valid synthetic evidence so it does not poison the content-addressed object format.

This is deliberately a narrow claim: it establishes only **observed deletion resistance through the
configured backend API for that sentinel at that time**.

It does not prove:

- cloud-provider retention configuration or enforcement outside that API path;
- legal hold, governance lock, retention duration, or administrative separation of duties;
- physical-media immutability;
- authenticated tenancy or target ownership;
- backup availability, geographic independence, or a durability SLA;
- resistance to privileged provider operators, account takeover, alternate deletion APIs, or
  out-of-band destruction.

## Replication protocol

`replicate_backup()` performs the following sequence:

1. validate target labels and the minimum target threshold;
2. create and verify the exact source backup snapshot;
3. run the backend conformance probe for **every** configured target;
4. if WORM is required, fail before copying source evidence unless every target produced the narrow
   deletion-resistance observation above;
5. re-read each source envelope and require it to match the frozen snapshot digest/length/root;
6. copy with `put_if_absent`;
7. read the target object back and require exact byte equality;
8. revalidate the target envelope and `TrialEvidence.evidence_root`;
9. create a target receipt only after every snapshot object verifies;
10. create the overall replication receipt only after every named target verifies.

An already-present target object is accepted only when its exact envelope bytes equal the frozen
source envelope. Different bytes under the same logical key are a hard conflict, not an overwrite or
repair opportunity.

Repeated replication is therefore idempotent. A failed operation may leave already copied immutable
objects on earlier targets; no overall replication receipt is minted until all configured targets
verify. Retrying safely converges because existing exact objects are accepted and conflicting bytes
remain fail-closed.

## Threshold semantics

`minimum_verified_targets` is an explicit minimum count over the configured named targets. The
function refuses configurations below that threshold before running a probe or copying evidence.

The current contract does not silently tolerate failed configured targets: **every named target
must verify before an overall receipt is created**. The threshold is therefore a minimum
configuration requirement, not an N-of-M mechanism that hides a failed replica.

## Receipt and trust boundaries

Backup, probe, target, and overall replication records have separate domain-separated roots.
Revalidation rejects root tampering, cross-snapshot target receipts, unsorted/duplicate target
identity, a target count below policy, or WORM-required receipts that lack observed resistance.

Those roots are integrity commitments only. They are not signatures, MACs, trusted timestamps,
provider attestations, authenticated writer identities, or proof that a remote provider enforced
the same behavior through every interface.

The existing reference-safe retention/garbage-collection contract remains separate. A
deletion-resistant target may intentionally refuse garbage collection; replication does not weaken
or reinterpret reference safety to make deletion succeed.
