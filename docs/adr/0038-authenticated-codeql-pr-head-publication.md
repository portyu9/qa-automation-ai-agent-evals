# ADR 0038: Attribute genuine read-only PR CodeQL to its exact head through a trusted publication boundary

**Status:** Accepted, conditional on exact-head CI, authentic PR-head code-scanning and non-bypass mergeability evidence.

## Context

Actual OpenSSF Scorecard SASTID #27 is 7/10, with 0 of the last 30 merged PR
heads carrying successful check-runs from a recognized SAST app. The repository
already scans every `pull_request` (including forks) with the pinned CodeQL
Python/Actions security-extended analysis and a mandatory original-SARIF
zero-alert veto, and scans/uploads on accepted `main`. However PR check-runs
are authored by `github-actions`, while OpenSSF counts native
`github-code-scanning`, `github-advanced-security`, and a few established
external SAST apps. The separate main-only uploader in accepted ADR 0030
intentionally does not grant security reporting permission to untrusted PR code.

A simple `push` trigger does not repair PR-head check attribution, and a
write-capable `pull_request` analysis job would restore the exact trust error
rejected by ADR 0030. `pull_request_target` would carry an even riskier
privileged checkout/build boundary and may be blocked by GitHub policy.

## Decision

Keep `.github/workflows/codeql.yml` unchanged: unprivileged PR scanning,
unmodified original CodeQL SARIF, zero-alert veto, exact-run forensic artifact,
and existing authenticated accepted-main Code Scanning publication.

Add a distinct trusted **`workflow_run` consumer** executed from GitHub
default-branch workflow source after the canonical CodeQL PR run reports success.
Its only write authority is `security-events: write`, held in a single publisher
job. It checks out *accepted main source only* into `trusted/`, with checkout
credentials not persisted. It never checks out, evaluates, sources, or executes
the candidate PR's files in its privileged runner.

The trusted verifier re-reads GitHub APIs with the live read-scoped job token:

- exactly the canonical immutable CodeQL workflow ID/path/event/name/success and
  first attempt, head branch, same-repository identity, and one live open PR
  with exact current base/head/branch;
- PR merge-ref tree equals the actual head source tree; reject potential
  misattribution if the CodeQL PR merge-check subject differs;
- active CodeQL workflow, Python zero-alert validator and both validator self/
  stack-check source files are *byte-identical* to accepted main on candidate
  head. If an untrusted PR changes any producer input, this delegated report
  cannot be trusted and is explicitly **BLOCKED** rather than promoted;
- live run's CodeQL scanner job and mandatory scan/veto/forensic steps all
  completed successfully, and the unique retained SARIF belongs to that
  exact completed run/head with bounded size and GitHub artifact digest;
- download by exact authenticated run ID; verify original retained SARIF with
  trusted-main CodeQL zero-alert verifier, strict CodeQL tool/run identity,
  bounded files, and a final original-data veto. Never transcode, filter,
  fabricate, or suppress CodeQL alerts.

Only after those preconditions pass, use the immutable pinned GitHub
`upload-sarif` action with explicit `refs/pull/<number>/head` and actual
`head_sha`, and a separate Code Scanning category. The official action
supports explicit ref and SHA inputs, but end-to-end proof must verify the
*actual* GitHub Code Scanning check-run app attribution. The workflow's privileged
steps, origin event, exact publisher output bindings, and self-test are
immutable contracts in the semantic workflow graph validator with mutation
fixtures. Never allow candidate-controlled `ref`, `run-id`, SARIF path,
script path, shell expression, or permission setting.

## Scoped non-claims and migration boundaries

- Fork PRs **continue to run unprivileged CodeQL and zero-alert veto**. Trusted
  PR-head publication is initially BLOCKED for fork heads until an independently
  verified safe fork receipt and GitHub upload association are designed. Do not
  convert fork data into trusted origin.
- An artifact checksum shows byte integrity **only**. Authentication follows
  the separate GitHub producer run, immutable accepted-main executable inputs,
  matching source tree, and explicit provenance revalidation. This does not
  eliminate vulnerabilities in CodeQL tooling or GitHub platform.
- A Code Scanning upload check may be absent, associated with the wrong SHA, or
  accepted after the PR changed. These are **BLOCKED** until a real same-repo PR
  proves `github-code-scanning` success on its exact head. API upload success,
  a generic `github-actions` check, or a hash is not enough.
- Historical 0/30 is not retroactive. Even verified new PR-head native checks
  only improve the genuine rolling Scorecard sample over real future merges.
- An open PR that modifies the scanner workflow/validators is not eligible for
  this delegated publication until a separately trusted reanalysis strategy
  exists. Do not disable mandatory CodeQL in its place.
- The live ruleset currently requires CodeQL and Scorecard Code Scanning tools
  and zero bypasses. The correctness of premerge Scorecard reporting and
  non-bypass mergeability must be proven independently. Never bypass the native
  ruleset or fabricate a green scanner status to merge this change.

## Verification required before accepted status

1. Semantic workflow graph negative mutations, verifier fake-API adversarial
   fixtures, exact accepted-main CodeQL and security policy tests all pass.
2. A legitimate same-repo PR produces an authentic native
   `github-code-scanning` completed successful check on its exact PR head.
   Confirm actual SARIF evidence unchanged and security-events permissions
   confined to the publisher.
3. Qualify a fork PR remains read-only and fail-closed; document the blocked
   trusted publication honestly.
4. Prove full current-base required checks, actual non-bypass native merge, and
   resulting accepted-main CodeQL/Scorecard reports. Re-run real Scorecard and
   inspect SAST historical fraction without altering, dismissing or hiding
   genuine warnings.

Related: issues #380, #349, #360; ADR 0030, ADR 0031.
