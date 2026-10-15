# ADR 0037: Prohibit regression of the cleared Scorecard pip installer warnings

**Status:** Accepted, contingent on protected exact-head and authentic postmerge Scorecard qualification.

## Context

Protected PR #377 merged at accepted main c134d3bd2c15d3d5213aa72b7c3be7f2b192a990. The genuine independent Scorecard workflow 38673527580, job 116221835112, uploaded complete unfiltered SARIF and retained it as artifact 11945232317. Its classifier reported five true SARIF findings versus the previous eight maximum, and no alerts suppressed. The three PinnedDependenciesID warnings on locally built and independently retained noneditable source distributions cleared after genuine SHA-256 pip hash installation, not after removing package tests. Earlier native fuzzing clearance remains real. The eight-finding ceiling is now outdated.

## Decision

Lower the exact scanner regression maximum to five, with zero PinnedDependenciesID and zero FuzzingID findings accepted. Delete the previously grandfathered three local-sdist pip command identity allowances so no retired source or newly introduced third-party command can replace one. Retain all other five existing rule ceilings with no exceptions. Preserve scanner identity, all expected Scorecard rules, per-run evidence structure, location validation, source snippets, fail-closed unknown-rule behavior and tamper-resistant failure reports. Add synthetic negative tests that reintroduce all historically cleared installer cases in a single or separate SARIF run. Do not change the upstream scanner or its original full SARIF output.

## Consequences

Any genuine future Scorecard scan that reports even one new pip or fuzzing finding fails the postmerge monitoring job and retains evidence, rather than declaring the posture acceptable. Genuine decreases in the five remaining governance/historical/external findings continue to be recorded without expanding any prior allowance. Required Package integrity and independent CodeQL/Security gates remain unchanged.

## Assurance impact

The five-finding ceiling is a narrow observational regression policy, not an authentication mechanism or independently qualified vulnerability audit. Original SHA-256 provenance, manifest/source/run integrity binding, tests of real wheel and sdist distributions, retained release Sigstore attestations and least-privilege CodeQL source analysis remain non-compensatory. The original Scorecard publisher still uploads unfiltered SARIF. The exact source commit and raw scanner artifact identity were established before branching under issue #349.

## Non-claims

Five SARIF posture warnings are not five proven exploitable vulnerabilities and are not direct proof of the current owner-only Code Scanning UI count. SHA-256 cannot authenticate a publisher. There is no fabricated human-independent code review, SAST app history, repo age, external Best Practices enrollment, fork validation or GitHub ruleset governance. BLOCKED, FAIL and PASS remain distinct. Issues #349 and #360 remain open until genuinely resolved.
