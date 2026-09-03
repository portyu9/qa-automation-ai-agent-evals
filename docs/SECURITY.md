# Security

## Security posture

The repository treats the evaluated agent and all provider/tool/MCP content as untrusted with respect to evaluation authority. Evidence may describe what happened; it may not redefine what is allowed or what counts as success.

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
- immutable evidence objects with ordered-sequence validation;
- hash-chain evidence root binding trajectory and terminal state;
- content-addressed adversarial fixtures with canonical finite JSON payloads;
- deterministic adversarial scenario derivation that preserves the base objective, outcomes, and exact authority policy;
- reserved attack-envelope validation and optional full derived-scenario rederivation against an expected base;
- canonical adversarial campaigns with duplicate-attack rejection and base-scenario drift detection;
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

The taxonomy is not itself mitigation. The implemented adversarial layer can bind these threat identifiers to deterministic attack fixtures and derive exact security scenarios, but **scenario generation is not attack delivery**. An adapter or controlled evaluation environment must actually inject the declared stimulus at the relevant boundary and expose observable evidence that the ordinary policy/outcome oracles can grade.

See [Adversarial Testing](ADVERSARIAL_TESTING.md).

## Adversarial fixture boundary

`AttackFixture` is intentionally provider-neutral. It records the attack identity, threat class, delivery channel, payload, revision, and tags. `AttackFixture.apply()` augments a base scenario through a reserved state envelope while preserving the base authority contract.

Supported channel identities currently include user input, tool results, tool metadata, memory, resources, handoffs, and other controlled environment state. These labels tell an evaluation environment **where** a stimulus belongs; they do not claim that the repository has a universal injector for each channel.

When the original base scenario is available, `extract_attack(..., expected_base_scenario=...)` verifies the embedded base identity and rederives the complete adversarial scenario. This prevents a manipulated derived scenario from passing merely because its attack envelope is internally well formed.

## Evidence integrity is not authenticity

`evidence_root` is a cryptographic content digest. It detects changes in normalized event order/content and terminal metadata. It is **not** a signature, attestation, or independent identity proof.

Likewise, adversarial fixture/campaign hashes are content identities. They do not authenticate who authored an attack pack or prove that a target environment delivered it.

A stronger durable artifact layer must separately address provenance, signer/runner identity, retention, and tamper-resistant storage.

## Sensitive data

The deterministic core does not automatically upload traces or persist provider content. Provider adapters must default to data minimization and must document whether prompts, tool arguments/results, user data, secrets, attack payloads, or model content can enter traces.

No adapter or red-team environment should treat observability as permission to retain secrets.

## Deployment boundary

Application-layer policy cannot prove process isolation, network egress control, secret-manager policy, tenant separation, production IAM, sandbox containment, or that an external MCP/tool server faithfully injected a requested adversarial condition. Those remain deployment/infrastructure or test-environment controls and must be tested at their actual enforcement boundary.

## Reporting vulnerabilities

Do not open a public issue containing credentials, private customer data, exploit secrets, or other sensitive material. Use GitHub's private vulnerability-reporting mechanism if enabled for the repository/account.
