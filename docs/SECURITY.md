# Security

## Security posture

The repository treats the evaluated agent and all provider/tool/MCP/memory/resource/handoff content as untrusted with respect to evaluation authority. Evidence may describe what happened; it may not redefine what is allowed or what counts as success.

The evaluation control plane is explicit about its own preconditions. An adversarial trial is not behaviorally gradeable until the controlled environment has produced one exact, internally valid delivery receipt for the attack bound to that scenario. Failure to establish that precondition is `BLOCKED` evaluation uncertainty, not an agent defect.

## Current deterministic controls

Implemented controls include:

- explicit tool allowlists/denylists, approval-before-use checks, resource-prefix confinement, and tool/handoff budgets;
- critical non-compensatory policy failure;
- provider/runtime failures classified as `RUNTIME_ERROR / BLOCKED`;
- controlled adapter-precondition failures classified separately as `EVALUATION_ERROR / BLOCKED`;
- immutable ordered evidence with domain-separated evidence roots;
- content-addressed adversarial fixtures and authority-preserving scenario derivation;
- evidence-bound delivery receipts binding exact scenario, attack, channel, injection point, and payload digest;
- exactly-one receipt verification before adversarial subject grading;
- fail-closed blocking for missing, duplicate, malformed, forged, or mismatched delivery evidence;
- raw attack-body exclusion from delivery receipts and evaluator delivery-error evidence;
- concrete OpenAI `USER_INPUT` delivery using exact canonical fixture JSON;
- concrete OpenAI local-`FunctionTool` `TOOL_RESULT` one-shot result replacement;
- concrete OpenAI local-`FunctionTool` description-level `TOOL_METADATA` poisoning;
- concrete OpenAI SDK session-history `MEMORY` poisoning using a fresh per-trial `Session`;
- concrete OpenAI structured inline-file `RESOURCE` poisoning using exact canonical fixture JSON as `input_file.file_data`;
- concrete OpenAI native `HANDOFF` context poisoning on the first SDK handoff while preserving destination;
- per-trial isolation through copied tools, cloned agents, fresh sessions, ephemeral structured run inputs, and fresh handoff filters;
- exact SDK call-ID binding for result injection;
- exact `ScriptedModel` observation of poisoned metadata, session history, structured inline-file resource, and handoff context;
- clean subsequent ordinary runs proving no metadata/memory/resource/handoff leakage into reusable subject state;
- exact historical replay of recorded delivery evidence without claiming fresh injection;
- bounded counterexample minimization;
- pinned GitHub Actions and read-only workflow permissions.

## Threat taxonomy

Stable identifiers cover direct/indirect prompt injection, tool poisoning, unauthorized tool use, privilege escalation, approval bypass, data exfiltration, cross-tenant leakage, memory poisoning/staleness, hallucinated actions/false success, runaway resource use, circular handoff, schema drift/malformed results, retry storms, sandbox escape, and MCP authorization failure.

The taxonomy is not mitigation by itself. The adversarial layer binds threat identifiers to deterministic scenarios; the delivery layer requires evidence that the trusted evaluation control plane reports successful injection before behavioral grading.

The OpenAI adapter now exercises six concrete surfaces: direct user input, indirect local tool-result content, local tool-description metadata, client-side SDK session history, structured inline-file resource input, and first-native-handoff transferred context. Generic environment state remains unsupported. Production application memory, hosted retrieval/vector stores, external resources, hosted tools, MCP surfaces, external registries/tool servers, and distributed handoff fabrics still require dedicated real-boundary infrastructure.

## Adversarial delivery boundary

`AttackDeliveryReceipt` is emitted only after a controlled injector reports that exact scenario attack placement occurred at a concrete injection point. It contains no raw attack body and binds exact scenario identity, attack identity, channel, injection point, canonical payload SHA-256, and a domain-separated receipt root.

`TrialRunner` requires exactly one valid `ATTACK_DELIVERY` event before deterministic subject oracles execute.

```text
unsupported/unavailable controlled injection → BLOCKED / evaluation uncertainty
provider/runtime unavailable                 → BLOCKED / runtime uncertainty
verified delivery + violated requirement     → FAIL / behavioral evidence
verified delivery + requirements satisfied   → PASS
```

Recorded receipts participate in ordinary evidence roots. Historical replay rechecks them but does not perform fresh injection.

## OpenAI `USER_INPUT` boundary

For `USER_INPUT`, the adapter supplies objective followed by exact canonical attack JSON as two ordered SDK user messages.

```text
source          = injector:openai-agents:user-input
injection_point = openai-agents:Runner.run.input[1]
```

This establishes the controlled SDK harness boundary, not proof that a remote hosted model processed or resisted the message.

## OpenAI local `TOOL_RESULT` boundary

The result injector targets **local SDK `FunctionTool` instances only**. The fixture requires `tool` and `result`; complete canonical fixture JSON becomes replacement output.

Per trial the target is copied and the agent cloned. On first matching invocation the original function is intentionally not executed, exact canonical attack JSON is returned, and receipt is bound to the SDK call ID.

```text
TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
```

This is controlled local result replacement, not hosted/MCP/remote-tool interception, and it does not preserve original side effects on the injected call.

## OpenAI local `TOOL_METADATA` boundary

The metadata injector targets the `description` of **one exact local SDK `FunctionTool` copy**. The fixture requires `tool` and `description`; complete canonical fixture JSON becomes copied description.

Tool name, parameter schema, callback, approval behavior, and routing identity remain unchanged. The deterministic SDK test observes exact poisoned description and later proves the reusable original remains unchanged.

This is not schema poisoning, hosted-tool metadata mutation, MCP discovery poisoning, external-registry poisoning, or provider-side metadata attestation.

## OpenAI SDK session-history `MEMORY` boundary

The memory injector targets **client-side SDK session history only**. A valid fixture requires `memory`; complete canonical fixture JSON becomes one prior `user` history item in a fresh per-trial SDK `Session` implementation.

```text
source          = injector:openai-agents:memory-session-history
injection_point = openai-agents:Session.get_items[0]
```

The deterministic SDK test proves exact poisoned history precedes current objective and a later ordinary run receives no inherited poison.

This does not claim application production-session mutation, provider-managed-conversation poisoning, vector/RAG memory manipulation, cross-user contamination, or provider-side persistence attestation.

## OpenAI structured inline-file `RESOURCE` boundary

The resource injector targets **one structured inline file in the SDK run input**. A valid fixture requires `resource`; complete canonical fixture JSON becomes exact `file_data` while the evaluator supplies fixed filename `agent-evals-resource.json`.

```text
input[0] = objective user message
input[1] = user message containing:
           type      = input_file
           file_data = exact canonical AttackFixture.payload_json
           filename  = agent-evals-resource.json
```

```text
source          = injector:openai-agents:resource-inline-file
injection_point = openai-agents:Runner.run.input[1].content[0]:input_file.file_data
```

The deterministic SDK test requires `ScriptedModel` to observe this exact structured file item, and a subsequent ordinary run must not contain it.

This boundary is intentionally narrow. It does **not** establish or claim:

- OpenAI hosted File Search or vector-store poisoning;
- RAG retrieval/ranking/chunking/embedding manipulation;
- provider-uploaded `file_id` mutation;
- remote `file_url` fetching or URL-resource manipulation;
- browser/web-page, database, object-store, or production document-repository interception;
- MCP/hosted-tool resource retrieval control;
- provider-side file parsing/processing attestation;
- target-side proof that a remote hosted model consumed the file bytes.

The adapter's separate `resource_resolver` callback is only a tool-request resource-identity normalizer used by policy evaluation. It is not this adversarial resource injector.

## OpenAI native `HANDOFF` boundary

The handoff injector targets **context transferred through the first actual OpenAI Agents SDK handoff in one trial**. A valid fixture requires `handoff`; canonical fixture JSON becomes one appended `user` item in cloned `HandoffInputData`.

```text
source          = injector:openai-agents:handoff-context
injection_point = openai-agents:RunConfig.handoff_input_filter:first:input_history[-1]
```

The SDK-selected target agent, handoff tool identity, and routing decision remain unchanged. Normalized evidence records `HANDOFF` followed by `ATTACK_DELIVERY`.

If no handoff occurs or the run-level filter is not invoked for the transfer, no receipt exists and the adversarial trial cannot pass delivery verification.

This does not claim destination rerouting, every-hop poisoning, remote/distributed agent-fabric interception, or external message-bus control.

## Delivery integrity is not attestation

A delivery receipt closes an evaluation-control gap but does not create a cryptographic trust anchor.

`injector:<identity>` is a control-plane label, not authenticated signer identity. `receipt_root` is domain-separated SHA-256 integrity, not a signature or MAC. A buggy or malicious trusted injector could still report delivery that did not occur without stronger independent acknowledgement/authentication.

## Evidence integrity is not authenticity

`evidence_root`, fixture/campaign hashes, and receipt roots detect content/identity changes relative to trusted inputs. They do not authenticate author, runner, or injector. Durable deployment provenance requires separate signer identity, trusted timestamps, retention, and tamper-resistant storage controls.

## Sensitive data

The deterministic core does not automatically upload traces or persist provider content. Delivery receipts store only canonical attack payload digest, not attack body.

Controlled injectors necessarily place raw canonical attack content into SDK user input, local tool result, copied tool description, isolated session history, structured inline file, or native handoff context because that content is the test stimulus. Subject/tool/session/resource/handoff observations still require normal minimization/redaction discipline.

## Deployment boundary

Application-layer policy cannot prove process isolation, network egress control, secret-manager policy, tenant separation, production IAM, sandbox containment, external MCP/tool fidelity, production memory-store isolation, hosted retrieval correctness, remote/distributed handoff correctness, or provider preservation/processing of controlled content after the tested SDK boundary. Those controls must be tested at actual enforcement boundaries.

## Current unsupported OpenAI attack channel

Only `ENVIRONMENT` remains unsupported by `OpenAIAgentsAdapter`. It precondition-blocks rather than silently degrading to another channel.

## Current verification checkpoint

The current source checkpoint is **167 passed, 9 deselected, 93.81% branch coverage**, strict mypy clean across **34 source files**, with **9/9** deterministic OpenAI SDK tests green. The channel-specific adversarial payload implementation is absent from the missing-coverage table at this checkpoint.

## Reporting vulnerabilities

Do not open a public issue containing credentials, private customer data, exploit secrets, or other sensitive material. Use GitHub private vulnerability reporting if enabled for the repository/account.
