# ADR 0024: Preserve BLOCKED for unobservable ruleset bypass authority

**Status:** Accepted — supersedes the limited assumption in ADR 0022/0023
that read-only GitHub Actions tokens can always observe `bypass_actors`.
Earlier ADRs remain byte-for-byte immutable.

## Context

The accepted `main@6aec0e3a4e97e380b0a724fde790a4888f7fc9ac`
successfully completed all five existing CI, CodeQL, independent Security,
Scorecard and platform smoke workflows. Its new live governance monitor
[38619333881](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38619333881)
failed because the restricted, read-only GitHub Actions token's live
ruleset response omitted `bypass_actors`. The previous implementation
checked `ruleset.get("bypass_actors") != []`, interpreting a missing
field as if a bypass were positively observed.

In contrast, the independent connected owner-authorized GitHub API
confirmed the actual ruleset #22191532 is active with **zero**
bypass actors, seven protected GitHub Actions status contexts,
merge-commit-only PRs, mandatory resolved review threads and strict
up-to-date status checks. Authentication scope, not a changed protection
rule, accounts for the inconsistent runtime observation.

A lineage-and-salvage preflight on issue #360 established the existing
branch `fix/governance-observability-and-feature-claims-20261014`
was exactly at accepted main with no divergent history or overlapping
PR. All relevant historical controls and signed/unsigned authority
boundaries were already accepted and must be preserved. Paired PR #364
reuses that branch.

## Decision

For the narrow, administrator-only bypass actor list in the live
ruleset response, an explicit empty list is **PASS**, any explicit
nonempty or malformed value is **FAIL**, and a missing/null field is
**BLOCKED**. This does **not** assume that omission proves the list is
empty. Independently verify the ruleset identity, enforcement status,
default branch conditions, deletion and non-fast-forward protections,
pull-request requirement, resolved review threads, merge-only history,
strict check freshness and correct GitHub Actions integration IDs.

The runtime records separate states: `ruleset_controls: BLOCKED` when
the bypass actor list cannot be observed, and
`verified_rule_checks: PASS` only when every accessible mandatory
protection is proven. A scope-limited successful report-generating
job is **not** a successful attestation of the blocked no-bypass field;
it must emit a warning and retain machine-readable evidence.

Pre-merge deterministic tests independently mutate the bypass list to
null, missing, and a real actor, including the combined case of an
unreadable administrator repository setting. An explicitly observed
unsafe actor always fails, even if some unrelated field is blocked.
All other observed unsafe rules, changes to credential boundaries,
and incomplete protected status contracts continue to fail closed.

### Administrator feature claims require separate live verification

A second source-of-truth contradiction was identified in #349:
`.github/repository-governance.json` asserted that the GitHub
dependency graph, secret scanning, and push protection were
`verified-enabled`, while the scanner policy classified dependency
graph as disabled and the other two as unverified. A genuine PR
`dependency-graph/compare` probe returned HTTP 403/404 and correctly
reported dependency review **BLOCKED**. That error does **not**
distinguish a disabled feature from a token authorization limitation.

Until administrator-authorized GitHub API evidence is independently
collected, both checked-in feature inventories now use
`unverified-admin-surface`. A mandatory CI semantic verifier checks
the two sources agree and, with negative fixtures, rejects even a
*matching* `verified-enabled` assertion because agreement between two
writable repository files is not verification. Only a future
explicitly reviewed, independently evidenced governance transition
may change those truthful provisional states. The local source
declarations cannot grant themselves administrator trust.

## Consequences

The read-only accepted-main monitor can provide useful authenticated
evidence for controls visible to the GitHub Actions token without
pretending to attest privileged administrative values. Owner-visible
GitHub settings remain a distinct, dated, authenticated observation.
This avoids granting an owner PAT to a CI job just to improve a badge.

No existing protected check, CodeQL zero-alert qualifier, Security
bridge, source-package evidence verifier, branch deletion protection or
PR approval decision is weakened. The broader Scorecard 24-alert
inventory remains unchanged unless an authentic scan proves otherwise.
A blocked dependency-graph API precondition cannot be converted to a
successful dependency review merely by changing repository metadata.

## Assurance impact

This is an observability classification correction, not an admission of
untrusted self-declared authority. `BLOCKED` cannot compensate for a
`FAIL`, and two partial `PASS` results do not imply whole-repository
governance assurance. Historical audit results and accepted ADR meanings
are not rewritten retroactively. The actual GitHub branch rules still
decide merges, independent of this monitor's report.

## Non-claims

An unreadable bypass-actor list is **not** evidence that no bypass
actor exists. A separate owner-connected ruleset read can verify the
value at a point in time; the unprivileged monitor cannot assert its
own token carried equivalent access. There is no independent human
CodeReview proof, real external fork PR evidence, full signed
Dependabot maintenance PR lifecycle, or OpenSSF Best Practices badge
created by this change. The 18 audited local package detector warnings
and six other Scorecard posture findings remain genuine open SARIF
findings until authoritative scanner evidence changes.
