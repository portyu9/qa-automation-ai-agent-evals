# Security Policy

## Reporting a vulnerability

Please avoid putting secrets, credentials, private production payloads, access tokens, exploit-ready sensitive details, or personal data in a public issue.

If GitHub shows **Report a vulnerability** for this repository, use that private Security Advisory reporting path. If that option is not available, open a minimal public issue that states only that you need a private security-reporting channel; do not include the vulnerability details in that public issue.

Include, when safe to disclose privately:

- the affected commit/version and component;
- the security or assurance boundary involved;
- minimal reproduction steps or a small synthetic reproducer;
- the expected fail-closed behavior and the observed behavior;
- whether evidence integrity, authorization, approval, replay, release gating, credentials, or cross-tenant data may be affected.

## Scope and response principles

Security fixes must preserve the repository's evidence-bound trust model. In particular, a fix must not convert evaluator uncertainty into `PASS`, allow semantic judgment to rescue deterministic failure, or let an evaluated subject manufacture evaluator-owned evidence.

Changes that alter evidence/receipt parsing, canonical identities, authorization semantics, replay behavior, or release authority require explicit compatibility review. Historical evidence must not silently acquire new semantics under an existing schema identity.

The technical threat model, security boundaries, and explicit non-claims are maintained in [`docs/SECURITY.md`](../docs/SECURITY.md) and [`docs/LIMITATIONS.md`](../docs/LIMITATIONS.md).
