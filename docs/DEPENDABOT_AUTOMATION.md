# Dependabot automation authority

The default-branch `dependency-governance` workflow is the repository's sole autonomous Dependabot merge authority. The previous standalone green-check auto-merger is retired by the same change that introduces this control plane.

## Green-path merge

Autonomous merge covers canonical Dependabot Python and GitHub Actions version/security updates, including major versions, only after exact-subject qualification. Governance requires a current `main` base, repository-owned head, verified Dependabot commit provenance, an exact prospective merge subject, and green `ci-gate` plus `CodeQL` checks on the exact head.

GitHub Actions changes must be one-for-one immutable action-SHA replacements for the same action identity and an advancing semantic version; arbitrary workflow edits remain blocked. Python changes must modify only `pyproject.toml` dependency specifications: package identities and optional-dependency groups must remain unchanged, additions/removals/renames are rejected, direct URL/VCS/path/marker authority is rejected, and every non-dependency TOML semantic must remain identical. The CI matrix installs the candidate `pyproject.toml` graph on Python 3.11-3.14 and `ci-gate` aggregates the behavioral, typing, security, packaging, mutation, OpenAI, and MCP evidence before merge.

Governance/recovery/workflow control-plane files, manual-review labels, and mixed-ecosystem diffs remain fail-closed. An hourly reconciliation sweep detects stale canonical Dependabot proposals and, through an identity-verified `DEPENDABOT_OWNER_TOKEN`, asks Dependabot to rebase them natively; governance never calls the update-branch API. The same owner-scoped token is used only for the exact-head audit comment and exact-head approval after all qualification gates pass. The controller revalidates the unchanged head and approval immediately before merge.

## Red-path recovery

Recovery has no merge authority. It can request at most one rerun (`maxRunAttempts == 2`) for the reviewed `CI` workflow, and only when exactly one non-aggregate leaf job and exactly one code-owned infrastructure/upload step fail with timestamp-bounded transient network/service evidence. Deterministic dependency-resolution, hash, policy, HTTP 4xx/rate-limit, permission, and disk failures override any transient-looking text and block recovery.

Tests, mutation scores, OpenAI/MCP behavioral lanes, package verification, security analysis, CodeQL, and `ci-gate` are never recovery targets. A second failed attempt remains red for manual investigation.

## Code scanning

`codeql.yml` runs Python and GitHub Actions CodeQL with `security-extended` queries on pull requests, `main`, a weekly schedule, and manual dispatch. The analysis retains SARIF evidence for 14 days and a fail-closed zero-alert gate rejects every CodeQL result before the `CodeQL` check can become green; scanner execution success alone is not merge evidence. External-fork pull requests do not receive write-capable code-scanning execution.

A tracked-source inventory contract also fails closed if a first-party code language appears without scanner coverage. Today the repository's first-party executable stack is Python plus GitHub Actions, so the required CodeQL mapping is exactly `python,actions`; adding another recognized code language requires extending the scanner contract in the same change.

The owner token must authenticate `portyu9` (numeric user ID `35150859`) and be repository-scoped with only the permissions needed to comment on issues/pull requests and submit pull-request reviews. It is not used for repository contents writes, Actions reruns, or merges; those remain on the repository workflow token and existing exact-head governance path.
