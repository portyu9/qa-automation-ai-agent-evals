# Dependabot automation authority

The default-branch `dependency-governance` workflow is the repository's sole autonomous Dependabot merge authority. The previous standalone green-check auto-merger is retired by the same change that introduces this control plane.

## Green-path merge

Autonomous merge covers canonical Dependabot Python and GitHub Actions version/security updates, including major versions, only after exact-subject qualification. Governance requires a current `main` base, repository-owned head, verified Dependabot commit provenance, an exact prospective merge subject, and green `ci-gate` plus `CodeQL` checks on the exact head.

GitHub Actions changes must be one-for-one immutable action-SHA replacements for the same action identity and an advancing semantic version; arbitrary workflow edits remain blocked. Python changes must modify only `pyproject.toml` dependency specifications: package identities and optional-dependency groups must remain unchanged, additions/removals/renames are rejected, direct URL/VCS/path/marker authority is rejected, and every non-dependency TOML semantic must remain identical. The CI matrix installs the candidate `pyproject.toml` graph on Python 3.11-3.14 and `ci-gate` aggregates the behavioral, typing, security, packaging, mutation, OpenAI, and MCP evidence before merge.

Governance/recovery/workflow control-plane files, manual-review labels, stale PRs, and mixed-ecosystem diffs remain fail-closed. Dependabot uses native rebasing; governance does not call the update-branch API.

## Red-path recovery

Recovery has no merge authority. It can request at most one rerun (`maxRunAttempts == 2`) for the reviewed `CI` workflow, and only when exactly one non-aggregate leaf job and exactly one code-owned infrastructure/upload step fail with timestamp-bounded transient network/service evidence. Deterministic dependency-resolution, hash, policy, HTTP 4xx/rate-limit, permission, and disk failures override any transient-looking text and block recovery.

Tests, mutation scores, OpenAI/MCP behavioral lanes, package verification, security analysis, CodeQL, and `ci-gate` are never recovery targets. A second failed attempt remains red for manual investigation.

## Code scanning

`codeql.yml` runs Python CodeQL with `security-extended` queries on pull requests, `main`, a weekly schedule, and manual dispatch. External-fork pull requests do not receive write-capable code-scanning execution.
