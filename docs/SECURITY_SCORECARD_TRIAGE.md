# OpenSSF Scorecard: finding triage and PR-gate authority

Baseline evidence: 30 open Scorecard code-scanning alerts on accepted `main` commit
`fcabb60826dd43d95e66311d5cf3cb55e87a19a2` (14 October 2026).
This inventory is a **snapshot**, not a claim that the alerts are closed. The
Scorecard SARIF severities describe supply-chain posture checks; they do **not**
prove 30 independently exploitable vulnerabilities. A clean CodeQL or pip-audit
result also cannot prove that repository governance is secure.

## Confirmed scope and next actions

| Alerts | Finding | Triage and required action |
| --- | --- | --- |
| #26 | Release publisher workflow-wide `contents: write` | Fixed in this PR: workflow defaults to `contents: read`, and only the trusted main publication job requests `contents: write`. Verify release publication before closing. |
| #23–25 | Trusted lock/Dependabot governance writers | The verified artifact publisher needs repository writes; the default-branch-only governance job needs bounded PR/recovery operations. Least-privilege scopes and provenance require ongoing review. The semantic workflow policy guards approved write capabilities, but it cannot make these inherently privileged operations read-only. |
| #4–15, #17–22 | Scorecard `pipCommand not pinned by hash` | Inspect each call. Reported commands install the **checked-out local source** or locally produced and reverified release distributions with `--no-deps`; remote dependency installs use committed `--require-hashes` locks. Do not disable local package smoke tests just to improve a heuristic. Retain these as detector-limited findings until upstream recognizes verified local packages or a fully equivalent installation strategy is validated. |
| #16 | Lock compiler `pip==25.3 pip-tools==7.5.2` | **Genuine gap:** version pins are not artifact hashes. Convert the maintenance compiler bootstrap to a fully hash-checked transitive, per-platform input before closing; do not claim existing release locks cover this compiler. |
| #27 | Scorecard SAST historical-commit coverage | CodeQL Python/Actions `security-extended` runs on PRs/main with a zero-SARIF-result test; Scorecard reports zero of its previous 30 commits checked. Verify live tool uploads/status history. Require the `CodeQL` status before merging. Historical coverage cannot be retroactively invented. |
| #28 | Unrecognized fuzzing | The project already uses dedicated `deep-fuzz.yml` / Hypothesis tests on security-critical boundaries; Scorecard's language/integration detector does not recognize this Python setup. Preserve actual fuzzing; integrate a Scorecard-recognized option only if appropriate and tested, not for cosmetic scoring. |
| #3 | Security policy missing linked private-report channel | This PR adds the GitHub private-reporting link and coordinated disclosure target to `.github/SECURITY.md`. Confirm private vulnerability reporting is enabled before claiming end-to-end availability. |
| #2, #29 | Main branch reviews/protection | Active ruleset requires **zero** human approvals and only seven CI statuses. Repository owner must require `CodeQL` and `security-gate` from GitHub Actions, at least one independent human approval, last-push approval, and stale-review dismissal where sustainable. No bot review counts as an independent human review. |
| #30 | Repository younger than 90 days | Cannot legitimately remediate with code or artificial commit history. Reassess once the project is old enough and verify genuine ongoing maintenance. |
| #31 | OpenSSF Best Practices registration | Maintainer needs to register and substantiate criteria at https://www.bestpractices.dev/; do not claim a badge without review. |

## Actual merge enforcement versus monitoring

The `Protect Main` ruleset previously required `Quality / Python 3.11`,
`Quality / Python 3.14`, three MCP checks, `OpenAI adapter / deterministic SDK`,
and `Package integrity`, but **not directly** `CodeQL` or `security-gate`. Importantly, the required `Package integrity` check already calls `verify_required_codeql.py` and requires exact-subject CodeQL workflow success; directly requiring the `CodeQL` context would be defense in depth. Its
required approving review count was zero. Those are GitHub-hosted ruleset
settings; editing a YAML file does not change them.

The existing `CI` policy job already runs the semantic workflow validator,
and both required Quality jobs depend on it. This PR extends that pre-merge
gate to reject workflow-level write authority and unreviewed job-level
capability escalation, with narrow validator-owned exceptions for accepted
trusted-only publication, provenance, and security analysis paths. This is a
regression guard, **not** an assertion that every previously reported alert
is resolved or that Scorecard itself runs as a required PR check.

The follow-up monitoring decision changes Scorecard to publish real SARIF after
every accepted `main` push, or on its weekly schedule/manual invocation; it
still never executes untrusted PR code with SARIF write authority.
Do not grant `security-events: write` to untrusted Scorecard PR code in an
attempt to fabricate a merge gate. Continue retaining CodeQL zero-alert
qualifications, Bandit/pip-audit, actionlint/zizmor, dependency-review and
fail-closed dependency precondition checks.

## Administrator follow-through

In GitHub **Settings → Rules → Rulesets → Protect Main**, preserve the existing
required checks and consider adding `CodeQL` (defense in depth, already indirectly gated by `Package integrity`) and `security-gate` as *required* checks
from GitHub Actions. Configure **Require code scanning results** for CodeQL
at an appropriate vulnerability threshold when supported. Make sure those
checks execute on all eligible PRs, including fork PRs, before requiring
them globally. The current CodeQL job intentionally skips untrusted forks;
its event/permission design needs a verified read-only analysis path before
forked PRs can satisfy a mandatory CodeQL requirement.

Require an independent human reviewer if a qualified second contributor is
available. An author cannot self-approve, and neither GitHub Actions nor an
AI bot is a substitute for that review; selecting an unsatisfiable rule could
deadlock maintenance.

Finally, verify the new PR's exact-head CI, dedicated Security and CodeQL
results and, after merge, the next *real* Scorecard SARIF run before treating
any alert as `fixed`. Reassess remaining alerts against current results;
do not dismiss them simply to reach a zero-alert badge.
