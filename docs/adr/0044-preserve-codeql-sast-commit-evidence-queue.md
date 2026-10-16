# ADR 0044: Isolate read-only CodeQL runs by the exact source commit

**Status:** Accepted

## Context

Authentic unfiltered OpenSSF Scorecard [run 38906594311](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38906594311) on accepted main
reports `SASTID` **8/10, 18/30** recent commits recognized. The finding
is real and must remain unsuppressed while its historical coverage gap
persists. Inspection of exact GitHub PR commit check-runs found intermediate
commits such as `ad2b06e5b2` and `6a9566d05a` with cancelled CodeQL
workflows, and intermediate commits including `a68904de74` and
`2598464200` with no CodeQL check attached, despite successful final
PR-head scans. This is genuine missing evidence; not every absent result
has an independently established identical cause.

The read-only PR producer in `.github/workflows/codeql.yml` previously
used a per-PR concurrency group and `cancel-in-progress: true`.
Consequently, a quick commit update cancelled the older PR's ongoing
CodeQL scan. A per-PR group with only `cancel-in-progress: false` still
has GitHub's default one-pending-run replacement behavior: some
intermediate commits can be dropped before their checks execute.

GitHub documents `concurrency.queue: max` as an up-to-100 pending-run
alternative as of May 2026. That syntax is not yet understood by this
repository's pinned actionlint validation (see upstream
[rhysd/actionlint#657](https://github.com/rhysd/actionlint/issues/657)),
and adding it without an independently qualified toolchain would break
mandatory Actions security checks. Do not bypass the linter, suppress
its error, or misrepresent the unaccepted `queue` configuration as
operational. A different, compatible design can avoid cross-commit
cancellation without changing token authority.

## Decision

Give each read-only CodeQL workflow run a concurrency group that includes
the **exact source commit SHA**, in addition to the existing repository and
PR identity:

`codeql-${{ github.repository }}-${{ github.event.pull_request.number || github.ref }}-${{ github.event.pull_request.head.sha || github.sha }}`

Set `cancel-in-progress: false`. Do not use an unqualified `queue` key.
The PR event head SHA is source-owned metadata and affects **only
cancellation/resource grouping**, never privileged publication authority.
For non-PR events the expression uses the accepted event's `github.sha`.
A newer PR source commit therefore occupies a different concurrency
group and cannot cancel or displace the prior SHA's running or pending
scan merely by advancing the branch.

Extend the existing fail-closed workflow graph validator to pin the
**exact** repository/PR/SHA group and false cancellation state. Add
adversarial fixtures that reject setting cancellation to true, removing
the SHA dimension (reintroducing single-pending-run replacement across
commits), or collapsing the group to a whole-repository identity.
Keep all existing negative tests for fork privilege elevation,
`pull_request_target`, accidental SARIF uploads from PR code,
original-SARIF zero-alert veto, and accepted-main-owned publication.

The untrusted `pull_request` scanner remains read-only on every
same-repository or external fork event. The separate main-only trusted
publisher still independently authenticates live **current** PR source
identity, exact original run, immutable producer bytes, retained artifact
and original zero-alert SARIF, and requires native Code Scanning app
qualification where relevant. Historical intermediate scans do **not**
grant authority to publish SARIF as though they were current PR heads.

## Consequences

Distinct source SHA events can now be scanned concurrently rather than
cancelling each other through the original per-PR group. Resource usage
may increase when contributors push rapidly. Identical-SHA reruns still
share a group, and GitHub can reject, delay or drop workflow events for
other limits; this change does not create an unbounded delivery guarantee
or retroactively repair earlier cancellations. The repository's global
resource, Actions and artifact-retention limits still apply.

Future independently successful CodeQL source checks on real PR commits
may raise the rolling Scorecard SAST fraction as old, unqualified
commits leave its genuine last-30 sample. An ordinary
`github-actions CodeQL` result is distinct from a native
`github-advanced-security` Code Scanning result. Separate native
publication remains deliberately evidence-bound and may be BLOCKED on
GitHub inventory/category mismatch or an external fork.

## Assurance impact

This changes the **availability** of legitimate read-only scan results,
not their trust level. Each commit must produce its own genuine
successful zero-alert scan; neither a newer green PR-head scan nor
a digest is authentication of a missing prior result. No privileged
token is added to code executing PR-supplied sources. `BLOCKED` remains
distinct from `FAIL`, and no compensatory aggregation replaces the
per-commit scanner decision.

Protected merges still require all existing 13 mandatory exact-head
Actions contexts and zero bypass actors. Independently running an
intermediate source scan cannot turn an unverified final head green.

## Non-claims

- This does **not** immediately increase the true `SASTID` count from
  18/30 to 30/30, dismiss alert #27, or create historical green checks.
- This does **not** claim `queue: max` works with the pinned actionlint
  toolchain or guarantee every GitHub event is executed.
- This does **not** qualify privileged native publication on forks,
  force GitHub's best-effort trusted-main scheduler to run, or count
  an Actions CodeQL result as a native GitHub Advanced Security result.
- This does **not** relax CODEOWNER, branch protection, mandatory
  reviewers, scanner zero-alert criteria or the original verifier.
- The existence of a final green scan cannot prove every intermediate
  source commit passed; those remain independently checked or unknown.

**Tracking:** [#380](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/380)
and [#349](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/349).
