# ADR 0022: Observe live protected-main merge controls, not committed intent alone

**Status:** Accepted with scoped operational qualification

## Context

The accepted single-CODEOWNER architecture uses protected CI checks as
merge authority and explicitly **does not** claim an independent human
reviewer. The repository had a deliberately separate committed governance
policy and active GitHub ruleset, but no **continuous authenticated
reconciliation** of the remote controls. An actual native auto-merge
activation on PR #361 was rejected because the connector requested squash
while live `Protect Main` required merge commits. The owner has since
changed repository merge settings, independently confirmed via the GitHub
API: native auto-merge and update-branch are enabled, merge commits are
allowed and squash/rebase are disabled.

Before opening this lane, issue #360 recorded exact accepted main
`8fcee27963bbac64dd515d0d691502763ace22c3`, zero open PRs,
only main, all relevant merged historical governance/security PR commit
IDs and exact file blob IDs. No divergently preserved capability was
found; accepted checks, role boundaries and non-claims are preserved.

## Decision

Add a dedicated **trusted-main-only**, **read-only** governance drift job
on push and daily schedule with the exact GitHub repository and ruleset
identities. Its authentication to GitHub uses the scoped default
`GITHUB_TOKEN` to query current repository settings and
`rulesets/22191532` over HTTPS. Check for no bypass actors,
prohibition of main deletion and non-fast-forward updates, pull-request
requirement, thread resolution, merge-only history, strict up-to-date
status qualification, seven exact protected GitHub Actions contexts with
the correct integration identity and native auto-merge/update-branch
settings. New additional protected checks are permitted. Unexpected,
incomplete or inaccessible API replies are **FAIL**, not PASS.

Do not introduce a privileged `pull_request_target` event or run
untrusted fork-submitted scripts in the scheduled control job. The
workflow uses fixed action commit pins, read-only permissions,
credential-free checkout, and the repository identity guard.

Its deterministic adversarial fixtures execute in the already required
`CI / Repository policy` job and in the monitor itself, while the
security-stack gate requires the actual scheduled monitor be present.
All seven existing protected required contexts and the independent
`Package integrity` bridge remain unchanged.

## Separate assessment claims

The live monitor explicitly records `human_review_scorecard=BLOCKED`
while the ruleset requires zero approvals. A user-toggled reviewer count
is not evidence that a **qualified independent human** actually reviewed
a PR. Likewise a green monitor is **not** proof that a signed Dependabot
PR was automatically merged, a genuine external fork PR was qualified,
a private reporting endpoint was verified accessible, or the
OpenSSF Best Practices program granted a badge. Those have separate
administrator, real-event, historical, and human preconditions.

The prior Scorecard finding inventory remains **24 open** (18 tested
local-source/retained-artifact pip install detections plus Branch
Protection, Code Review, SAST history, Fuzzing integration,
age-restricted Maintained, and Best Practices enrollment). The live
monitor must not dismiss, suppress or reclassify these alerts and
must not turn `BLOCKED` into `FAIL` or `PASS` silently.

## Evidence and merge semantics

Every GitHub API response is evidence of **a point-in-time live read**,
not a cryptographic attestation of a repository's historical state or a
guarantee of future enforcement. Only GitHub's actual protected branch
rules control merging. Tests prove that a locally supplied malformed or
weakened configuration fails; a real post-merge workflow must separately
demonstrate GitHub authentication and rule evaluation.

Use the actual native auto-merge facility on the real reviewable PR
once the first required checks are running. A native merge is proven
only by GitHub's `auto_merge` request, successful completion and
accepted-main requalification. Do not mark issue #360 complete merely
because a repository setting was enabled, or because another connector
performed an immediate exact-head merge.
