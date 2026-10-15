# ADR 0036: Bind noneditable sdist smoke to manifest SHA-256 via pip hash mode

**Status:** Accepted, contingent on exact-head CI and genuine postmerge Scorecard qualification.

## Context

The authentic Scorecard SARIF on accepted main contains eight findings, including three `PinnedDependenciesID` warnings on tested built or retained source distributions. These are already reviewed, manifest-bound first-party artifacts, not remote third-party downloads. They still require a genuinely noneditable sdist installation to test package distributability. Existing pip commands lack **pip-enforced** SHA-256 verification at the final install boundary.

## Decision

Preserve all built and independently retained noneditable sdist installations, including trusted release smoke. Do not replace them with editable source, rewrite SARIF, hide pip behind an opaque Python subprocess, or drop release tests.

After source-based artifact build and detailed metadata inspection, create the existing canonical manifest before the first sdist test. Retained artifacts are independently reverified against this manifest and their producing CI commit/run identity. For each of three source distribution tests, use a dedicated manifest helper to re-verify the exact artifact bytes and expected source context, then write an exclusive, local-file-only pip requirement under `RUNNER_TEMP` with the **original manifest SHA-256**. Pip must enforce `--require-hashes --no-deps --no-build-isolation` while installing the noneditable archive.

The premerge policy admits this precise command only at two audited CI and one audited release locations with a same-step manifest-derived requirement producer. Reviewed third-party hash closures, wheel tests, native CodeQL and protected package gate remain unchanged.

## Consequences

Real install-time tampering of source-distribution bytes after the manifest is produced is rejected by `pip`, preserving metadata/import/CLI/doctor smoke and independent wheel/sdist reproducibility evidence. The original Scorecard publisher retains unfiltered authentic SARIF, and a future baseline lowering is contingent on observed accepted-main scanner results.

## Assurance impact

The additional pip hash is independently enforced against the already reviewed CI source/run artifact manifest. Source path/type, SHA-256 integrity, exact two-artifact inventory, producer identity, last-push source binding and retained release Sigstore attestation remain separate, non-compensatory requirements. Adversarial tests reject digest changes, commit mismatches, preexisting lock files and new unhashed installer commands. No security controls are relaxed to manufacture a badge.

## Non-claims

SHA-256 is not publisher authentication; a compromised trusted build runner could still produce untrustworthy bytes. The dynamic lock is not a signed independent authority. Real Scorecard recognition is not assumed until accepted-main SARIF is independently requalified. No GitHub Code Scanning alert is manually dismissed, no historical SAST/app reviewer evidence or project age is invented, and the five other governance/history/Best Practices issues remain open.