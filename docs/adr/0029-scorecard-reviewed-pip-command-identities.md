# ADR 0029: Bind Scorecard pinned-install warnings by real workflow command identity

**Status:** Accepted; exact-head and post-merge qualification required.

## Context

OpenSSF Scorecard v5.5.0 recognized 23 genuine SARIF findings on accepted `main@f5fb5df246dbad6202bb16c07f6ebeb0ff718056`. Accepted PR #369 already enforces the 23-result per-rule upper-bound vector, including zero Fuzzing warnings after actual Atheris libFuzzer coverage (#367). However, a **different** new unpinned third-party installation could replace a previously observed local-source `PinnedDependenciesID` heuristic while the aggregate count remains at 18. A pure rule-count gate cannot detect such substitutions.

The preflight in issue #349 comment `6180926496` checked exact accepted main, only `main` branch, zero open PRs, all matching or superseded security/Scorecard branches merged with no unique unmerged capability. Prior accepted scanner classifier blob `39748020b1cdff418ae9635a424220c51069e7d0`; existing independent workflow pip-install policy blob `d667dd15376ae25cb96dd96ea27f3b04a471bf86`. Both remain authoritative in their respective narrow scopes and must be preserved.

The authentic [Scorecard run 38655091200](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38655091200), job 116162840782, completed success on that exact SHA; its original JSON SARIF contains three distinct runs, **23 actual findings** including 18 `PinnedDependenciesID`. The result source details identify the file `uri` and exact `region.snippet.text` for each pipCommand. There are **12 distinct reviewed path/command pairs** covering exactly 18 instances: `ci.yml` seven local source `.` plus one each local `dist/*.tar.gz` and retained `retained-dist/*.tar.gz`; eight other workflows each contain one local source `.` command; `publish-release.yml` contains one retained sdist. The reviewed local-only commands use `--no-deps --no-build-isolation` after separately hash-verified dependency installation. This is a source/detector-limited observation, **not a waiver or assertion that raw local hashes authenticate publishers**.

## Decision

Keep the 23-rule maximum vector from ADR 0028 and add a **second independent fail-closed maximum** over `(physicalLocation.artifactLocation.uri, physicalLocation.region.snippet.text)` specifically for `PinnedDependenciesID` findings. The exact observed command lines, grouped per workflow source location, are an explicitly reviewed inventory, with per-identity maximum multiplicities. The sum of these maxima must equal the separate `PinnedDependenciesID=18` rule maximum; unexpected/missing/malformed pip finding locations, unreviewed file paths or command text, and increased per-identity counts all fail, even if **total findings stay at 23**. Do not compare volatile line numbers; a legitimate move inside a file is not automatically an unreviewed new package acquisition.

Expand the built-in **and independent pytest** adversarial fixtures to cover genuine 18-member identity shapes, source-command replacement, new unreviewed workflow path, missing source evidence, same-category constant-count identity substitution, and growth across multiple SARIF runs. The existing original SARIF Code Scanning upload and retained separate classifier JSON remain unmodified; report only strict `FINDINGS_OPEN`, `NO_REPORTED_FINDINGS`, or `FAIL` with explicit non-claims. The structural workflow-owned pip-installer policy remains independent defense-in-depth and still rejects arbitrary unhashed remote acquisition.

## Consequences

- A new unreviewed Scorecard pipCommand finding replacing one known detector limitation cannot silently pass by keeping an aggregate 18-finding total.
- A genuine scanner-format or workflow-command change may correctly require review and an updated committed decision, rather than auto-waiving a different finding.
- Actual improvements decreasing a reviewed identity count remain allowed for human verification; no existing Code Scanning warning is dismissed or fabricated as fixed.
- No new external dependency, token scope, workflow trigger, administrator bypass, human approver simulation or privileged SARIF upload path is added.

## Assurance impact

This is independent **observation binding** from actual Scorecard SARIF, not trust delegated to a scanner's own self-declared configuration. The inspected command text does not confer installation authority: hash-only external dependency locks and exact checked-out/retained artifact validation remain separate accepted controls. No cryptographic hash alone authenticates the artifact publisher, and a successful classifier does not override the repository's non-compensatory or BLOCKED decisions.

## Non-claims

- The 18 known pinned-install warnings remain open; this PR is preventive regression hardening, not an OpenSSF detector fix or 18 remediation closures.
- The whole repository is not vulnerability-free because Scorecard logs remain 23 findings or because local Atheris fuzzing succeeded.
- Historical GitHub CodeQL app-name limitations, independent human review, fork PR E2E qualification, signed Dependabot E2E qualification, age-based maintenance eligibility and OpenSSF Best Practices enrollment remain unresolved under #349/#360.
- Never hide actual scanner results, broaden privileged workflow scopes or treat a `BLOCKED` admin observation as `PASS`.
