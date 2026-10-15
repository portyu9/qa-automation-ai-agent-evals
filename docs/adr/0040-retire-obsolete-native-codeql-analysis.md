# ADR 0040: Retire obsolete native CodeQL analysis configuration without weakening PR scan authority

**Status:** Proposed pending genuine post-retirement PR-head native CodeQL qualification

## Context

ADRs 0030, 0038, and 0039 separate the untrusted `pull_request` CodeQL
analysis/zero-alert veto from write-authorized SARIF publication on accepted
`main`. The main-owned publisher verifies the exact original producer run,
unchanged executable inputs, original Python and Actions SARIF, accepted-main
workflow SHA, live PR head, and CodeQL artifact before uploading to the
established `.github/workflows/codeql.yml:codeql-upload` category. It does
not execute PR code with elevated permission.

A historical main-only native CodeQL `analysis_key/category`,
`.github/workflows/codeql.yml:codeql`, remained in GitHub Code Scanning's
configuration expectations after its job changed to `upload: never`.
Consequently, on genuine PR #383 (head
`f45321ac64a829fca0025e4da24404c2de45f65d`) the accepted-main
scheduled publisher run
[38810553226](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38810553226)
authenticated both zero-alert original CodeQL SARIF inputs and uploaded them
successfully, but the **native** `github-advanced-security` CodeQL check
concluded **NEUTRAL**, with *one configuration not found* (the obsolete
`codeql` stream). A green GitHub Actions CodeQL job or publisher is
insufficient to assert native Code Scanning success.

Before deletion, the maintainer used authenticated GitHub CLI/REST access to
enumerate all main CodeQL analyses and CodeQL alert states. That audit
reported **80 legacy** `codeql` analyses with no findings, warning or error
for any of them; **10 active** `codeql-upload` analyses with latest
`id=1963408731` on accepted
`main@76426ef66336a6272f341edffbe54863e3eefa23`; and an empty
CodeQL alert-state aggregate. Their identities were distinct, not two
names for interchangeable authority. The historical legacy tip commit
`54e4d7893eb9eb8bb758a7e2c98f6aaa1ad277c7` is an ancestor of
accepted main, not a unique abandoned implementation to salvage.

## Decision

The maintainer retired **only** the obsolete `codeql` Code Scanning
analysis set by GitHub's newest-first deletion API, preserving the active
`codeql-upload` set. A bounded script checked the immutable expected main
SHA, individual legacy analysis identity, empty findings/errors, the unique
deletable newest legacy record, and the entire set of ten active IDs before
each deletion. The owner explicitly approved the initial destructive
operation and separately approved the final legacy-config deletion.

The owner-provided terminal record reports all 80 deletes, including final
legacy analysis `1786856310`, and these script postconditions:

```text
RETIREMENT COMPLETE
Legacy analyses remaining: 0
Active analyses preserved: 10
Audit directory: codeql-retirement-20261015T225046Z
```

The JSON inventory and SHA-256 manifest reside in the **owner's local audit
directory**. They were not uploaded as an independently retained GitHub
artifact, and the connected assistant GitHub app cannot inspect the live
Code Scanning analysis-list endpoint. We distinguish owner-executed script
evidence from independently observed post-retirement native checks; no
deleted alert history can be reconstructed merely from retained metadata.

The retired analysis category must not be resurrected, even to force a
cosmetically green Code Scanning result. The supported category remains
`.github/workflows/codeql.yml:codeql-upload`. Source CodeQL stays
read-only on all PRs (including forks), with `security-extended`, local
zero-alert veto and original SARIF retention. The privileged publisher stays
separate, main-owned, workflow-SHA-bound, and limited to exact authenticated
same-repository PR evidence.

## Consequences

A new **real same-repository PR** must exercise the CodeQL producer, original
zero-alert check, main-owned trusted publisher and native GitHub Code Scanning
check on the **same exact head commit**. The native CodeQL check must conclude
**SUCCESS**, not NEUTRAL, SKIPPED or an inferred success from workflow
completion. The active analysis category and authentication evidence must
match. Only after normal non-bypass protected merge and subsequent authentic
unfiltered Scorecard output may SAST #27 be reassessed; a historical
9-of-30 rolling SAST count does not instantly become 30-of-30.

The Protect Main ruleset has 13 strict required GitHub Actions checks and
zero bypass actors; the prior owner-approved migration removed the native
code-scanning premerge ruleset constraint. This ADR does **not** silently
restore that rule or claim an equivalent native premerge policy. Restoring a
native gate would require an independent, non-deadlocking, scoped governance
decision and an authentic end-to-end qualification.

## Assurance impact

Retirement removes a stale native analysis expectation. It does not add
privilege to PR code or relax CodeQL/Security/Package-integrity enforcement.
A checksum is only an integrity check, not standalone source authentication.
Missing or mismatched CodeQL evidence remains **BLOCKED**, not PASS or FAIL
by inference; fail-closed behavior takes priority over automatic publication.
Previously published original CodeQL SARIF is never altered to suit a detector.

## Non-claims

- There is **no** claim that the new PR's native CodeQL result is already
  successful; it has to be independently measured on its exact head.
- There is **no** claim that Scorecard SASTID #27 is already resolved or that
  historical PR-head coverage is retroactively complete.
- There is **no** claim that the owner-local archive is remotely attested,
  that no original historical records were irreversibly lost, or that the
  connected GitHub app independently verified all 80 deletion API responses.
- There is **no** new delegated publication authority for external forks:
  original read-only scanning remains active, while the privileged delegated
  publisher for fork PRs remains **BLOCKED** until separately qualified.
- There is **no** suppression, manual dismissal, fabricated native check,
  native ruleset bypass or modification of accepted ADRs 0030/0038/0039.

**Operational tracking:** [issue #380](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/380),
[parent Scorecard issue #349](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/349).
