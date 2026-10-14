# ADR 0012: Authenticated publisher no-op for an already qualified lock child

**Status:** Accepted
**Date:** 2026-10-13
**Supersedes:** None

## Context

ADRs 0008, 0009, and 0011 authorize a GitHub-signed Dependabot manifest update followed by one exact signed trusted publisher child containing all twelve hash-locked interpreter/compatibility artifacts. The independent read-only `dependency-locks` matrix executes not just on the original signed source commit, but again on the resulting publisher child when the branch advances. Its successful child-head run triggers `dependency-lock-publisher` again. The original publisher only accepted a one-file `pyproject.toml` source; it therefore reported a failed privileged workflow even though the candidate child had already been fully authenticated and qualified. The failure is deterministic, not an evidence of a security or compatibility defect, and contaminates the reliability of autonomous CI recovery.

## Decision

Retain strict control-plane workflow-run provenance, exact bound PR/branch/head SHA, accepted-main authority, and the existing signed-change governor **before** classifying the subject. When and only when the governor `assess(..., require_checks=False)` independently accepts the complete canonical two-commit chain—including the original signed Dependabot manifest source parented directly to accepted main, trusted GitHub-signed publisher child, message/identity, immutable manifest, exact twelve canonical generated locks, SHA-256 hash profiles, compatibility validators and prospective merge ref—the publisher treats the second successful read-only compiler wake as an idempotent **already-published no-op**.

The original one-file signed bot source remains the sole `publish` disposition. A partial inventory, duplicate path, mixed action change, unauthorized path, absent provenance, stale head, mismatched branch, wrong interpreter lock, or unsupported ecosystem must fail closed. A verified no-op produces a distinct receipt and returns success **without reading untrusted artifact payloads again, minting or consuming owner write authority, generating another child, or updating a ref**.

## Consequences

The read-only compiler can run on both the original bot source and exact publisher child without producing a spurious red privileged workflow. This does not suppress any actual failed lock, provenance, workflow or security check. A newly updated bot source still undergoes full compilation and exact published child qualification. Previously failed historical runs remain in the immutable audit history; successful future child-head runs produce true authenticated no-op evidence.

## Assurance impact

The classification happens only after the independently reviewed governor `assess` returns an authenticated subject. It neither trusts the workflow event's claims nor infers success from a file count alone; regression tests cover missing, duplicate, extra, mixed, and forged inventories after the guarded entrypoint. The same strict child provenance verifier from ADR 0011 remains in force, along with owner-authenticated fast-forward publishing for new bot source commits and all required CI, CodeQL, security and post-merge gates.

## Non-claims

An already-published receipt does not itself constitute a passed CI, CodeQL, security, trusted merge gate, or human approval. It does not authorize unsigned commits, stale base/head relationships, arbitrary updates to locked files, synthetic artifacts, replays with mismatched branch identity, a third commit, or a second privileged publication.
