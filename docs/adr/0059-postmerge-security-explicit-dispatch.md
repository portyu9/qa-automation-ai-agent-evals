# ADR 0059: Trigger independent Security before post-merge CI for governed bot merges

**Status:** Accepted
**Date:** 2026-10-19

## Observed production evidence

The signed Dependabot group PR #397 merged under the actual main-owned
governor with the configured owner's exact-head review, authentic native
CodeQL, Package integrity and all thirteen protected checks. Original
signed head: `91b05c2203d6c35a20037dd7771c699bd7a4e132`.
Protected merge: `fff647c09f4d848559725736b13268190c3e832f`.
The GitHub Actions bot was the merge actor. Post-merge explicitly
dispatched CodeQL run `39297069938` passed; explicitly dispatched
CI run `39297057145` failed its **correct** independent Security
provenance requirement (Package integrity job `118213206638`,
`all exact-subject Security successes did not register`).

The GitHub Actions `GITHUB_TOKEN` used for the merge does not generate
ordinary push workflow events. Although trusted Security workflow
`.github/workflows/security.yml` is configured for `push` **and**
`workflow_dispatch`, the governor registered only CI and CodeQL.
The prior config and self-test therefore missed a real post-merge
Security evidence dependency. Removing or softening the CI verifier
is explicitly forbidden.

## Decision

The trusted-main governor must register, in this **mandatory order**,
all three exact merged-main subjects:

1. Security via existing `workflow_dispatch`, with its two real mandatory
   scanner jobs and `security-gate` still independently verified by CI
   Package integrity for the **same merge commit, event and run attempt**.
2. CodeQL via existing `workflow_dispatch`, retaining authentic zero-alert
   SARIF, native Code Scanning and the main-only upload boundary.
3. CI via `workflow_dispatch` and existing `subject_sha` input, so CI
   sees its already-dispatched Security and CodeQL evidence.

The governor continues to check current main SHA before each dispatch;
requires exact workflow name/path/main/subject/event, unique run,
valid attempt and status, and terminal-success veto. A failed or absent
Security run blocks post-merge qualification. The merged result includes
Security run ID/attempt/event/status as well as CI and CodeQL receipts.
The main-only governor need not execute PR code or elevate the Security
job permissions.

Append fail-closed fixtures rejecting missing/reordered/misnamed
Security, missing CI subject input, wrong SHA/ref/path/event, terminal
Security failure, ambiguous duplicate runs, and wrong dispatch order.
Issue #408 tracks the production defect.

## Consequences and assurance bounds

The fix removes an event-trigger gap, **not** a security requirement.
The exact #397 post-merge CI failure remains historical evidence; no
retroactive success is claimed. Only newly executed authentic
independent Security/CodeQL/CI workflows on exact future merged
subjects can qualify. Scheduled workflow queuing or unsuccessful
scans still block rather than being flattened into success.

A Git SHA is an equality handle, not origin authentication; owner
token identity, signed canonical Dependabot provenance, release
attestation and GitHub-protected checks remain separate. Independent
human review and unrelated external-fork proof are not inferred.

## Branch and lineage preflight

Accepted main at the preflight was
`fff647c09f4d848559725736b13268190c3e832f`,
with **no open PRs**, **only main branch**. Previous bot PR #397
and repair PRs #400–#407 are all merged and their branches deleted.
Historical PR #389 was explicitly reverted by protected PR #390, not
salvageable production functionality. No currently divergent commit,
orphan branch or unmerged unique source required salvage. This change
is a narrowly scoped control-plane enhancement separate from prior
accepted scanner, issuer, owner and evidence protections.

## Non-claims

Passing code/test fixtures is not an end-to-end proof of the next bot
release, future GitHub availability or absence of all vulnerabilities.
No branch-protection bypass, forged native checks or suppression of
unsuccessful security evidence is authorized.
