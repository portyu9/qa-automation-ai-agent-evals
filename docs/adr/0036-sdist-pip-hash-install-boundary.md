# ADR 0036 — Bind noneditable sdist smoke to manifest SHA-256 via pip hash mode

Status: proposed; requires exact-head CI and genuine postmerge Scorecard qualification.

## Decision

Preserve all built and independently retained noneditable sdist installations,
including the trusted release smoke. Do not use editable source, rewrite
SARIF, hide pip behind an opaque Python subprocess, or drop release tests.

After artifact build and deep metadata inspection, create the existing
canonical manifest *before* the first sdist test. Retained artifacts are
reverified against the manifest and CI run/source identity. For each of
the three sdist tests, use a dedicated manifest helper that re-verifies
the exact two-artifact set and expected producer context and writes an
exclusive, local-file-only pip requirement under RUNNER_TEMP with the
manifest's original SHA-256. Then use actual pip --require-hashes,
--no-deps and --no-build-isolation to install those exact bytes.

The workflow semantic policy admits this only at two audited CI locations
and one audited release location, with an immediately associated explicit
manifest-to-requirement producer. Prior reviewed third-party hash closures
and wheel tests remain unchanged. The runtime test proves the package
metadata, import, console CLI and doctor version, not mere scanner silence.

## Boundaries

SHA-256 checks integrity, not publisher identity; producer authority comes
from prior CI subject/run binding and, in the trusted release path, Sigstore
bundle and subject attestation checks. Dynamic lock files cannot prove that
the producing runner was not compromised. Real Scorecard recognition is
not assumed until verified from an independent accepted-main SARIF scan.
The five remaining branch-review/SAST/history/age/Best Practices warnings
have distinct causes. No code-scanning alert is dismissed or suppressed,
and neither BLOCKED nor FAIL is converted into PASS.
