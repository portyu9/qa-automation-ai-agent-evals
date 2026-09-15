# Property-based assurance boundary

The repository uses Hypothesis to generate bounded deterministic examples for pure trust kernels. Property tests complement example regressions; they do not replace schema validation, adversarial fixtures, state-machine testing, mutation testing, fuzzing, golden vectors, or live-provider observation.

## Covered invariants

The property suite exercises the following current invariants:

- subject fingerprints, event digests, and evidence roots are invariant to JSON object insertion order where object order is not semantic;
- trial evidence roots bind the trial identity;
- canonical typed resource evidence round-trips through the strict resource parser;
- merely equivalent Python representations that are not canonical resource JSON fail closed rather than being silently coerced;
- hierarchical resource authorization is component-prefix aware, domain aware, and transitive across generated scopes and identifiers;
- scenario/authority identity is invariant to insertion order of semantically unordered tool, tag, and resource-scope material after contract canonicalization;
- representative attack-delivery, semantic-judgment, retrieval-delivery, and side-effect receipt roots are invariant to JSON object insertion order;
- those receipt domains remain distinct when hashing the same canonical material.

Generated JSON and resource material is intentionally small, finite, local, and below the evaluator's current resource ceilings. Hypothesis wall-clock deadlines are disabled so runner speed does not become assurance authority. Example counts remain bounded so shrinking can produce small counterexamples suitable for permanent regression fixtures.

## Authority and nonclaims

These tests assert deterministic framework invariants only. They do not grant trust to generated inputs, receipts, adapters, models, or providers. A hash or receipt root remains an integrity identity, not authentication, signature, attestation, or proof of remote enforcement.

Generated scope tests do not widen authorization semantics: exact typed domains and whole structural components remain authoritative. Generated receipt-root tests do not prove cryptographic collision resistance. Sampling many Hypothesis cases is not exhaustive formal verification.

This suite also does not reinterpret evaluator outcomes. `BLOCKED` and `INCONCLUSIVE` remain distinct from subject `FAIL`, deterministic safety failures remain non-compensatory, and property tests do not become release authority by themselves.

## Separate roadmap work

The following remain intentionally separate hardening domains:

- state-machine transition assurance for temporal protocols and approval/resume flows;
- mutation testing and trust-kernel mutation score gates;
- malformed-byte/protocol/OAuth fuzzing;
- independent-reference differential tests;
- fixed golden digest/root vectors and language-neutral conformance corpora;
- corrupted persisted-evidence corpora;
- scheduled stress and wall-clock performance regression testing.

Keeping these domains separate prevents broad "property tested" claims from hiding what has and has not actually been established.
