# ADR 0048: Revalidate PR-head CodeQL authorization at the privileged upload boundary

**Status:** Accepted
- **Date:** 2026-10-16
- **Applies to:** accepted-main-owned `.github/workflows/codeql-pr-publisher.yml`
- **Parent evidence:** #380 and #349; ADRs 0046, 0047

## Context

Before this change, the privileged trusted-main publisher authenticated a successful
read-only pull-request CodeQL workflow, a unique live PR head/base/source tree and the
retained artifact's digest at **discovery**. It subsequently downloaded the artifact,
verified both unfiltered zero-alert original language SARIF reports, then uploaded via
`security-events: write` without a second live authorization check. A concurrent
merge, close, force-update, accepted-main advance, artifact identity change, or
separate authenticated CodeQL upload could invalidate discovery before publication.

A digest is an artifact equality check, **not** a creator signature. A scan success is
not a permission to repurpose an old PR head, to trust unreviewed PR code, or to accept
a code-scanning result for a different category or application.

## Decision

1. Keep `pull_request` CodeQL jobs **read-only**: their checked-out source is untrusted;
   CodeQL local zero-alert veto and full original `actions.sarif` and
   `python.sarif` are mandatory. No PR-owned `security-events:write`,
   `pull_request_target`, or privileged `workflow_run` source execution.
2. Preserve main-only `publish` authority and `github.sha` immutable trusted source.
   The original discovery emits an exact snapshot with PR number, head/base SHA, original
   run ID, original SARIF artifact ID and its GitHub-observed SHA-256 digest.
3. After verified artifact download **and** full SARIF zero-alert/schema checks, and
   immediately **before** the privileged `upload-sarif`, reread canonical GitHub
   workflow run, current main ref, open PR and its head/base, current same-repo branch
   ref, PR merge tree and immutable producer inputs, original job steps, and GitHub
   artifact digest. Require exact equality with the discovery snapshot.
4. Additionally reread active PR Code Scanning analyses and the authenticated native
   `github-advanced-security`/`github-code-scanning` check inventory: refuse to
   upload on an already-published or contradictory concurrent native result.
5. Pin workflow step order, exact expected-output bindings, no `continue-on-error`,
   read-only token and original provenance/SARIF checks in a parsed YAML semantic policy
   with fail-closed mutation fixtures. The trusted verifier independently rejects stale
   head, closed PR, changed main/artifact and competing CodeQL results.
6. If the provider's evidence cannot be independently read, classify **BLOCKED** and
   do not upload. Do not transform BLOCKED into a misleading CodeQL FAIL or PASS.

## Consequences

A stale discovery result can no longer authorize the trusted publisher: the
candidate is rechecked after download against the original snapshot. A concurrent
native scanner publication fails the current job rather than replacing genuine
evidence. This adds bounded GitHub API reads; if they fail, no privileged
SARIF write occurs. The existing pinned 13-context merge policy remains unchanged.

## Assurance impact

The positive claim narrows to a continuously re-evaluated, canonical PR-head,
main SHA, zero-alert original artifact and native Code Scanning identity at the
last publisher-controlled verification step. Semantic mutation tests make this
preupload authorization step non-optional; exact refusal fixtures cover
post-discovery main/head/PR/digest drift and competing reports.

## Non-claims

- Final revalidation narrows, but does **not** mathematically eliminate the race between
  the last GitHub API response and the native `upload-sarif` action; a future atomic
  provider transaction would be necessary for a stronger claim.
- Accepted-main-only trusted publication does **not** establish external-fork PR
  qualification. The first eligible signed Dependabot full lifecycle and independent
  human review governance remain separate open evidence requirements.
- Scorecard SAST is a **rolling 30-commit heuristic**. The old #389/#390 commits lacked
  native final-head evidence and cannot be retroactively represented as cleared. Only
  genuine new protected changes and a fresh **original, unsuppressed Scorecard SARIF**
  can substantiate improvement, including any future 30/30 claim.
- Hash-bound artifact downloads and CodeQL app identity establish a narrower statement
  than source authentication by a signature or independent reviewer.
- No bypass actors, weaker ruleset checks, null-test scan or fabricated status were added.

## Evidence

This ADR is part of [PR #393](https://github.com/portyu9/qa-automation-ai-agent-evals/pull/393).
Record actual exact final PR head, original native CodeQL app check, 13 required contexts,
normal protected merge SHA, postmerge workflow results and fresh Scorecard artifact in
#380/#349 **after verification**; never fill these from predicted future outcomes.
