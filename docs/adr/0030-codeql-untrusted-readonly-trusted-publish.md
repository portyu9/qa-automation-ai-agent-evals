# ADR 0030: Separate unprivileged CodeQL PR analysis from trusted main Code Scanning publication

**Status:** Proposed, subject to independently successful exact-head PR and post-merge push qualification.

## Context

On accepted `main@54e4d7893eb9eb8bb758a7e2c98f6aaa1ad277c7`, the CodeQL workflow's sole `codeql` job analyzes both same-repository and external `pull_request` code, executes repository Python validation from the proposed head, and requests `security-events: write`. Its analyzed PR branch has `upload: never` and checkout credentials are not persisted, which are valuable safeguards, but **neither is a principled reason to grant an untrusted source analyzer a write-capable job token**. Fork tokens are normally read-only, but same-repository proposed heads may receive the write grant. The security policy validator previously *required* that elevated analyzer token, so the privilege error was policy-encoded.

The complete live accepted-main lineage-and-salvage preflight is issue #349 comment `6181301375`: only `main`, no competing open PRs or divergent unmerged branches; merged PR #361 already established mandatory CodeQL fork coverage and fail-closed zero-result veto; #353–#356 already established exact-subject independent Security/CodeQL qualification, and #365 added Scorecard check visibility. Exact source/policy blobs are documented there and preserved; no earlier capability is stranded.

## Decision

Use two distinct jobs with no elevated workflow-wide permissions:

1. **`codeql` analysis:** runs unconditionally on every configured event, including *both same-repo and fork* PRs, using explicit read-only `actions`, `contents` and `security-events` permissions. Check out exact proposed source with `persist-credentials: false`. Preserve pinned `github/codeql-action/init` and `analyze` for Python and GitHub Actions with `security-extended` queries. Set `analyze upload: never` for *every event*, run existing fail-closed CodeQL raw-SARIF zero-alert gate, and retain exact-workflow `codeql-sarif-<run_id>` even upon failures. Never run PR code in `pull_request_target` or `workflow_run` authority.

2. **`codeql-upload` publisher:** depends on successful `codeql` and may run *only* for trusted `main` refs on non-PR events. The only permitted write is `security-events: write`. Download the exact same-run named SARIF artifact using immutable pinned official actions, check out trusted accepted main without persisted credentials, independently revalidate the retained SARIF using the existing fail-closed zero-alert verifier, and then upload the original evidence through the pinned `github/codeql-action/upload-sarif` action. No source-supplied PR scripts are executed in this privileged job.

Change the repository-owned semantic workflow policy to **remove** `security-events:write` from the unconditional analysis job's exception and admit it *only* on the exact guarded `codeql-upload` job. Enforce pinned step/action identities, exact-run download path, mandatory re-verification, non-skippable scan and publishing steps, negative tests for skip/privilege/condition/artifact substitution, no privileged fork execution and unchanged job/dependency authority. Keep existing protected `Package integrity` bridge and independent Security checks. Requalify all protected PR checks before merging; then prove CodeQL's genuine accepted-main publication independently from the protected postmerge `CodeQL` workflow and stored Code Scanning SARIF.

## Consequences

- Source supplied in a PR (fork *or same repository*) cannot obtain write-capable `security-events` authority via the CodeQL analysis job, even if it changes its own scanner verification script.
- The privileged Code Scanning publication remains possible for independently validated accepted-main results only. A missing, malformed, or nonzero-alert SARIF fails the uploader before publication.
- Accepted-main CodeQL job graph changes from one job to two; a green `CodeQL` workflow includes both jobs on trusted main, while PR analysis still vetoes findings and uploader is necessarily skipped. The difference must be verified by the live GitHub run, not inferred from YAML.
- This change does **not** introduce a publish-on-fork privilege path or bypass the current seven main ruleset checks.

## Assurance and non-claims

- This is **permission least-privilege hardening**, not a declaration that Scorecard's historical `SASTID` `0/30` check-run recognizer will improve. Upstream Scorecard detects scanner *app slugs* on the historic PR heads, not mere presence of a CodeQL job. Actual CodeQL scan execution must be evaluated separately.
- A successful scanner check does not establish all vulnerabilities absent. SHA-256 artifact identity is not publisher authentication, and the job token cannot authenticate a source user's claims.
- This does not resolve the 18 local-only PinnedDependencies scanner warnings, independent human review, Maintained 90-day age, Best Practices enrollment, fork E2E run with a real external contributor, or the signed eligible Dependabot maintenance cycle. Keep #349/#360 open, never relabel `BLOCKED` as `PASS`.
