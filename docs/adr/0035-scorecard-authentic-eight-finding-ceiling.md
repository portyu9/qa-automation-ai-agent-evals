# ADR 0035: Fail closed against reintroduction of cleared Scorecard findings

**Status:** Accepted, contingent on exact-PR and independent accepted-main Scorecard qualification.

## Context

The default-branch [OpenSSF Scorecard run 38669640178](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38669640178), job `116209456072`, emitted its original unfiltered SARIF from accepted `main@43cd171a2fec3ac6d3ae16d222a527ecef779887`. The full source text is retained in authentic job logs and archive `11942894954`. Its checker output is **`Scorecard SARIF: FINDINGS_OPEN, real findings=8, baseline maxima=23; no alerts were suppressed`**. All 15 previously reported first-party local-source pip installs stopped triggering `PinnedDependenciesID` after verified [PR #375](https://github.com/portyu9/qa-automation-ai-agent-evals/pull/375)/ADR 0034 changed these to genuinely dependency-free editable exact-checkout source installs. The three remaining pip warnings are the *noneditable* built or retained sdist smoke tests (`ci.yml`: `dist/*.tar.gz`, `ci.yml`: `retained-dist/*.tar.gz`, `publish-release.yml`: `retained-dist/*.tar.gz`). Five other genuine Scorecard findings are `BranchProtectionID`, `CodeReviewID`, `SASTID`, `MaintainedID`, and `CIIBestPracticesID`. Fuzzing is zero after independent native Atheris qualification.

The independent semantic SARIF posture classifier `.github/scripts/classify_scorecard_sarif.py` still allowed **up to 18** `PinnedDependenciesID` warnings and **up to 23** total findings, including the now-disappeared 15 source-test command identities. That safety ceiling was appropriate for earlier real evidence but now too permissive: a regression to the old source-install warning inventory could be reported `FINDINGS_OPEN` without tripping CI. This would lose the security assurance of the authentic 15-finding improvement.

Pre-branch lineage-and-salvage preflight in [issue #349 comment 6182881387](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/349#issuecomment-6182881387) verified main, zero competing PRs or divergence, and all prior Scorecard, Atheris, trusted CodeQL publisher and exact-subject security controls accepted. Exact relevant source blob IDs are recorded. No unique historical lane capability was stranded.

## Decision

Ratchet the classifier's `PinnedDependenciesID` maximum from 18 to **3** (the exact noneditable sdist warning locations) and the genuine total posture baseline from 23 to **8**. Remove the old 15 local-source warning identities from the allowlist completely, without disabling, filtering or dismissing the original scanner SARIF. Bind this new baseline to the exact accepted main commit `43cd171a2fec3ac6d3ae16d222a527ecef779887`, not a fabricated historical Scorecard result.

Keep the raw SARIF model strict: require declared scanner rules (including cleared categories), authentic Scorecard driver/version, parse complete results across every run, reject unknown findings or increased counts, validate exactly one source path/snippet for each remaining pip warning, and reject any new or swapped pip command even when total stays at eight. Add direct adversarial fixtures for reintroducing a cleared local `pip install .` warning at an old source path, increasing `PinnedDependenciesID` to four, replacing an existing sdist warning with an arbitrary third-party pip command, repeated identity, malformed SARIF, and new `FuzzingID` (which must stay zero). Genuine decreasing results stay eligible for further ratcheting.

## Consequences

The continuous Scorecard SARIF workflow remains independent of PR-authored scanner claims and keeps publishing **the full original scanner evidence**. Its classification now fails if any of the 15 genuinely cleared first-party warnings recur. Its three sdist warnings remain real and are not incorrectly labelled resolved. A later independently proven reduction of the three must be followed by a **separate** baseline shrink only after a real postmerge scanner result.

This change does not alter any current workflow tokens, direct native GitHub ruleset checks, independent CodeQL/Security protected job verdicts, signed Dependabot bot controls, genuine wheel or source distribution installation, artifact digest, retained Sigstore/OIDC evidence, Windows/macOS platform smoke, deep fuzz or source coverage. It preserves **honest** scanner non-claims and avoids masking regressions behind an outdated alert ceiling.

## Assurance impact

The posture regression gate is now synchronized to verifiable, unfiltered, authentic accepted-main Scorecard evidence. Future CI fails on recurrence of an already corrected class rather than silently accepting its original inventory.

## Non-claims

- This is **not** a claim that GitHub's Code Scanning alert UI already shows eight open findings; the connected GitHub integration cannot query the restricted alerts endpoint. The eight count comes from authentic raw SARIF and its independent classifier.
- The remaining three local noneditable sdist warnings are not three proven exploitable supply-chain vulnerabilities. Any future local archive hash-pinning must keep genuine wheel/sdist install, hash provenance, manifest and release smoke tests intact.
- Neither a clean CodeQL run nor a reduced Scorecard count proves zero vulnerabilities. Hashes bind artifact identity, not publication authority. Bot owner approval is not an independent qualified human reviewer. `BLOCKED` is never flattened into `FAIL` or `PASS`.
- The five separate governance, SAST historic app recognition, age and OpenSSF Best Practices prerequisites remain open under #349/#360. Never close their issues by changing the expected warning limit.
