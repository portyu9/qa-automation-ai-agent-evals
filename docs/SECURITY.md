# Security

## Security posture

The repository treats the evaluated agent and all provider/tool/MCP content as untrusted with respect to evaluation authority. Evidence may describe what happened; it may not redefine what is allowed or what counts as success.

The evaluation control plane is also explicit about **its own preconditions**. An adversarial trial is not behaviorally gradeable until the controlled environment has produced one exact, internally valid delivery receipt for the attack bound to that scenario. Failure to establish that precondition is evaluation uncertainty (`BLOCKED`), not an agent defect.

## Current deterministic controls

Implemented controls include:

- explicit tool allowlists and denylists;
- approval-before-use checks for privileged tools;
- resource-prefix confinement;
- tool-call and handoff budgets;
- explicit policy-violation evidence;
- critical classification of policy-oracle failure;
- non-compensatory release gating;
- provider/runtime exceptions converted to `BLOCKED` rather than accepted;
- structured adapter-precondition failures separated from provider/runtime failures and converted to `EVALUATION_ERROR / BLOCKED`;
- immutable evidence objects with ordered-sequence validation;
- hash-chain evidence root binding trajectory and terminal state;
- content-addressed adversarial fixtures with canonical finite JSON payloads;
- deterministic adversarial scenario derivation that preserves the base objective, outcomes, and exact authority policy;
- reserved attack-envelope validation and optional full derived-scenario rederivation against an expected base;
- canonical adversarial campaigns with duplicate-attack rejection and base-scenario drift detection;
- evidence-bound attack-delivery receipts binding exact scenario, attack, channel, injection point, and payload digest;
- exact-one delivery-receipt validation before adversarial policy/outcome grading;
- fail-closed `BLOCKED` semantics for missing, duplicate, malformed, or mismatched delivery evidence;
- raw adversarial payload exclusion from delivery receipts and evaluator delivery-error evidence;
- one concrete OpenAI Agents SDK `USER_INPUT` injector that places the exact canonical attack payload at a tested `Runner.run` input position and emits the corresponding receipt;
- fail-closed precondition blocking for unsupported OpenAI adversarial channels before model execution;
- exact historical replay of recorded delivery evidence without claiming fresh injection;
- bounded counterexample minimization;
- pinned GitHub Actions and read-only workflow permissions.

## Threat taxonomy

The current code defines stable identifiers for:

- direct and indirect prompt injection;
- tool poisoning;
- unauthorized tool use;
- privilege escalation;
- approval bypass;
- data exfiltration;
- cross-tenant leakage;
- memory poisoning and stale memory;
- hallucinated actions and false success;
- runaway resource use;
- circular handoff;
- schema drift and malformed tool results;
- retry storms;
- sandbox escape;
- MCP authorization failure.

The taxonomy is not itself mitigation. The implemented adversarial layer binds these threat identifiers to deterministic attack fixtures and exact security scenarios. The delivery layer then requires evidence that the trusted evaluation control plane reports successful injection before behavioral grading begins.

The OpenAI adapter provides one concrete delivery implementation for direct `USER_INPUT` stimuli. Threats that require tool-result, metadata, memory, resource, handoff, MCP, or environment manipulation still require dedicated delivery infrastructure at those real boundaries.

See [Adversarial Testing](ADVERSARIAL_TESTING.md).

## Adversarial fixture boundary

`AttackFixture` is intentionally provider-neutral. It records the attack identity, threat class, delivery channel, payload, revision, and tags. `AttackFixture.apply()` augments a base scenario through a reserved state envelope while preserving the base authority contract.

Supported channel identities currently include user input, tool results, tool metadata, memory, resources, handoffs, and other controlled environment state. These labels tell an evaluation environment **where** a stimulus belongs; they do not claim that the repository has a universal injector for each channel.

When the original base scenario is available, `extract_attack(..., expected_base_scenario=...)` verifies the embedded base identity and rederives the complete adversarial scenario. This prevents a manipulated derived scenario from passing merely because its attack envelope is internally well formed.

## Adversarial delivery boundary

`AttackDeliveryReceipt` is emitted only after a controlled injector reports that the scenario's exact attack was placed at a concrete injection point. The receipt contains no raw attack body. It binds:

- exact derived scenario identity;
- exact attack identity;
- declared attack channel;
- injection point;
- SHA-256 of the canonical attack payload;
- a domain-separated receipt root.

The normalized evidence source must use `injector:<identity>`. `TrialRunner` requires exactly one valid `ATTACK_DELIVERY` event for an adversarial scenario before it invokes deterministic subject oracles.

If delivery evidence is absent, duplicated, malformed, has an invalid source label, has a forged root, or belongs to another scenario/attack/channel/payload, the evaluator appends a critical `EVALUATION_ERROR` and returns `BLOCKED` with no completed oracle results.

That distinction prevents evaluator defects from being mislabeled as subject defects:

```text
unsupported controlled injection → BLOCKED / evaluation uncertainty
provider/runtime unavailable     → BLOCKED / runtime uncertainty
verified delivery + violated requirement → FAIL / behavioral evidence
verified delivery + requirements satisfied → PASS
```

The recorded receipt participates in the ordinary trial evidence root. Exact historical replay therefore rechecks the recorded receipt, but does not perform a fresh injection.

## OpenAI `USER_INPUT` boundary

For a derived OpenAI `USER_INPUT` adversarial scenario, `OpenAIAgentsAdapter` constructs two ordered user messages for `Runner.run`:

```text
input[0] = scenario objective
input[1] = exact canonical AttackFixture.payload_json
```

The matching receipt identifies `openai-agents:Runner.run.input[1]` as the injection point and uses source `injector:openai-agents:user-input`. The independent deterministic SDK test asserts that exact input reaches `ScriptedModel` and that unsupported channels do not invoke the model at all.

This is a useful control-plane guarantee, but it stops at the SDK harness boundary. It does not prove that a remote hosted model processed the message, that a provider preserved it unchanged after that boundary, or that the model resisted the attack. Credentialed live-provider behavior remains a separate test tier.

## Delivery integrity is not attestation

The delivery receipt closes an important evaluation-control gap, but it does not create a cryptographic trust anchor.

The `injector:<identity>` source is a control-plane label, not authenticated signer identity. `receipt_root` is an ordinary domain-separated SHA-256 content identity, not a signature or MAC. The framework verifies consistency relative to the trusted evaluator's recorded observation; it does not independently prove that an arbitrary external target consumed the payload.

A buggy or malicious trusted injector could report delivery that did not occur. Stronger deployments may require authenticated injector identities, target-side acknowledgements, trusted timestamps, remote attestation, or equivalent independent evidence.

## Evidence integrity is not authenticity

`evidence_root` is a cryptographic content digest. It detects changes in normalized event order/content and terminal metadata. It is **not** a signature, attestation, or independent identity proof.

Likewise, adversarial fixture/campaign hashes and delivery receipt roots are content identities. They do not authenticate who authored an attack pack or who performed an injection.

A stronger durable artifact layer must separately address provenance, signer/runner identity, retention, and tamper-resistant storage.

## Sensitive data

The deterministic core does not automatically upload traces or persist provider content. Provider adapters must default to data minimization and must document whether prompts, tool arguments/results, user data, secrets, attack payloads, or model content can enter traces.

Delivery receipts intentionally persist only the canonical attack payload digest, not the attack payload itself. The OpenAI injector necessarily places the raw canonical attack payload into the in-memory SDK input because that is the stimulus under test; the receipt does not duplicate it into delivery evidence. Other evidence produced by the subject or its tools can still contain sensitive data and requires normal minimization/redaction discipline.

No adapter or red-team environment should treat observability as permission to retain secrets.

## Deployment boundary

Application-layer policy cannot prove process isolation, network egress control, secret-manager policy, tenant separation, production IAM, sandbox containment, or that an external MCP/tool server faithfully injected and delivered a requested adversarial condition to its real consumer. Those remain deployment/infrastructure or test-environment controls and must be tested at their actual enforcement boundary.

## Reporting vulnerabilities

Do not open a public issue containing credentials, private customer data, exploit secrets, or other sensitive material. Use GitHub's private vulnerability-reporting mechanism if enabled for the repository/account.
