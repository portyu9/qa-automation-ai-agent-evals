# Security Policy

## Reporting a vulnerability

Please avoid putting secrets, credentials, private production payloads, access tokens, exploit-ready sensitive details, or personal data in a public issue.

Use [GitHub's private vulnerability reporting page](https://github.com/portyu9/qa-automation-ai-agent-evals/security/advisories/new) if private reporting is enabled for this repository. If GitHub does not offer a private report form, open a minimal public issue asking the maintainer to establish a private reporting channel; **never include vulnerability details, credentials, exploit steps, or sensitive production evidence in the public issue**. The public issue is only a contact request, not a vulnerability disclosure.

Include, when safe to disclose privately:

- the affected commit/version and component;
- the security or assurance boundary involved;
- minimal reproduction steps or a small synthetic reproducer;
- the expected fail-closed behavior and the observed behavior;
- whether evidence integrity, authorization, approval, replay, release gating, credentials, or cross-tenant data may be affected.

## Coordinated disclosure and response

Please allow a target of **90 days** for coordinated disclosure after the initial private report. The reporter and maintainer should agree on the actual public disclosure date, especially if downstream users need more time to patch. This target is guidance, **not a guaranteed remediation SLA**; urgent active-exploitation reports should be escalated as quickly as possible. Do not publish sensitive reproduction material before coordination.

A maintainer should acknowledge the report when practical, privately triage impact and reproducibility, document any affected versions, and publish a fix or mitigation with appropriate release notes before coordinating a public advisory. If the finding is not actionable, explain the determination privately rather than silently dismissing it. Public GitHub issues and pull requests are not an appropriate channel for secret vulnerability details.

## Scope and response principles

Security fixes must preserve the repository's evidence-bound trust model. In particular, a fix must not convert evaluator uncertainty into `PASS`, allow semantic judgment to rescue deterministic failure, or let an evaluated subject manufacture evaluator-owned evidence.

Changes that alter evidence/receipt parsing, canonical identities, authorization semantics, replay behavior, or release authority require explicit compatibility review. Historical evidence must not silently acquire new semantics under an existing schema identity.

The technical threat model, security boundaries, and explicit non-claims are maintained in [`docs/SECURITY.md`](../docs/SECURITY.md) and [`docs/LIMITATIONS.md`](../docs/LIMITATIONS.md).
