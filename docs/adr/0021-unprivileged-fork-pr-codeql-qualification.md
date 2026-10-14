# ADR 0021: Qualify external fork pull requests with unprivileged CodeQL

**Status:** Accepted

## Context

At accepted `main@16b33658761a8ad57537bb6f0b4404f4e6353370`,
the repository already requires `Package integrity` to verify exact
PR-head CodeQL and independent Security workflow success. However,
`.github/workflows/codeql.yml` skipped the entire CodeQL job for
fork-origin PRs, while CI's protected aggregate continued to require
an independently successful CodeQL run. That could deadlock a legitimate
external contribution or, if somebody weakened the bridge to accept a
skipped job, reduce assurance. The existing CodeQL `analyze` step
already emits local SARIF and selects `upload: never` on all PRs.
The scan also includes a locally executed, strict zero-alert validator.

The lineage and salvage preflight was recorded on issue #360 **before**
branch `security/fork-codeql-readonly-20261014` was created:
only accepted main remained, there were no open PRs or divergent live
branches, and merged historical CodeQL/security PRs #273, #280, #283,
#284, #338, #350, #354, #356 and #359 were all already accepted.
Exact baseline blob identities and merge commits are in that issue.
Nothing unique needed recovery, and all accepted CodeQL/Security
evidence semantics must be preserved.

## Decision

- Run the **same** CodeQL `pull_request` job for both same-repository
  and external fork PRs; do not switch to privileged
  `pull_request_target` or `workflow_run`.
- Preserve the `github/codeql-action` pinned action SHA, Python and
  GitHub Actions analysis, `security-extended` queries, local SARIF
  output, and fail-closed **zero alert** enforcement on every PR.
- Preserve `upload: never` for **all** PRs. Only trusted push,
  schedule and manual default-branch runs upload results to Code
  Scanning, and all executions retain SARIF for independent review.
- Trust GitHub's documented public-fork `pull_request` event policy:
  fork `GITHUB_TOKEN` is read-only and repository secrets are not
  delivered, even when a job nominally requests
  `security-events: write` for trusted push uploads. Treat private
  repository admin settings permitting write tokens to forks as
  *outside* this public repository's assurance claim.
- Move the privileged CodeQL job guard from a **skip external forks**
  condition into the independent semantic workflow graph policy,
  requiring exactly one no-skip CodeQL job, exact non-upload on PR,
  exact local SARIF verifier, credential-free checkout and no secrets.
  Add negative mutation tests of each privilege/bypass regression.

## Consequences

Same-repo PR CodeQL behavior and accepted-main Code Scanning uploads
remain unchanged. An external fork PR can now run the same local
CodeQL zero-alert analysis without access to repository-write
authority. The independent `Package integrity` job continues to
check **all** exact-subject successful CodeQL and Security runs;
missing, skipped, failed and pending evidence is never counted as
success. Existing other protected job requirements remain unchanged.

This is a necessary condition for considering a direct CodeQL ruleset
check for all PRs, but full fork eligibility still requires a **real,
externally originated PR** demonstrating read-only CodeQL, security
gate, package integrity, first-time contributor approval policy and
GitHub check conclusions. Do not change admin rulesets based solely
on a same-repository PR test.

## Assurance impact

The job-level skip is removed rather than bypassing the downstream
requirement. The decision preserves an independent CodeQL analysis,
conservative no-upload of untrusted PR results, exact head evidence
binding and a non-compensatory PASS/FAIL gate. The semantic validator
owns trusted exceptions; a workflow cannot simply declare itself
trusted. Unit mutation tests reject disabled scanning, branch skips,
unsafe triggers, persistent GitHub tokens and SARIF gate removal.

## Non-claims

This does not demonstrate full real-fork PR success until an actual
untrusted fork passes. It does not make AI/bot-authored reviews qualify
as independent **human** reviews; it does not change native
`allow_auto_merge` from a repository option into an always-on
auto-merger, nor prove that Dependabot has completed a full
end-to-end automatically merged signed update. It neither fixes
Scorecard's 18 existing local package-install heuristics nor makes
the repository older than 90 days or earns a Best Practices badge.
A successful CodeQL run is not evidence that all possible code
vulnerabilities are absent.
