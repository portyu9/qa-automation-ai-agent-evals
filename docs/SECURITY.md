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

The taxonomy is not itself mitigation. Scenario packs and dedicated oracles must operationalize each threat before the repository can claim test coverage for that class.

## Evidence integrity is not authenticity

`evidence_root` is a cryptographic content digest. It detects changes in normalized event order/content and terminal metadata. It is **not** a signature, attestation, or independent identity proof.

A future durable artifact layer must separately address provenance, signer/runner identity, retention, and tamper-resistant storage.

## Sensitive data

The deterministic core does not automatically upload traces or persist provider content. Provider adapters added later must default to data minimization and must document whether prompts, tool arguments/results, user data, secrets, or model content can enter traces.

No adapter should treat observability as permission to retain secrets.

## Deployment boundary

Application-layer policy cannot prove process isolation, network egress control, secret-manager policy, tenant separation, production IAM, or sandbox containment. Those remain deployment/infrastructure controls and must be tested at their actual enforcement boundary.

## Reporting vulnerabilities

Do not open a public issue containing credentials, private customer data, exploit secrets, or other sensitive material. Use GitHub's private vulnerability-reporting mechanism if enabled for the repository/account.
