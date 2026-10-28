# ADR 0072: Accept immutable PyPI publisher pin refresh with unchanged release-channel annotation

**Status:** Accepted
**Date:** 2026-10-28
**Authority boundary:** Native signed Dependabot `dependabot[bot]` workflows-only action-pin updates, already reviewed by exact-Git-SHA CI, CodeQL, security, semantic workflow, release/SBOM and protected merge gates.

## Context

Signed Dependabot PR #425, exact head `f55ca6a978f746b9ddb369e1a6acf8ebbf5baacb`, updates six upstream Actions in 18 workflow files. Its first native Repository policy job fails even though the source contains only pinned `uses:` SHA changes. The semantic ADR validator `.github/scripts/validate_semantic_adr.py` supports SHA-only action references and conventional `# vX.Y.Z` version comments, but the isolated protected PyPI OIDC publisher already uses a legitimate stable provenance annotation `# release/v1 2026-07-28` on `pypa/gh-action-pypi-publish@<40-hex-SHA>`. That existing comment remains unchanged when only its release-pinned commit is advanced. The current parser rejects the line and propagates an irrelevant ADR requirement into `ci-gate` and `Package integrity`. The approved ADR 0070 already admits isolated PyPI publisher action updates at the runtime-policy boundary.

## Decision

Recognize the preexisting literal form `# release/v1 YYYY-MM-DD` as an annotation **only** on `pypa/gh-action-pypi-publish`. Parse it separately from numeric semver, never infer release-version order from the annotation. Require the previous and proposed annotation to match exactly, the same publisher action identity, a changed 40-character immutable SHA, and a one-for-one modification in an already-existing workflow. All other actions retain the exact previous `# vX.Y.Z`/SHA-only rules; all non-action lines, changed release annotations, foreign publishers, mixed/renamed files, and new powers require normal human-authored, appended ADR governance.

## Consequences

The legitimate native bot can be recognized as a pinned SHA-only release change and proceed to genuine security and CI validation without a hand-authored compensating release branch, suppressing tests, fabricating checks, editing the bot branch or relaxing required reviews. The separate signed release-provenance verification and immutable action pin certification stay mandatory. This is not permission to merge on the parser decision alone.

## Assurance impact

The embedded fail-closed self-test exercises native publisher SHA updates, equal frozen release annotation, prior/adversarial unchanged SHA, foreign action identity, changed annotation date, changed format, appended arbitrary workflow code, and malformed multi-file diff. It also retains every existing negative ADR/action version test. The test must run successfully under the exact PR source on the protected native CI and policy lanes. The original native signed #425 branch and its 18 changed workflows remain untouched.

## Non-claims

This repair does not certify the six new action versions, eliminate legitimate security findings, exempt untrusted authors, grant permission to weaken the PyPI isolated OIDC publisher, or constitute an unattended complete bot merge. The original signed bot head still requires fresh native first-attempt required checks, an appropriate independent merge decision and normal branch protections. End-to-end verification requires the native Dependabot PR to merge autonomously in a later independently observed controller run.

## Lineage

Preflight is recorded on the live native #425 comment `6458955475`: accepted main `23a2eb09627752737e7550538b71ca85e5a719f8`, Git tree `a8c8cca6e8d386f51cb1ff27027418d926b9e583`, parents `1822ef4b14190067580177969b238df40a1cf4e3` and `c47f669c7a24327ded331e0224434d2771f5f866`. Historical #423/#424 already accepted, superseded #417/#422 classified, no other orphan branch or uniquely salvageable PR. The original scanner/semantic validator Git blob `94cb86cdced8fc2ab9c49519a12dd8a2de3e7005` is the sole functional source change.
