# Typed Resource Authority

## Status

The repository uses a **typed, versioned resource algebra** for root authority, delegated handoff authority, resource-bearing policy evidence, and stronger approval-intent binding.

`AuthorityPolicy.allowed_resource_scopes`, `HandoffAuthorityGrant.allowed_resource_scopes`, and `EffectiveAuthority.allowed_resource_scopes` all use `ResourceScope`. Runtime resource authorization and handoff attenuation use the same structural containment relation. There is no `startswith` authorization fallback and no compatibility converter from legacy `allowed_resource_prefixes` strings.

Legacy lexical resource configuration is rejected by the typed contracts rather than silently translated. Resource-bearing `TOOL_REQUEST` and stronger `APPROVAL_REQUEST` evidence must carry the exact canonical JSON material of a `ResourceIdentifier`; raw resource strings and merely coercible Python representations fail closed.

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

The model exposes deterministic canonical JSON and typed resource authority is behavior-bearing scenario identity material.

## Evidence and adapter boundary

Canonical evidence uses all four explicit fields:

```json
{
  "schema_version": "agent-evals/resource/v1",
  "kind": "hierarchical",
  "domain": "tenant",
  "components": ["7", "orders", "42"]
}
```

The evidence parser requires that exact JSON shape. It rejects omitted default fields, extra fields, tuple-valued components, model instances, raw strings, and unsupported kind/version material. This keeps the wire representation explicit rather than relying on permissive model coercion.

Provider adapters do not infer resource semantics from URLs, paths, object keys, or arbitrary tool arguments. A configured resource resolver is responsible for explicitly mapping provider-observed invocation material to a `ResourceIdentifier`. Returning no identity for resource-scoped approval intent blocks that evaluation precondition; authorization is never manufactured from the external locator text.

## Approval binding and versioning

Stronger approval-intent receipts bind the exact typed `ResourceIdentifier` and use `agent-evals/approval-intent/v2` with a distinct domain-separated root. Historical v1 string-resource receipt material is not reinterpreted as v2 typed-resource material.

The receipt hash is an integrity binding over evaluator-defined material. It is **not** a signature, human-identity authentication, provider attestation, or proof that a human independently approved the action.

## Deliberate non-claims

Version 1 does **not** define canonical semantics for URLs, filesystem paths, Windows paths, cloud object keys, database identifiers, MCP URIs, host aliases, percent-encoded names, or provider-specific resource locators. Passing one of those syntaxes as a single hierarchical component fails closed when it contains a prohibited separator/encoding form; splitting an external identifier into components does not magically prove that the resulting hierarchy matches the external system's alias or authorization semantics.

A future resource kind must define its own canonicalization and containment rules explicitly before it can become authorization-bearing. Unknown resource kinds and unknown schema versions are rejected.

These types are evaluator contracts, not authentication, IAM credentials, capability tokens, target-side enforcement attestations, or proof that an external service uses the same namespace semantics.

## Migration boundary

The typed runtime migration intentionally changes behavior-bearing scenario identity: typed authority material, its schema version, domain, and components participate in canonical scenario identity. Existing lexical scenarios must be migrated deliberately; there is no mixed lexical/typed mode.

Adding a new external resource syntax still requires an explicit resource kind or explicit adapter-side mapping whose semantics are owned and tested by the evaluator. Extensibility must not become self-declared trust: an adapter cannot gain authority by inventing a resource kind, silently normalizing aliases, or falling back to string-prefix matching.