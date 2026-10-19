# ADR 0052: Main-owned upstream qualification for signed Dependabot action upgrades

**Status:** Accepted
**Date:** 2026-10-19
**Supersedes:** None

## Context

Signed Dependabot PR #397 updates six GitHub Action releases. The existing exact-SHA literal
checks cause deterministic failures, and the trusted CodeQL publisher declines the changed
CodeQL workflow despite the only differences being immutable action pins. PR #398 and ADR
0051 fixed app-issuer confusion and SHA-only action lines but did not establish upstream pin
provenance or preserve the producer trust boundary during such updates.

## Decision

The accepted-main-owned PR publisher, never candidate code, validates the canonical
Dependabot identity, signed commit, GitHub web-flow committer and full set of modified
workflow files. An accepted-main semantic validator rejects non-action edits, renames,
unrelated action identities, unchanged SHA, inconsistent annotations or non-monotonic
annotated versions. For every updated action, main-owned logic reads the canonical
upstream GitHub tag (dereferencing annotated tags), binds its target to the immutable
workflow SHA and requires a GitHub-verified valid signature on the target commit.
A signed Dependabot dependency-version claim must agree with any workflow comment.

The unprivileged PR CodeQL workflow retains the existing zero-alert veto. Main may
publish its canonical SARIF only after independently verifying the complete pinned-action
delta, exact head/base/merge tree, scan job/artifact identity and pre-upload revalidation.
Any changed executable CodeQL verification script remains blocked except for one
*separately reviewed exact-source-blob* migration of the scanner's static pin-literal
contracts. No candidate can supply or alter this exception blob.

The runtime and graph validator continue to insist on exact canonical action names,
immutable 40-hex SHA refs, all accepted workflow job/permission/trigger/input
contracts; future releases no longer require revising stale hardcoded hashes.
No privilege is added to the PR scanning job.

## Consequences

Dependabot may make authenticated, patch-only vendor pin upgrades without requiring
a code-owned validator change for each published upstream release. The new upstream
query is a stricter availability prerequisite: inaccessible vendor refs, tag drift or
unsigned target commits BLOCK rather than silently passing. GitHub tag/signature
verification establishes an issuer-observed release mapping at verification time,
not intrinsic safety of upstream code or immunity to a future compromised maintainer.

The trusted main publisher also accepts a **completion event** from the single
canonical read-only CodeQL workflow as a wake-up, alongside its existing
main-owned push/schedule/owner dispatch triggers. The wake-up never consumes
untrusted PR event fields to identify a publish target, never checks out
candidate code, and always re-reads exact trusted run/head/base/tree/artifact
proof before any security-events write. Discovery terminates once every live
head has been evaluated instead of failing spuriously against a repository
with more than 300 historical CodeQL runs. Missing or failed newest scans
remain explicitly BLOCKED.

The reviewed scanner policy migration is staged separately; its exact Git blob SHA
is preapproved by this accepted-main decision before the candidate can run.
The acceptance path must still pass real CI, native PR-head CodeQL, branch rules
and the trusted owner-governed merge sequence.

## Assurance impact

Publisher and owner-governance authority stay in accepted main. PR code can run
only with read permissions. The signed source, upstream release ref/commit,
independent zero-alert evidence, artifact digest, strict exact-subject checkout and
immutable merge protections are separate, non-compensatory prerequisites.
Adversarial tests reject upstream tag mismatch and failed issuer verification.

## Non-claims

- An upstream tag or Git commit SHA by itself is not an authentication of code safety.
- A GitHub verified upstream commit is not proof that the vendor was uncompromised.
- The trusted publisher is not permission to run candidate code with elevated tokens.
- Admin-hidden settings are BLOCKED, not PASS. No merge bypass, suppressions, or
  independent human review is invented.
- Only a complete live successful signed-bot lifecycle proves autonomy end-to-end.

## Evidence

Base accepted main `8bf6aca9f206db6528f15b2a83ad45dec7714724`.
Prior merged #396 and #398 are accepted. Open #397 is the unique active bot lane,
and no other repair branches survive; #389 is deliberately superseded by #390.
Issue #399 tracks full live validation and remaining requirements.
