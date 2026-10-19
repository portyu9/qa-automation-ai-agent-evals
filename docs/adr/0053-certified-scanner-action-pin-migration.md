# ADR 0053: Certify the previously reviewed scanner pin-policy migration

**Status:** Accepted
**Date:** 2026-10-19
**Supersedes:** None

## Context

The accepted scanner coverage verifier previously hard-coded one exact
`ossf/scorecard-action` and `github/codeql-action/upload-sarif` SHA
inside its text contracts. A legitimate signed Dependabot pin-only update
therefore failed scanner qualification, even when pinned to canonical
upstream signed release commits. The verifier is itself a read-only CodeQL
producer executable input. Arbitrary changes to that script must **not**
be approved by a candidate's own tests or GitHub Actions checks.

ADR 0052 and protected merged PR #400 introduced a trusted main-owned
upstream tag/verified-release check for all signed bot workflow action
diffs and **preapproved the exact candidate scanner script blob**
`12eab86b64d4c9ec637150c4e76868dcc052a025`.
The accepted-main trusted publisher may authenticate precisely that one
already reviewed source file, not any newly declared validator hash.

## Decision

Migrate only the exact preapproved `.github/scripts/validate_security_stack.py`
source blob. Retain the original mandatory CodeQL/Python/Actions scanner
inventory, Scorecard trigger, SARIF upload/triage outputs and fail-closed
permissions. Replace two stale exact-SHA string literals with canonical
action-identity requirements and **mandatory full-40-character lowercase SHA**
checks, not mutable tags, branches, or blanket ignores.

No workflow, permission, trigger, review gate, publisher script, or
repository ruleset is modified in this migration. The trusted CodeQL
publisher from accepted main must verify the candidate scanner source SHA
matches its code-owned preapproval before accepting any SARIF.

## Consequences

Future signed bot upgrades for these action names will not require
editing this executable scanner verifier for each patch release. The
separate accepted-main publisher still requires official upstream GitHub
tag dereferencing, exact pinned SHA and GitHub-verified target commits,
signed Dependabot head and one-for-one changes across the entire PR.

Scanner success remains insufficient for merge: separately qualified
read-only CodeQL zero-alert evidence, authentic native exact PR-head
CodeQL, CI, Security and all 13 protected branch checks must succeed.

## Assurance impact

This is an **exact prior source approval**, not a hash treated as
authentication. The independent reviewer-authorized accepted-main
constant is the approval authority, and the Git blob hash is the
immutable equality handle. Candidate code cannot change that authority.
Any extra script edit, missing scanner action, mutable action ref,
permission regression, missing SARIF or changed trust boundary remains
BLOCKED/FAIL as appropriate; never promoted to PASS.

## Non-claims

- Scanner success is not proof of absence of vulnerabilities.
- A SHA alone is not verification of vendor origin or software safety.
- Tag/commit verification does not prove absence of upstream compromise.
- No suppression of CodeQL, Scorecard, dependency review or baseline
  findings, and no merge/ruleset bypass, is authorized.
- Full autonomous operation requires real live signed-bot owner-token
  authorization and protected merge, not a synthetic test or manual
  owner merge.
- Admin-only inaccessible settings remain BLOCKED.

## Evidence

Base `main@75a55960ab65d1915d4a2b7dd90637525faa70d2`
merged PR #400 / ADR 0052. GitHub ref inventory before branching:
only `main` and the one open signed bot PR #397 branch; no orphan
hardening branches, no divergent unique code or test requiring salvage.
Historical #389 was explicitly reverted by merged #390; PR #398 was
already accepted. Preapproved scanner blob as above, accepted publisher
blob `46aca6933294ccbdcb8cea2200b0006a22778dbb`.
Issue #399 records outstanding live bot E2E validation.
