# Live Provider Assurance and Adapter Conformance

## Purpose

The framework separates deterministic adapter conformance from credentialed live-provider observation.

Ordinary pull requests and deterministic CI prove repository-owned contracts without network credentials. A separate scheduled/manual live canary can make a bounded historical observation against a configured provider. Neither path gives provider output grading authority, and neither path lets a third-party adapter declare itself a trusted producer of evaluator-owned evidence.

## Evaluator-owned adapter conformance

The core evaluator applies an evaluator-owned conformance check to every normalized adapter result before evidence conversion. The check validates:

- an exact `AdapterResult`;
- exact `EvidenceEvent` instances with contiguous zero-based sequence values;
- an exact terminal-state object;
- bounded output shape;
- finite non-negative elapsed time, token counts, and estimated cost.

Adapter identity remains the original runtime object throughout execution, drift detection, error provenance, and producer-authority checks. Invalid or hostile adapter names continue to fail through the existing bounded metric-provenance boundary rather than creating a second competing identity path.

A conformance failure is mapped into the evaluator's established invalid-adapter-result precondition and therefore resolves to `BLOCKED`, never subject `FAIL`.

Conformance is not producer authorization. The core evaluator still checks the original adapter by exact type for evaluator-owned `ATTACK_DELIVERY`, retrieval, approval, side-effect, and MCP protocol evidence. A subclass, matching class name, matching source string, structurally valid result, or conformance pass cannot manufacture that authority.

This design keeps extensibility separate from trust:

```text
implements AgentAdapter + passes structural conformance
    = eligible to provide ordinary normalized subject observations

passes structural conformance
    != authorized producer of evaluator-owned evidence
```

## Distinct JSON runtime adapter

`JsonHttpRuntimeAdapter` is a second runtime boundary distinct from the OpenAI Agents SDK adapter. Its transport receives a bounded request containing the exact trial, subject, scenario, objective, and turn-limit identities.

The remote response may supply only terminal output/state and non-authoritative token/cost telemetry. It cannot supply framework `EvidenceEvent` objects or choose evaluator-owned evidence kinds or source strings. Unexpected response fields fail closed before grading.

When public provider/runtime interfaces expose them, the adapter may retain bounded request identifiers and model-revision labels in a framework-created `OUTPUT` event. Those labels are diagnostic metadata. They are not authenticated provider identity, model attestation, or signing evidence.

A non-successful transport result becomes adapter uncertainty (`BLOCKED`), not a behavioral failure.

## Credentialed live-provider canary

`.github/workflows/live-provider-canary.yml` is deliberately separate from ordinary CI. It runs only:

- on an explicit manual dispatch; or
- on its weekly schedule.

There is no `pull_request` or ordinary `push` trigger. The job has read-only repository permission and no OIDC, attestation, or repository-write authority.

The current canary uses the provider's public HTTP API through `.github/scripts/run_live_provider_canary.py`. Credentials come only from the GitHub secret environment. The script does not print the credential.

The executable ceilings are intentionally small:

| Boundary | Default ceiling |
|---|---:|
| Attempts | 3 |
| Request timeout | 15 seconds |
| Total wall clock | 45 seconds |
| Request rate | 6/minute |
| Input tokens | 256 |
| Output tokens | 32 |
| Total estimated cost across all attempts | $0.01 |

The cost preflight uses an operator/repository-supplied price snapshot. It multiplies the maximum per-request token cost by the maximum attempt count, so a retry-capable configuration whose worst-case total bounded usage would exceed the canary cost ceiling is rejected before any provider request. Runtime observations also accumulate validated usage/cost across retries and fail closed if the total ceiling is exceeded. The resulting cost value is an estimate under that configured price snapshot, not a provider bill or authenticated pricing claim.

## Retry and verdict classification

Live observations have three explicit dispositions:

| Disposition | Meaning |
|---|---|
| `observed` | A structurally valid successful provider response satisfied the predeclared canary assertion. |
| `subject_failure` | A structurally valid successful provider response was observed but violated the predeclared behavioral assertion. |
| `provider_uncertain` | The provider/runtime relation could not be resolved safely: retryable service failure, timeout, malformed response, bounded-usage violation, or another provider/transport uncertainty. |

HTTP 429 and selected 5xx responses are retried only within the attempt/rate/wall-clock limits. Timeouts follow the same bounded retry policy. A retry delay that would consume the remaining wall-clock budget fails closed as provider uncertainty.

This distinction is intentional:

```text
provider unavailable / throttled / malformed / timed out
    = provider_uncertain
    != subject_failure

valid successful response that violates declared canary assertion
    = subject_failure
```

## Retained metadata and artifacts

Where the public interface exposes them, the observation retains:

- provider request identifier;
- provider model/revision label;
- cumulative observed input/output token counts across validated attempts;
- cumulative configured-price estimated cost across validated attempts;
- attempt count and disposition.

The workflow retains the canonical JSON observation as `live-provider-canary-<run_id>` for 14 days. The schema explicitly records:

- `historical_observation: true`
- `provider_attestation: false`

The artifact is therefore a record of what the repository observed in one bounded run. It is not automatically promoted into release authority, a provider attestation, or a framework-signed truth claim.

## Deterministic testing without credentials

All conformance rules, the JSON runtime adapter, retry classification, rate/cost/wall-clock policy, malformed-response behavior, and non-attestation semantics are tested deterministically without live credentials.

The credentialed workflow is an additional observation tier. It is not required to determine whether an ordinary pull request is structurally correct.

## Non-claims

This layer does not establish:

- authenticated provider or model identity from a request ID or model string;
- provider-side execution provenance or non-repudiation;
- a trusted provider timestamp;
- SLA or general availability guarantees;
- universal correctness across models, regions, accounts, or future provider revisions;
- independent token accounting or billing correctness;
- freshness/correctness of an operator-supplied price snapshot;
- external side-effect truth unless another evidence contract observes that boundary;
- automatic release acceptance from a live canary result;
- authorization for third-party adapters to emit evaluator-owned evidence;
- retroactive authentication of historical live observations.

A future deployment may separately authenticate a retained live observation, but that would be a distinct trust relation and must not be inferred from this canary artifact itself.

[← Documentation hub](README.md)
