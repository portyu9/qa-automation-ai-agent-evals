# ADR 0044: Retain authentic per-commit CodeQL checks with bounded PR scan queue

**Status:** Accepted

## Context

OpenSSF Scorecard's `SASTID` currently recognizes **18/30** recent
commits on genuine accepted-main unfiltered [run
38906594311](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38906594311).
The original `SASTID` remains an actual finding, not a filter target.

Independent canonical GitHub commit/check-run inspection of the 30 most
recent accepted-main SHAs shows several intermediate PR commits lacking
a successful source CodeQL scan even though later head SHAs successfully
ran read-only CodeQL: e.g. `ad2b06e5b2` and `6a9566d05a` have
`CodeQL` runs with conclusion `cancelled`; intermediate
`a68904de74` and `2598464200` have no attached CodeQL check.
Meanwhile terminal PR heads have genuine `github-actions CodeQL`
`success`, and some previously observed heads received independent
main-owned `github-advanced-security CodeQL` successful native scans.
These examples establish a missing historical evidence problem, not a
claim that every such gap has exactly the same root cause.

The accepted read-only scanner workflow `.github/workflows/codeql.yml`
uses a per-PR workflow-level concurrency group with
`cancel-in-progress: true`. This intentionally cancels older
in-progress runs when the PR branch receives a newer source commit,
leaving the older SHA without a completed scan. Merely switching
`cancel-in-progress` to false without a queue still retains GitHub's
single-pending-run replacement behavior and can discard a series of
rapid source updates.

GitHub documented [bounded concurrency queues on May 7,
2026](https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/):
`queue: max` with no in-progress cancellation permits up to 100
pending workflow runs per concurrency group, processed separately. A
per-PR queue is preferable to unlimited parallel CodeQL scans because
it avoids unnecessary resource spikes while retaining intermediate
authentic analysis results.

## Decision

Keep the **exact existing** workflow-level per-PR/main-ref concurrency
group `codeql-${{ github.repository }}-${{ github.event.pull_request.number || github.ref }}`,
but change only its scheduling behavior to:

- `cancel-in-progress: false` so newer PR synchronize events never
  automatically terminate an already-running source CodeQL scan;
- `queue: max` so multiple pending commit scans for that same PR
  can be retained rather than replacing all but the newest pending run.

Strengthen the fail-closed `.github/scripts/validate_workflow_graph.py`
policy to require this exact group/false/max combination. Deterministic
adversarial fixtures must reject restored `cancel-in-progress: true`,
replacement of `queue: max` with the single-pending queue, or
broadening the group to drop the per-PR partition. Existing workflow
self-tests continue to reject unsafe `pull_request_target`,
write-authority in an untrusted job, skipping original SARIF validation,
client-side SARIF substitution, and bypass of the trusted-main publisher.

The scan continues to run read-only for all same-repo and external-fork
`pull_request` heads, retaining the exact original zero-alert SARIF
veto and source-run artifact. A separate accepted-main-only publisher
is still solely responsible for authenticated Code Scanning publication,
with its own original evidence binding, scoped token and active category.
No privileged PR event or new token permission is introduced.

## Consequences

More legitimate PR source commits may finish with genuinely successful
CodeQL checks rather than cancelled/missing checks. This may improve
Scorecard's rolling recognized history as real future source commits
replace older unrecognized commits, but is not an immediate correction
to existing GitHub check histories. Intermediate CodeQL scans may take
extra Actions minutes and repository artifact storage. The bounded
`queue: max` is capped at 100 pending per concurrency group; GitHub
may still fail/limit runs for unrelated platform reasons. Every finished
scan must stand on its own zero-alert and evidence gates.

A completed `github-actions CodeQL` scan is not equivalent to a
successful native `github-advanced-security CodeQL` check. The trusted
publisher still requires canonical live exact PR head, original
authentic SARIF, category and successful native check, and external
fork delegated publication remains BLOCKED pending real qualification.
Preserving intermediate scans does not grant their historical commits
authority to publish SARIF against the latest PR SHA.

## Assurance impact

The new queue changes only **liveness of read-only evidence production**,
not scanner authorization or strict non-compensatory safety. It preserves
the distinction between a cancelled/missing scan and an authentic
`success`: future runs can complete and be verified on their own
original SHAs without pretending a later successful run covers an
earlier SHA. If the queue fills or GitHub does not execute the scan,
the result remains missing or BLOCKED, not PASS.

Normal protected merge still requires all 13 required Actions contexts
on the **current** PR head and zero bypass actors. Any native app
qualification must be verified separately rather than copied from
another head.

## Non-claims

- This does **not** retroactively make Scorecard `SASTID` 30/30,
  dismiss security Code Scanning alert #27 or repair historical
  cancelled PR heads without real new scans.
- This does **not** guarantee every GitHub Actions event executes or
  that a queued scan passes; Actions capacity, external-fork events and
  queue limits remain independent constraints.
- This does **not** reduce any existing privilege boundary, use hashes
  as authentication, make a failed CodeQL source scan compensatable,
  or treat `BLOCKED` as `FAIL`.
- This does **not** demonstrate fork delegated native Code Scanning or
  independently human-reviewed governance. Those remain separately
  tracked.

**Tracked by:** [#380](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/380),
[#349](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/349).
