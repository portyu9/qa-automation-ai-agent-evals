# ADR 0032: An explicit owner review veto outranks historical Dependabot approval

**Status:** Accepted (implementation must still pass protected exact-head and post-merge qualification).

## Context

The narrowly scoped scheduled Dependabot governor `.github/scripts/dependency_governance.py` only merges authenticated GitHub-signed canonical Dependabot updates after verified exact-head checks, a separate owner-token approval and protected GitHub merge. This is **owner-authenticated automation**, not independent human review. The previous `_has_exact_owner_approval` implementation returned true when **any** historical `APPROVED` review carried the configured owner login, numeric account ID, and exact commit SHA. It did not evaluate later owner decisions. Worse, its `_ensure_owner_review_and_approval` path would automatically POST a fresh approval whenever the earlier review was missing or no longer acceptable, which could silently override the owner's explicit request for changes or dismissal.

GitHub's [review documentation](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews) describes `CHANGES_REQUESTED` as reviewer feedback that can block merges when applicable protection is enabled; such protection alone is not a sufficient guarantee for this repository's *zero-required-human-review* CI-authoritative ruleset. The governor must respect an explicit owner veto regardless of whether GitHub's merge API happens to reject it.

The issue #360 lineage-and-salvage preflight comment `6182038421` verified accepted `main@8da85cb2947fb7ea26ca07ff9c51a056e01fe081`, only `main`, zero open PRs, and no outstanding divergent capability. Dependabot lane PRs #341 through #346 have all merged and their signed-source publisher, immutable 12-lock compiler, authenticated no-op on generated child and fail-closed source provenance are already accepted. Relevant exact current blobs were documented before new work.

## Decision

Evaluate submitted owner review *decisions*, not simply membership of any historic `APPROVED` review:

- Authenticate **both exact configured login and immutable numeric user ID**. A mismatch of either on a candidate owner review fails closed. Ignore unrelated users' review decisions as insufficient to impersonate owner approval.
- Consider only submitted `APPROVED`, `CHANGES_REQUESTED`, or `DISMISSED` owner decisions with canonical commit SHA, positive unique review ID, and unambiguous timezone-aware submission timestamp. Ignore informational `COMMENTED` and unsubmitted `PENDING` states. Missing/malformed owner decision metadata fails closed rather than manufacturing approval.
- Determine the most recent decision by submitted timestamp, breaking equal-timestamp ties with the monotonically assigned GitHub review ID. A latest owner `CHANGES_REQUESTED` or `DISMISSED` is a **veto**. A latest `APPROVED` succeeds only when it is for the exact current head. An approval for a stale head does not clear an earlier explicit veto. A newer *actual owner* exact-head `APPROVED` may lift a veto.
- In the scheduled governor, check the veto **before obtaining the privileged owner token or posting even a review comment**, and re-read the decision **again immediately before attempting automated approval**. Respect a concurrently introduced owner veto by leaving the PR **BLOCKED**, not by overriding it with a programmatic `APPROVE`.
- Re-evaluate latest exact-head approval immediately before the final protected merge. Preserve existing signed-commit and bot ID verification, exact-head CodeQL and independent Security protection, hash-locked dependencies, trusted-status limitations and the GitHub ruleset as a second independent authority layer.

Positive and adversarial self-tests cover: original approval, subsequent `CHANGES_REQUESTED` or `DISMISSED`, shuffled list order, latest re-approval, stale head, owner login/ID spoofing, malformed timestamps/commit SHA, duplicate IDs, informational reviews, and a veto that must block before any owner-token action.

## Consequences

- An earlier owner approval cannot be used as merge authorization after a later explicit owner stop decision.
- The governor will not silently reapprove an update the owner just requested changes on. The maintainer can manually submit a fresh exact-head approval or allow a corrected Dependabot PR to proceed through authenticated review again; it is not a general-purpose auto-fixer.
- A malformed owner review history is treated as unavailable evidence (`BLOCKED` or operational failure), not as `PASS`. Concurrency still requires live exact-head re-checks; automation cannot atomically acquire a GitHub human's intent.

## Assurance impact

This closes a real intra-account review-revocation and audit gap in a controller that already proves narrow Dependabot provenance. It strengthens **revocation semantics** without expanding any workflow permission, trusted publisher identity, bypass list, dependency change scope or GitHub merge-method capability. Every existing CI, CodeQL and Security assertion remains authoritative.

## Non-claims

- Matching a configured owner's numeric GitHub account ID **does not distinguish a human action from a valid owner PAT**. Programmatic owner approvals are not independent human code review, and no GitHub Scorecard `CodeReviewID` improvement is claimed.
- Static/CI tests cannot prove a *new* eligible, signed Dependabot PR has completed all 12 current compiler profiles, owner-token review, merge and postmerge qualification. Keep #360 and #349 open until genuine E2E evidence exists.
- This does not fix 18 pip-command Scorecard detector warnings, the upstream SAST app-history checker, independent reviewer/admin configuration, private vulnerability reporting enrollment, OpenSSF Best Practices enrollment or repository age. `BLOCKED` is not `FAIL` or `PASS`; SHA-256 is artifact identity, not authentication of its publisher.
