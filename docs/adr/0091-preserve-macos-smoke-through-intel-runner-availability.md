# ADR 0091: Preserve macOS 26 smoke coverage through a supported Intel runner pool

**Status:** Accepted
**Date:** 2026-11-24
**Supersedes:** Only the macOS runner-label selection in the platform-smoke workflow. This does not supersede ADR 0090, the trust boundaries of the governance controller, the release-qualification contracts, or the deterministic cross-platform smoke requirements.

## Context

The accepted-main Platform smoke run #45441853642 on commit `443f6b10adea06f5a119280b52912516e5f91a61` completed Windows 2025/Python 3.14 successfully. Its macOS 26 job was never assigned a hosted runner, produced zero executed steps and no job log, and was cancelled after approximately fifteen minutes queued. A failed-job retry was requested but queued again with no steps at decision time. This is a GitHub-hosted runner acquisition failure, not evidence that the evaluation kernel failed on macOS.

GitHub documents the standard hosted `macos-26-intel` runner label. The contemporary GitHub Actions runner incident actions/runner#4833 also reports repeated macOS hosted-runner acquisition failures that terminate queued jobs before any test command starts. Continuing to require the capacity-affected `macos-26` ARM64 pool masks platform smoke results behind an upstream queue failure. The existing tests exercise platform-neutral JSON, oracle and evidence-store contracts, not a required Apple Silicon or ARM64 ABI.

## Decision

Retain macOS version 26, Python version 3.14, the exact hash-pinned dependency lock, immutable GitHub Action pins, workflow event triggers and the same deterministic kernel smoke tests. Change only the macOS smoke matrix runner from `macos-26` to the documented `macos-26-intel`, and name the matrix entry `macOS 26 Intel / Python 3.14`. Add a macOS-only runtime assertion requiring `platform.machine() == 'x86_64'` before dependencies or tests execute; fail closed if the hosted image does not match the intended architecture.

Keep Windows 2025/Python 3.14 unchanged. Do not silently mark queued or cancelled jobs as passing, skip macOS, downgrade Python or macOS, or expand token privileges. Each PR and merged-main commit still requires independent GitHub Actions platform smoke evidence.

## Consequences

The required macOS smoke runs in the supported Intel hosted runner pool rather than the capacity-affected ARM64 queue, without removing macOS platform coverage. Its architecture is now explicitly Intel, so **this ADR does not claim Apple Silicon / ARM64 coverage**. Future ARM64-specific compatibility assurance would require a separate governed workflow and runner-capacity/qualification strategy.

The infrastructure provider may still delay or cancel Intel jobs. There is no artificial success or merge bypass: these failures remain visible, and a PR stays unqualified unless its exact-head checks satisfy repository policy.

## Assurance impact

Pinning the platform label and asserting its architecture makes the intended operating system and runtime observable. The same platform-neutral tests and hash-checked Python dependencies remain the evidence contract on macOS and Windows; security, CodeQL, dependency review, package integrity, owner credential readiness, supply-chain attestations and CI gates remain unchanged.

The PR must pass Repository policy and the complete CI/security/CodeQL checks on its exact final head, including both platform smoke jobs. Following merge, the same platform smoke must run and pass on accepted main. A PR pass does not substitute for post-merge proof.

## Non-claims

- A hosted Intel runner is not guaranteed to be available indefinitely; this decision mitigates an observed queue failure, it does not guarantee GitHub Actions scheduling.
- An x86_64 macOS run is not a test of Apple Silicon, mobile iOS, GPU acceleration or native ARM64 binaries.
- A cancelled queued macOS job is not an application-test failure, security vulnerability, or evidence of successful execution.
- This decision does not repair or prove a live ignored Dependabot recreate, authorize unsigned dependency updates, or alter the governance controller's review identity.
- A passing CI or security workflow is not proof of zero open security alerts or completed GitHub administrator-only prerequisites.
