# ADR 0027: Native Atheris fuzzing with honest Scorecard detector qualification

**Status:** Proposed; acceptance requires exact-head CI, real native campaign and post-merge Scorecard observation.

## Context

OpenSSF Scorecard v5.5.0, pinned in this repository to source revision `c395761df6afe1a69e476bc60a013a94bcbc153f`, detects built-in Python fuzzing from an actual `import atheris` in a Python source file. The existing thousands of Hypothesis property examples and optional MCP framing fuzz campaigns are valuable assurance evidence but are not recognized as an Atheris or OSS-Fuzz integration. Genuine 2026-10-14 accepted-main Scorecard SARIF on `73f4a01d8a12be10cff67603b7fc24a7f1639d1d` reported the Fuzzing warning, and PR #366 now retains an explicit `FINDINGS_OPEN` classification without suppressing it.

Pre-branch lineage and salvage is documented in issue #349 comment `6180069117`: accepted main `73f4a01d8a12be10cff67603b7fc24a7f1639d1d`, no competing open PRs, and existing merged fuzz/lock/security PRs #222/#264/#287/#288/#296/#350/#359/#365/#366 **already accepted**. No unique code remains on any divergent historical branch; preserve existing six canonical dependency locks and Hypothesis, MCP/OAuth and deterministic fuzz tests. This work uses only `security/atheris-coverage-fuzz-20261014`, branched after that preflight.

## Decision

Build a real Atheris/libFuzzer coverage-guided Python campaign against the evaluator-owned `strict_json_loads` trust boundary, with a checked-in adversarial seed corpus. Exercise exact-byte rejection, object-root consistency and lossless safe JSON serialization/canonical round trip for accepted finite values. Unexpected failures must reach the native engine; only evaluator-owned `StrictJsonError` is swallowed. Restrict mutation input size to 4096 bytes.

Add an **isolated optional fuzz tool lock** `requirements/locks/atheris-py314.txt` pinning **Atheris 3.1.0** with the exact Linux CPython 3.14 wheel SHA-256 `315a0b5c819852b1ffe1ca72efc389c7724881f2c33e4aacb8c6bcec49bd5011`. This is an independently audited distribution byte identity, not publisher authentication; PyPI lists Twine upload rather than Trusted Publishing. Atheris 3.1.0 provides Linux 3.14 wheels but does not list a 3.11 wheel; scope is **Ubuntu 24.04 x86-64/Python 3.14 only**, not all platform support or a new runtime package extra. The six established exact-hash developer/optional locks remain unchanged. The repository-owned lock validator retains the six-profile inventory and separately validates the one Atheris version and precise digest.

Run Atheris in its own least-privileged `deep-fuzz.yml` job (already scheduled, manually dispatchable and PR-triggered on relevant paths). Use an exact PR-head SHA or main commit, non-persisting checkout credentials and hash-verified installs for both the Python 3.14 core and Atheris. Use a bounded 5,000-mutation campaign with a 180-second timeout, 4,096-byte inputs and deterministic run-ID-derived libFuzzer seed (normalized to a signed 31-bit range). Retain the exact commit, seed, lock checksum, actual run log, mutated corpus and any reproducing crashes for 21 days, even after a failure. A timeout, crash, dependency failure, missing artifact or unexpected output must not become a PASS.

Strengthen the existing runtime policy to require the *actual* native job, its exact subject/seed, bounded invocation and evidence; reject `pull_request_target` and write authority. Add always-run unit oracle regressions which invoke the genuine target with fake instrumentation only for non-native unit coverage, explicitly not as a replacement for the Actions-run native engine.

## Consequences

- Expands genuine coverage-guided trust-boundary exploration beyond Hypothesis without removing established property tests or permissive package installation shortcuts.
- Uses one audited third-party binary wheel, adding bounded CPU/storage expenditure and a narrow Linux-specific native dependency. Wheel SHA-256 proves which bytes are consumed, not who created them.
- Existing Scorecard findings are not immediately closed. An actual merged-main Scorecard rescan must demonstrate the `FuzzingID` recognition change (and report what remains). A source marker alone is not a valid verification.
- Native fuzzer crashing or timing out is a hard failing result. The exact-head native workflow result and retained corpus/log decide whether this lane is qualified.

## Assurance impact

The fuzz target checks narrow JSON parsing invariants only. It cannot assert that all evaluator behavior is fuzzed, that MCP server/client framing and agent protocol semantics were fuzzed natively, or that vulnerabilities are absent. The isolation job has no write authority and runs untrusted PR code only under `contents:read`. Source-owned policy does not attest administrator settings or independent code review. No change is made to non-compensatory safety verdicts, BLOCKED classifications, release provenance or artifact authentication claims.

## Non-claims

- Merely detecting `import atheris` is **not** evidence that the coverage-guided campaign ran; require actual completed Actions steps and retained exact-head evidence.
- A passing bounded fuzz run is not proof of no bugs, all inputs covered or the absence of exploitable vulnerabilities.
- Passing Python 3.14 Linux wheel qualification does not imply Python 3.11 or macOS/Windows support.
- Hash-verified dependency identity is not a supply-chain signature or publisher authentication; the PyPI wheel has not been established as Trusted Published.
- Do not dismiss preexisting `FuzzingID` or any other Scorecard SARIF finding solely because this ADR was merged.
