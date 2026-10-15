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
| #16 | Lock compiler `pip==25.3 pip-tools==7.5.2` | **Resolved with authentic acceptance:** merged PR #357 replaced the original un-hashed bootstrap with four reviewed transitive SHA-256 compiler locks; the temporary candidate workflow was removed before merge, accepted-main CI/CodeQL/Security/Scorecard passed, and this finding is absent from the latest real SARIF. Runtime CI locks remain separate. |
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
them globally. The CodeQL fork-PR skip was removed and protected by adversarial
semantic-policy tests in merged PR #361 / ADR 0021; analysis now uses
unprivileged `pull_request` with no PR SARIF upload and local zero-alert
enforcement. A **genuine external-fork PR end-to-end test** is still required
before directly requiring a CodeQL job on every possible fork PR; the
existing `Package integrity` bridge remains protected and fail-closed.

Require an independent human reviewer if a qualified second contributor is
available. An author cannot self-approve, and neither GitHub Actions nor an
AI bot is a substitute for that review; selecting an unsatisfiable rule could
deadlock maintenance.

Finally, verify the new PR's exact-head CI, dedicated Security and CodeQL
results and, after merge, the next *real* Scorecard SARIF run before treating
any alert as `fixed`. Reassess remaining alerts against current results;
do not dismiss them simply to reach a zero-alert badge.

## Verified 24-alert checkpoint and preventive PR control (14 October 2026)

The user-exported Code Scanning alert JSON lists **24 genuinely open**
Scorecard v5.5.0 alerts, all on accepted
`main@f519d90594d2d3cde107374632532a5065db98c3`:
**18 PinnedDependencies**, and one each **BranchProtection, CodeReview,
SAST, Fuzzing, Maintained, CIIBestPractices**. That agrees with the
independently parsed real SARIF from
[Scorecard run 38601137752](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38601137752).
These are distinct postures or detector limits, **not 24 proven vulnerabilities**.

The 18 highlighted pip commands test checked-out local source with
`--no-deps --no-build-isolation .`, or locally built/retained distributions
following committed hashes, artifact manifest/digest identity and
release-provenance checks. Their classification and exact source locations
are recorded in issue #349. The `--no-deps` flag prevents these commands
from downloading a new third-party dependency graph. Do not remove
these tests merely to create cosmetic zero-warning Scorecard output.

A distinct risk is **new third-party installer commands** accidentally
entering a pull request without SHA-256 enforcement. Focused PR #359 adds
a required CI Repository policy pre-merge installer inventory (with a
fail-closed negative self-test). Workflow `run` steps are parsed through
the existing reviewed semantic YAML parser. New third-party pip
installations must reference repository-reviewed hashed lock closures;
the narrow enumerated local source/artifact smoke exception is owned
by the validator, not declared by the untrusted workflow. This guard
prevents installer-regression merges; it does **not** dismiss existing
Scorecard alerts, audit source-code malware, replace independent CodeQL,
or pretend Scorecard itself is a pre-merge required check.

## Automation scope versus actual approval governance

The `dependency-governance.yml` scheduled/default-branch control
plane can retry **recognized transient CI infrastructure failures once**
and can rebase, inspect, programmatically owner-approve and merge only
canonical eligible Dependabot updates after exact-head CI/CodeQL proofs.
It signs into the configured owner identity with a **separate token**
when making those bounded owner-authorized review actions. This is
**not independent human review**; automated GitHub reviewer identity
must not be described as a second qualified maintainer.

At this **earlier** live snapshot, repository metadata reported
`allow_auto_merge=false` and `allow_update_branch=false`. This was
**superseded later on 2026-10-14**, as independently reverified in the
23-finding checkpoint below. These native GitHub settings are distinct
from the specialized Dependabot governance config's
`automergeEnabled=true` script setting. The live ruleset still requires
zero approvals, no stale-review dismissal and no last-push approval.
Changing those controls needs an authorized independent human reviewer
and repository administration; blindly enabling one approval for a
single-maintainer repo can deadlock otherwise safe PRs. Keep findings
#2 and #29 open until a genuine qualifying independent review history
and live ruleset check proves them resolved. General-purpose agent
autofixing of arbitrary Scorecard alerts is **not** implemented by
the bounded Dependabot recovery controller.

## Latest governance and security preconditions (2026-10-14)

The independent authentic Scorecard [main run 38619334215](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38619334215) was parsed from SARIF job `116042455263` on `main@6aec0e3a4e97e380b0a724fde790a4888f7fc9ac`. It has **24 genuine findings**: 18 `PinnedDependenciesID` checked-out source or independently verified retained release artifacts, one each `BranchProtectionID`, `CodeReviewID`, `SASTID`, `FuzzingID`, `MaintainedID`, `CIIBestPracticesID`. No `VulnerabilitiesID` finding. These are **not** 24 confirmed exploitable vulnerabilities, and none is dismissed or suppressed merely to make the UI green.

Actual native merge-only GitHub auto-merge is proven on protected, fully green PRs #362 and #363; this does **not** prove an independently reviewed signed Dependabot PR or a genuine external fork. The new live governance monitor on this accepted main returned a false violation because the unprivileged GitHub Actions API response omits the privileged `bypass_actors` field, even though a separate owner-connected ruleset read confirms no bypass actors. Paired PR #364 preserves the real distinction: missing admin field is **BLOCKED**, explicit unsafe actor is **FAIL**, observed required checks can still be independently **PASS**. A successful reporting workflow is not blanket assurance when its report contains BLOCKED.

A separate genuine PR dependency-review job 116035090773 found the GitHub dependency graph compare returned HTTP 403/404, so dependency review was **BLOCKED**. That status alone does **not** establish whether the graph is disabled or just inaccessible to the job token. Before PR #364 the committed governance JSON incorrectly declared dependency graph, secret scanning, and push protection all `verified-enabled` while the scanner JSON disagreed. Both sources now say **`unverified-admin-surface`** pending authenticated admin evidence; required CI tests prohibit promoting repository-owned declarations to self-authenticated claims. Private vulnerability reporting is **owner-reported enabled** but the connected administrator-only feature API is unavailable; do not mark it independently verified or claim a tested report URL without actual proof.

The user explicitly prefers single-CODEOWNER autonomous CI authority. A green bot reviewer or programmable owner-token `APPROVE` is **not independent human code review** and cannot meet the Scorecard `CodeReviewID` criterion. The repo is too young for Maintained's age-based assessment; OpenSSF Best Practices enrollment is external. Do not replace `BLOCKED` with `PASS`, untrustworthy self-attestations, fabricated historic fuzz/SAST runs, or fake zero-alert SARIF.

## Accepted-main 23-finding checkpoint: genuine native fuzz recognition (2026-10-14)

**Latest independently observed scanner evidence** is accepted
`main@973f8ee5167a7d66c4b884de8f356da21d8d67ed`, protected
[PR #367](https://github.com/portyu9/qa-automation-ai-agent-evals/pull/367)
and genuine [OpenSSF Scorecard run 38652619678](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38652619678),
job `116154802875`. The authentic OpenSSF Scorecard v5.5.0 SARIF reports
**23 actual security-posture findings** across all `runs` and `results`:

| SARIF rule | Actual findings | Current interpretation |
| --- | ---: | --- |
| `PinnedDependenciesID` | 18 | Existing local source/artifact `--no-deps` pipCommand heuristics remain; independently audited remote wheel and third-party installs are hash locked. |
| `BranchProtectionID` | 1 | Live ruleset still lacks independent required human approvals and related stale/last-push controls. |
| `CodeReviewID` | 1 | Native CI-authoritative autonomous merging is not independently qualified human code review. |
| `SASTID` | 1 | CodeQL genuine same-head scans succeed, but the upstream Scorecard historical checker still shows `0/30` recognized app-based checks. |
| `MaintainedID` | 1 | Repository age/activity scoring cannot be fabricated or accelerated by commits. |
| `CIIBestPracticesID` | 1 | Maintainer-controlled OpenSSF Best Practices enrollment and assessment remain unverified. |
| `FuzzingID` | **0** | **New actual Atheris/libFuzzer native Python campaign recognized by latest Scorecard SARIF.** |

The independent fail-closed classifier recorded
`Scorecard SARIF: FINDINGS_OPEN, real findings=23, baseline maxima=24; no alerts were suppressed`.
The original raw SARIF and separate triage JSON were retained as artifact
`11934932955`, `openssf-scorecard-38652619678`. This is a real one-finding
reduction from the previous **24-finding SARIF checkpoint**, not a
suppression, waiver, forged historic scan, or global claim of security.

**Qualification evidence:** PR #367's exact head
`e33d1742311096cc124c057083f99e8faee882d4`
passed real read-only `Deep fuzz assurance` for both the pre-existing
Hypothesis/MCP protocol campaign and a *new* Atheris 3.1.0 Python 3.14 Linux
coverage-guided campaign against the strict JSON trust boundary. The Atheris
job `116153915792` in
[run 38652271559](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38652271559)
shows native mutations/coverage feedback, `Done 5000 in 0 second(s)`,
`cov:71 ft:212` and retained exact-head corpus/crash/seed/log evidence
artifact `11934952498`. The third-party Atheris wheel was independently
pinned to its exact PyPI SHA-256; **hash does not authenticate the publisher**.
This coverage campaign does not imply no vulnerabilities or complete protocol
coverage. The new job imports checked-out source by `PYTHONPATH=src`
rather than introducing another unpinned local `pip install .` Scorecard
heuristic. Repository installer/permission/lock policies remain fail-closed.

**Code Scanning UI status is a separate observation:** the connected GitHub
app cannot read the `/code-scanning/alerts` REST endpoint. Therefore, while
the latest genuine SARIF has **no FuzzingID** result, the particular GitHub
Code Scanning alert's resolved/closed state has **not been independently
verified through the UI/API**. Inspect
[Security → Code scanning](https://github.com/portyu9/qa-automation-ai-agent-evals/security/code-scanning)
or use `gh api repos/portyu9/qa-automation-ai-agent-evals/code-scanning/alerts/28`
under maintainer permissions; do not manually dismiss it to improve a count.
Issue #349 remains open for the **23 reported findings**, independent from
the Code Scanning UI's possibly different open-alert count.

**Live setting update, superseding earlier snapshots:** a connected
read of repository metadata on 2026-10-14 independently confirmed
`allow_auto_merge=true`, `allow_update_branch=true`,
`allow_merge_commit=true`, `allow_squash_merge=false`, and
`allow_rebase_merge=false`. Protected PR #367 merged with the native
`MERGE` method only after all required CI/CodeQL/Security checks and both
fuzz campaigns succeeded. The optional deep-mutation job was **still
in progress at the merge decision**, so no independent success is claimed
for it at that checkpoint. Enabling the native setting is **not** broad
unconditional automatic approval of arbitrary PRs. Actual independent human
review, authenticated first eligible Dependabot lifecycle, fork PR end-to-end
tests and admin-only observability remain incomplete under #360.

This section updates the **live** evidence while preserving the old 30- and
24-finding baselines above as accurately dated historical snapshots.


## Accepted-main verified 8-finding Scorecard checkpoint — 15 local pip warnings removed (15 October 2026 UTC)

[PR #375](https://github.com/portyu9/qa-automation-ai-agent-evals/pull/375) (ADR 0034) merged through native main protection at `main@43cd171a2fec3ac6d3ae16d222a527ecef779887`, preserving the mandatory exact-head CI 38669393732, Security 38669393814, CodeQL 38669393761, Windows/macOS platform smoke 38669393813, free-threaded Python 38669393785, native Atheris/deep fuzz 38669393726, and deterministic performance 38669393811 as independently successful PR checks. The test lanes that import current **checked-out local source** now run `pip install --no-deps --no-build-isolation -e .` after full external SHA-256 locked dependency closure. Hatchling editable builds require only reviewed `dev-mode-dirs=["src"]` and no optional dynamically resolved package. Importantly, actual **noneditable** wheel and sdist build, install, import, CLI, reproducibility, manifest and retained release provenance tests were not replaced by editable installs.

The independent accepted-main [OpenSSF Scorecard run 38669640178](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38669640178), job `116209456072`, completed success with retained authentic artifact `openssf-scorecard-38669640178` (artifact ID `11942894954`). The unfiltered Scorecard SARIF was printed directly in the authentic job log and then classified with output **`Scorecard SARIF: FINDINGS_OPEN, real findings=8, baseline maxima=23; no alerts were suppressed`**. Exact remaining SARIF evidence is:

| SARIF rule | Genuine findings | Interpretation |
| --- | ---: | --- |
| `PinnedDependenciesID` | **3** | `ci.yml:701` built local `dist/*.tar.gz`, `ci.yml:786` independently verified `retained-dist/*.tar.gz`, `publish-release.yml:207` verified retained sdist. Preserve actual noneditable installs. |
| `BranchProtectionID` | 1 | Real zero independent required reviewers and missing stale/last-push protections in live ruleset. |
| `CodeReviewID` | 1 | No recognized independently approved changeset history; owner-token automation is not a separate human reviewer. |
| `SASTID` | 1 | Real CodeQL runs succeed, upstream historical scanner-app recognizer still 0/30. |
| `MaintainedID` | 1 | Repo under 90 days; cannot falsify age. |
| `CIIBestPracticesID` | 1 | Substantiated owner-enrolled external badge not yet proven. |
| **Total** | **8** | Neither zero vulnerabilities nor eight exploitable CVEs. |

The **15** earlier first-party local source `pipCommand` warnings were genuinely **absent** from the next SARIF, not suppressed, muted, converted into unrelated findings or dismissed. OpenSSF's current pip detector explicitly recognizes local source `--no-deps -e .` when its source is first-party; GitHub's actual Code Scanning open-alert list is a separate view this connected app cannot independently read.

The next separate baseline-hardening change pins `classify_scorecard_sarif.py` to the **newly observed** three audited sdist source-command identities and five unchanged categories (**8 total**, rather than obsolete 23) and adds a negative fixture for the now-resolved 15 source warnings. The scanner **still publishes original complete SARIF**, and any reintroduction will fail the security posture gate. Only after independent CI and another authentic main scan should that baseline hardening be called accepted.

Remaining hardening: preserve the full wheel+sdist tests when considering actual local sdist SHA-256 pinning, obtain human/admin governance and qualified external fork checks, await age eligibility, and enroll only in substantiated Best Practices criteria. Never conflate `BLOCKED` with `FAIL` or `PASS`, SHA-256 with authentication, and a signed Dependabot bot with independent human approval.
