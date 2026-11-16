# ADR 0088: Retire credentialed live provider canary from credential-free QA automation

**Status:** Accepted
**Date:** 2026-11-16
**Supersedes:** The enabled credentialed provider-canary workflow and its associated assumptions of required provider credentials in earlier live-provider documentation. This decision also supersedes the out-of-scope credential-provisioning suggestions in the non-claims of ADR 0085 and ADR 0087, without modifying those append-only historical records.

## Context

The approved purpose of the AI Agent Evals repository is automated, deterministic, credential-free evaluation and assurance. Real paid provider access, provider API keys, live model selection, and pricing configuration were intentionally excluded from scope. A prior scheduled/manual `live-provider-canary.yml` nonetheless attempted weekly HTTP access through `run_live_provider_canary.py`, reading `OPENAI_API_KEY` and canary model/pricing variables.

The scheduled run 43941665069 on 2026-11-16 failed before any provider request because those credentials were absent by design; artifact upload then failed because no observation file was created. Issue #447 incorrectly described this as an operator provisioning blocker. The user explicitly reaffirmed that no credentials should ever have been required and instructed removal of failures attributable to this out-of-scope tier. A silent success/no-op workaround would preserve an unauthorized workflow and could reintroduce provider calls later if someone created a secret.

The same repository contains `src/agent_evals/live_provider.py` and offline unit tests for a bounded injected-transport observation model. That reusable deterministic test seam contains no active HTTP provider runner and exercises meaningful uncertainty and non-attestation contracts. It is valuable assurance logic and must not be discarded.

## Decision

**Remove the credentialed GitHub Actions workflow** `.github/workflows/live-provider-canary.yml` and **remove its network-capable execution entry point** `.github/scripts/run_live_provider_canary.py`. Do not introduce secrets, placeholder keys, fake model responses, skipped jobs, false green statuses, or a new live provider trigger.

Retain `src/agent_evals/live_provider.py` and the deterministic offline `tests/unit/test_live_provider_canary.py`. Their results demonstrate test-seam behavior only, not a live provider observation. Rework the previous live-workflow policy tests to enforce the *absence* of the retired entry points and to reject any active GitHub workflow containing the named provider credential, canary parameter family, retired runner reference, or previously configured public responses endpoint.

Make the existing required `.github/scripts/validate_runtime_policy.py` fail closed on these same forbidden workflow/runner conditions so the absence of provider credentials is enforced as a repository contract during PR and post-merge CI, rather than relying on a passing but disabled optional scheduled workflow.

Update `docs/LIVE_PROVIDER_ASSURANCE.md` to state the correct scope and classify offline test observations without misrepresenting a real provider integration. Explicitly retract issue #447 as not planned; provider secret or billing setup is **not** a user action item. Historical failed GitHub Actions records remain visible as immutable history but the deleted workflow cannot schedule future runs.

## Consequences

Future ordinary CI continues to test bounded provider-like retries, token/cost accounting, failure classification and evaluator authority offline without provider keys or billing. The recurring Monday scheduled failure is eliminated at its source. Should a future change attempt to restore the old workflow or embed the same live provider key/runner into any workflow, the runtime policy and unit regression tests fail before merge.

A future request to enable credentialed provider access requires an explicit separate scope decision, governance approval and a new append-only ADR. It cannot be inferred from residual deterministic test types or historical language in accepted ADRs.

## Assurance impact

The removed network runner cannot generate historical live artifacts or consume provider billing. Existing mandatory CI, CodeQL, Security, signed Dependabot provenance, package-integrity and release gates remain unchanged. The new negative policy assertions run in CI on every exact PR head and on accepted `main`; this is stronger and more durable than skipping a job whenever a secret is missing.

The retained pure model continues to make separate `observed`, `subject_failure`, and `provider_uncertain` decisions over injected test transport, without creating model authority, authenticated provenance, or provider attestation. No offline success may substitute for a required independent security signal.

## Non-claims

- This decision does not claim GitHub can delete historical failed Actions runs or retroactively change their conclusions.
- It does not request, install, or permit provider credentials, model identifiers, paid calls, or pricing snapshots in repository automation.
- It does not abolish deterministic OpenAI adapter tests, MCP tests, or valid local protocol simulation.
- It does not relax native GitHub automation authentication, CI/CodeQL/Security, package-integrity, or release-authority controls.
- It does not automatically remediate unrelated failures, such as a separate platform-smoke runner failure or a stale Dependabot branch.
