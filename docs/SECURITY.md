# Security

## Security posture

The repository treats the evaluated agent and all provider/tool/MCP content as untrusted with respect to evaluation authority. Evidence may describe what happened; it may not redefine what is allowed or what counts as success.

The evaluation control plane is explicit about its own preconditions. An adversarial trial is not behaviorally gradeable until the controlled environment has produced one exact, internally valid delivery receipt for the attack bound to that scenario. Failure to establish that precondition is `BLOCKED` evaluation uncertainty, not an agent defect.

## Current deterministic controls

Implemented controls include:

- explicit tool allowlists/denylists and approval-before-use checks;
- resource-prefix confinement and tool/handoff budgets;
- critical non-compensatory policy failure;
- provider/runtime failures classified as `RUNTIME_ERROR / BLOCKED`;
- controlled adapter-precondition failures classified separately as `EVALUATION_ERROR / BLOCKED`;
- immutable ordered evidence with domain-separated evidence roots;
- content-addressed adversarial fixtures and authority-preserving scenario derivation;
- reserved attack-envelope verification and canonical campaigns;
- evidence-bound delivery receipts binding exact scenario, attack, channel, injection point, and payload digest;
- exactly-one receipt verification before adversarial subject grading;
- fail-closed blocking for missing, duplicate, malformed, forged, or mismatched delivery evidence;
- raw attack-body exclusion from delivery receipts and evaluator delivery-error evidence;
- concrete OpenAI `USER_INPUT` delivery using exact canonical fixture JSON;
- concrete OpenAI local-`FunctionTool` `TOOL_RESULT` delivery using exact canonical fixture JSON as a one-shot first-result replacement;
- concrete OpenAI local-`FunctionTool` `TOOL_METADATA` description poisoning using exact canonical fixture JSON;
- one shared fail-closed local-tool resolver for result and metadata attacks;
- per-trial copy/clone isolation so reusable original agent/tool objects are not mutated;
- exact SDK call-ID binding and request → delivery → result chronology for result injection;
- exact copied-description observation through the deterministic SDK model-call tool snapshot for metadata injection;
- fail-closed target validation for malformed, missing, unsupported, ambiguous, or unbindable local-tool attack targets;
- exact historical replay of recorded delivery evidence without claiming fresh injection;
- bounded counterexample minimization;
- pinned GitHub Actions and read-only workflow permissions.

## Threat taxonomy

Stable identifiers cover direct/indirect prompt injection, tool poisoning, unauthorized tool use, privilege escalation, approval bypass, data exfiltration, cross-tenant leakage, memory poisoning/staleness, hallucinated actions/false success, runaway resource use, circular handoff, schema drift/malformed results, retry storms, sandbox escape, and MCP authorization failure.

The taxonomy is not mitigation by itself. The adversarial layer binds threat identifiers to deterministic scenarios; the delivery layer requires evidence that the trusted evaluation control plane reports successful injection before behavioral grading.

The OpenAI adapter now exercises three concrete surfaces: direct user input, indirect content returned by a targeted local `FunctionTool`, and poisoned description metadata on a targeted copied local `FunctionTool`. Memory, resources, handoffs, environment state, hosted tools, external registries/tool servers, and MCP surfaces still require dedicated real-boundary infrastructure.

See [Adversarial Testing](ADVERSARIAL_TESTING.md).

## Adversarial fixture boundary

`AttackFixture` records identity, threat class, delivery channel, canonical payload, revision, and tags. Applying it augments a base scenario through a reserved envelope while preserving the base authority contract.

Channel labels identify where a stimulus belongs; they do not claim universal injector coverage. `extract_attack(..., expected_base_scenario=...)` can rederive the complete adversarial scenario and detect drift outside the envelope.

## Adversarial delivery boundary

`AttackDeliveryReceipt` is emitted only after a controlled injector reports that the exact scenario attack was placed at a concrete injection point. It contains no raw attack body and binds exact scenario identity, attack identity, channel, injection point, canonical payload SHA-256, and a domain-separated receipt root.

`TrialRunner` requires exactly one valid `ATTACK_DELIVERY` event before deterministic subject oracles execute.

```text
unsupported/unavailable controlled injection → BLOCKED / evaluation uncertainty
provider/runtime unavailable                 → BLOCKED / runtime uncertainty
verified delivery + violated requirement     → FAIL / behavioral evidence
verified delivery + requirements satisfied   → PASS
```

Recorded receipts participate in the ordinary evidence root. Historical replay rechecks them but does not perform fresh injection.

## OpenAI `USER_INPUT` boundary

For `USER_INPUT`, `OpenAIAgentsAdapter` sends:

```text
input[0] = scenario objective
input[1] = exact canonical AttackFixture.payload_json
```

The receipt identifies `openai-agents:Runner.run.input[1]` and source `injector:openai-agents:user-input`. Deterministic SDK tests assert the exact normalized input.

This stops at the controlled SDK harness boundary. It does not prove that a remote hosted model processed or resisted the message.

## OpenAI local-`FunctionTool` `TOOL_RESULT` boundary

The current tool-result injector deliberately targets **local SDK `FunctionTool` instances only**.

The identity-bearing attack payload must contain a valid `tool` and `result`. The full canonical fixture JSON is returned as replacement output so the receipt payload digest binds the exact model-visible replacement bytes.

Per adversarial execution the adapter copies only the targeted function tool, wraps the copy, and clones the agent with a fresh tools list. The reusable original agent/tool are not modified.

On the first matching invocation:

- the SDK `tool_call_id` is captured;
- the original target function is intentionally **not executed**;
- exact canonical attack JSON becomes the returned tool result;
- the receipt uses source `injector:openai-agents:tool-result` and an injection point containing exact tool name and call ID;
- normalized evidence orders `TOOL_REQUEST`, then `ATTACK_DELIVERY`, then the matching `TOOL_RESULT`.

Subsequent matching calls in that trial use the copied original behavior.

This is controlled **result replacement**, not an assertion that the real underlying service emitted malicious content. It is especially suitable for read/retrieval fault simulation and does not preserve original function side effects on the injected first call.

If the target never executes, no receipt exists and delivery verification blocks the trial. Missing/ambiguous/non-function targets and malformed routing contracts precondition-block before a false test can run.

The implementation does not intercept hosted tools, MCP tools, remote tool servers, or arbitrary non-`FunctionTool` implementations.

## OpenAI local-`FunctionTool` `TOOL_METADATA` boundary

The metadata injector targets the `description` of **one exact local SDK `FunctionTool` copy**.

The identity-bearing fixture requires `tool` and `description`. The complete canonical fixture JSON becomes the copied `FunctionTool.description`, which keeps the existing receipt payload digest bound to the exact model-visible metadata string.

Per adversarial execution the adapter:

- resolves one exact local `FunctionTool` with the same fail-closed resolver used by result injection;
- copies the target;
- replaces only the copied description;
- clones the agent with a fresh tool list;
- emits a receipt from `injector:openai-agents:tool-metadata` at `openai-agents:FunctionTool:<tool>:description`;
- leaves the original agent/tool unchanged.

The deterministic SDK test observes the exact poisoned description in `ScriptedModel`'s model-call tool snapshot and then proves a later ordinary run still sees the original description.

The v1 boundary intentionally does **not** change the tool name, parameter schema, callback, approval behavior, or routing identity. This prevents a description-poisoning test from silently becoming a schema/routing mutation test.

Therefore this implementation does not claim:

- parameter-schema poisoning;
- tool renaming or route manipulation;
- hosted-tool metadata mutation;
- MCP tool/server discovery poisoning;
- external registry/tool-server metadata poisoning;
- provider wire-format attestation;
- proof that a remote hosted model processed or preserved the poisoned description unchanged.

## Delivery integrity is not attestation

A delivery receipt closes an evaluation-control gap but does not create a cryptographic trust anchor.

`injector:<identity>` is a control-plane label, not authenticated signer identity. `receipt_root` is domain-separated SHA-256 integrity, not a signature or MAC. A buggy or malicious trusted injector could still report delivery that did not occur unless a stronger independent acknowledgement/authentication boundary is added.

## Evidence integrity is not authenticity

`evidence_root`, fixture/campaign hashes, and receipt roots detect content/identity changes relative to trusted inputs. They do not authenticate the author, runner, or injector.

A stronger durable artifact layer must separately address provenance, signer identity, trusted timestamps, retention, and tamper-resistant storage.

## Sensitive data

The deterministic core does not automatically upload traces or persist provider content. Delivery receipts store only the canonical attack payload digest, not the attack body.

The OpenAI controlled injectors necessarily place raw canonical attack content into in-memory SDK user input, a local tool result, or a copied local tool description because that content is the stimulus under test. Other subject/tool observations can still contain sensitive data and require normal minimization/redaction discipline.

No adapter or red-team environment should treat observability as permission to retain secrets.

## Deployment boundary

Application-layer policy cannot prove process isolation, network egress control, secret-manager policy, tenant separation, production IAM, sandbox containment, faithful behavior of an external MCP/tool server, or provider preservation of controlled metadata/results after the tested SDK boundary. Those controls must be tested at their actual enforcement boundaries.

## Current verification checkpoint

The current source checkpoint is **155 passed, 6 deselected, 93.67% branch coverage**, strict mypy clean across **34 source files**, with **6/6** deterministic OpenAI SDK tests green. The channel-specific adversarial payload implementation is absent from the missing-coverage table at this checkpoint.

## Reporting vulnerabilities

Do not open a public issue containing credentials, private customer data, exploit secrets, or other sensitive material. Use GitHub's private vulnerability-reporting mechanism if enabled for the repository/account.
