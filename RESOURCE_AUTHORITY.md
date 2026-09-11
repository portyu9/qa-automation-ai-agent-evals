# Typed Resource Authority

## Status

The repository now contains a **typed resource-algebra foundation** for a future authority-policy migration. This document describes that foundation only.

`AuthorityPolicy.allowed_resource_prefixes`, `HandoffAuthorityGrant.allowed_resource_prefixes`, `EffectiveAuthority`, and current policy grading still use their existing lexical string-prefix semantics until #197's migration slice lands. The presence of `ResourceIdentifier` / `ResourceScope` therefore does **not** widen current authorization claims or silently reinterpret existing scenarios.

## Version 1 resource grammar

`agent-evals/resource/v1` supports one resource kind: `hierarchical`.

A typed resource has:

- an exact schema version;
- an exact resource kind;
- a canonical lowercase ASCII `domain` identifying the evaluator-defined resource namespace;
- an ordered tuple of exact components.

A `ResourceIdentifier` requires at least one component. A `ResourceScope` may use an empty component tuple to explicitly mean the whole named domain.

Containment is structural, never lexical. A scope for components `("1",)` contains `("1", "orders")`, but not `("10", "orders")`, `("1-shadow",)`, or an otherwise identical path in another domain. Scope-to-scope attenuation uses the same tuple-prefix relation.

## Canonical component rules

Version 1 deliberately rejects ambiguous representations instead of guessing how to normalize them. Each component must:

- be non-empty and already NFC-normalized;
- have no leading or trailing whitespace;
- not be `.` or `..`;
- contain neither `/` nor `\\` because hierarchy is represented by the component tuple itself;
- contain no `%`, so encoded/double-encoded path aliases are not accepted;
- contain no Unicode `C*` category characters, including control, format/bidi-control, surrogate, private-use, and unassigned characters;
- remain within the bounded component-count and component-length limits.

Component comparison is exact and case-sensitive. The resource-domain grammar is deliberately narrower: lowercase ASCII letter first, followed by lowercase ASCII letters, digits, `_`, or `-`.

The model exposes deterministic canonical JSON suitable for later inclusion as behavior-bearing scenario identity material.

## Deliberate non-claims

Version 1 does **not** define canonical semantics for URLs, filesystem paths, Windows paths, cloud object keys, database identifiers, MCP URIs, host aliases, percent-encoded names, or provider-specific resource locators. Passing one of those syntaxes as a single hierarchical component fails closed when it contains a prohibited separator/encoding form; splitting an external identifier into components does not magically prove that the resulting hierarchy matches the external system's alias or authorization semantics.

A future resource kind must define its own canonicalization and containment rules explicitly before it can become authorization-bearing. Unknown resource kinds and unknown schema versions are rejected.

These types are evaluator contracts, not authentication, IAM credentials, capability tokens, or target-side enforcement attestations.

## Migration boundary

The next #197 slice must migrate root and delegated authority together. It must not leave root authorization typed while handoff attenuation remains lexical, or vice versa. That migration must also update resource-bearing evidence/adapters, tests, scenario identity semantics, and the existing lexical-resource nonclaims only after the runtime authorization path is structurally complete.
