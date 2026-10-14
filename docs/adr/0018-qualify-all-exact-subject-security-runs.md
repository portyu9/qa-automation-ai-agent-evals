# ADR 0018: Qualify every exact-subject CodeQL and Security run

**Status:** Accepted
**Date:** 2026-10-14
**Supersedes:** Only the singleton-run/ambiguous-distinct-IDs assumption in the CodeQL and Security proof aggregation of ADR 0017; retains ADRs 0013–0017 and their other authority, evidence and permission invariants.

## Context

PR #354 added independent `Security` job verification to the
ruleset-required `Package integrity` gate while preserving the earlier
exact-subject CodeQL bridge. On accepted `main` SHA
`ab6c1a6d2deff5a34320101578b4473a698a60eb`, GitHub initiated two
sets of legitimate `push` workflow runs for the *same* immutable commit.
The first CI run was cancelled by concurrency. The second
`Package integrity` job (CI run `38591463722`, job `115948202981`)
rejected the two authentic CodeQL runs (IDs `38591073644` and
`38591463973`) with the message
`ambiguous exact-subject CodeQL evidence`, despite both being completed
successfully. The singularity invariant had inadvertently become an
availability bug, even though independent scans were present.

This is not a reason to accept the latest positive result if a previous
matching run failed, to ignore cancellation, or to change scanner results.

The mandatory pre-branch lineage and salvage preflight was performed
against accepted `main` `ab6c1a6d2deff5a34320101578b4473a698a60eb`.
There were zero open PRs. The only extant branch was `main`.
All relevant prior capabilities (#284, #338, #337, #350, #351, #354)
were already accepted; no divergent historical branch contained unique
unmerged changes. The accepted verifier blob was
`8cd8ff87b16a428d44999154cbb7b55163ea9082`; accepted ADR 0017
blob was `b9b69d6602159aa5003c23ae747e8c1a67ae954d`.
The preflight then created a **single** repair branch,
`fix/codeql-security-same-sha-success-20261014`, from the exact
accepted commit. No parallel implementation branch was created.

## Decision

A single authenticated Actions API response may describe several distinct
runs with the same permitted event, exact subject SHA, head branch,
workflow name and workflow path. Such distinct runs are not automatically
ambiguous. The verifier shall collect all matching runs and require:

1. Positive canonical run ID and attempt, distinct run IDs, and approved
   workflow identity, branch and event classes.
2. Each matching run must finish `completed` with `conclusion=success`.
   A failed, skipped, cancelled, or malformed receipt rejects the entire
   qualification. Active/queued/pending receipts must finish inside the
   existing bounded polling window; they cannot be compensated by a green
   peer run.
3. The full query must be nontruncated. The Actions API `total_count`
   must equal the number of returned rows; otherwise fail closed, even
   if this prevents qualifying a commit with over 100 workflow runs.
   The bounded one-page query must not silently disregard unseen evidence.
4. Sort the successful receipt set by canonical run ID, for deterministic
   logging and comparison; never arbitrarily choose a most recent green
   run while ignoring any other.
5. For the dedicated `Security` producer, read the selected attempt's
   jobs **for each and every successful matching run**, verify the same
   run ID and attempt, and require independently successful `Security
   scanners` and `security-gate` jobs with no missing or duplicated
   required job identity.

The ruleset-required `Package integrity` name, readonly Actions token,
CodeQL/Security independent scanners, `ci-gate`, release provenance,
and existing authoritative fail-closed preconditions remain unchanged.
Add negative tests for mixed success/failure, cancellation, duplicate IDs,
partial run sets, missing/malformed metadata, bounded pending states,
cross-subject mismatch, and failure in a second Security run.

## Consequences

Multiple *wholly successful* genuine scans of the exact accepted subject
may qualify without needlessly deadlocking the protected CI gate. A
mixed result still blocks; a duplicated ID or truncated API response
blocks; one positive Security workflow does not excuse an unqualified
second workflow. The verifier conservatively rejects oversized response
sets rather than attempting to infer missing records. A future pagination
enhancement must bind every page before broadening this claim.

## Assurance impact

The accepted evidence authority is unchanged: GitHub-hosted workflows
and their exact authenticated subjects are inputs to a separate protected
check. A hash does not authenticate a purported scan, a passed workflow
does not certify every vulnerability absent, and `BLOCKED` remains
uncertainty rather than PASS or FAIL. This is a bounded correction of
the run-cardinality contract, not an authorization expansion.

## Non-claims

This does not make OpenSSF Scorecard a required pre-merge check, resolve
the remaining posture alerts, confer human code review, permit a
cancelled/failed matching scanner run to be ignored, or waive a missing
security prerequisite. Live exact-head and accepted-main executions are
required separately to substantiate this repair.
