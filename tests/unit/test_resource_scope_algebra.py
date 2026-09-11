from __future__ import annotations

import json

import pytest
from hypothesis import given, settings, strategies
from pydantic import ValidationError

from agent_evals.contracts.resource import ResourceIdentifier, ResourceKind, ResourceScope


_VALID_COMPONENT = strategies.text(
    alphabet=strategies.sampled_from(tuple("abcdefghijklmnopqrstuvwxyz0123456789_-")),
    min_size=1,
    max_size=24,
)
_VALID_DOMAIN = strategies.from_regex(r"[a-z][a-z0-9_-]{0,15}", fullmatch=True)


def test_scope_uses_component_boundaries_not_lexical_prefixes() -> None:
    scope = ResourceScope(domain="tenant", components=("1",))

    assert scope.contains_identifier(
        ResourceIdentifier(domain="tenant", components=("1", "orders", "42"))
    )
    assert not scope.contains_identifier(
        ResourceIdentifier(domain="tenant", components=("10", "orders", "42"))
    )
    assert not scope.contains_identifier(
        ResourceIdentifier(domain="tenant", components=("1-shadow",))
    )


def test_scope_containment_is_structural_and_domain_bound() -> None:
    parent = ResourceScope(domain="tenant", components=("7", "orders"))

    assert parent.contains_scope(ResourceScope(domain="tenant", components=("7", "orders")))
    assert parent.contains_scope(
        ResourceScope(domain="tenant", components=("7", "orders", "open"))
    )
    assert not parent.contains_scope(ResourceScope(domain="tenant", components=("7",)))
    assert not parent.contains_scope(
        ResourceScope(domain="workspace", components=("7", "orders", "open"))
    )


def test_empty_scope_components_explicitly_mean_whole_domain() -> None:
    scope = ResourceScope(domain="tenant")

    assert scope.contains_identifier(ResourceIdentifier(domain="tenant", components=("7",)))
    assert scope.contains_scope(ResourceScope(domain="tenant", components=("anything",)))
    assert not scope.contains_identifier(
        ResourceIdentifier(domain="workspace", components=("7",))
    )


@pytest.mark.parametrize(
    "component",
    (
        "",
        ".",
        "..",
        "orders/42",
        r"orders\42",
        "%2e",
        "%252e",
        " leading",
        "trailing ",
        "e\u0301",
        "abc\u202e",
        "abc\u200d",
        "line\nbreak",
        "private\ue000",
    ),
)
def test_identifier_rejects_ambiguous_or_noncanonical_components(component: str) -> None:
    with pytest.raises(ValidationError):
        ResourceIdentifier(domain="tenant", components=(component,))


@pytest.mark.parametrize(
    "domain",
    (
        "Tenant",
        "tenant.example",
        "tenant/domain",
        "tenant%2fother",
        " tenant",
        "tenant ",
        "1tenant",
        "",
    ),
)
def test_resource_domain_requires_explicit_lowercase_ascii_grammar(domain: str) -> None:
    with pytest.raises(ValidationError):
        ResourceScope(domain=domain)


@pytest.mark.parametrize(
    "raw_component",
    (
        "https://example.com/orders/42",
        r"C:\\tenant\\orders\\42",
        "bucket/key/with/slashes",
        "orders%2F42",
    ),
)
def test_v1_does_not_silently_treat_urls_paths_or_object_keys_as_hierarchy(
    raw_component: str,
) -> None:
    with pytest.raises(ValidationError):
        ResourceIdentifier(domain="external", components=(raw_component,))


def test_unknown_resource_kind_and_schema_version_fail_closed() -> None:
    with pytest.raises(ValidationError):
        ResourceIdentifier.model_validate(
            {
                "schema_version": "agent-evals/resource/v2",
                "kind": "hierarchical",
                "domain": "tenant",
                "components": ["7"],
            }
        )
    with pytest.raises(ValidationError):
        ResourceIdentifier.model_validate(
            {
                "schema_version": "agent-evals/resource/v1",
                "kind": "url",
                "domain": "tenant",
                "components": ["7"],
            }
        )


def test_canonical_json_round_trips_without_rewriting_identity_material() -> None:
    resource = ResourceIdentifier(
        domain="tenant",
        components=("équipe", "Order-42"),
    )
    scope = ResourceScope(
        domain="tenant",
        components=("équipe",),
    )

    assert ResourceIdentifier.model_validate_json(resource.canonical_json) == resource
    assert ResourceScope.model_validate_json(scope.canonical_json) == scope
    assert resource.canonical_json == json.dumps(
        resource.model_dump(mode="python"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    assert '"kind":"hierarchical"' in resource.canonical_json
    assert '"schema_version":"agent-evals/resource/v1"' in resource.canonical_json


@given(
    domain=_VALID_DOMAIN,
    parent_components=strategies.lists(_VALID_COMPONENT, min_size=0, max_size=4),
    suffix=strategies.lists(_VALID_COMPONENT, min_size=1, max_size=4),
)
@settings(max_examples=100, deadline=None)
def test_structural_scope_contains_only_exact_component_prefixes(
    domain: str,
    parent_components: list[str],
    suffix: list[str],
) -> None:
    scope = ResourceScope(domain=domain, components=tuple(parent_components))
    contained = ResourceIdentifier(
        domain=domain,
        components=tuple([*parent_components, *suffix]),
    )
    assert scope.contains_identifier(contained)

    if parent_components:
        collided = list(parent_components)
        collided[-1] = f"{collided[-1]}x"
        collision = ResourceIdentifier(
            domain=domain,
            components=tuple([*collided, *suffix]),
        )
        assert not scope.contains_identifier(collision)


@given(
    domain=_VALID_DOMAIN,
    components=strategies.lists(_VALID_COMPONENT, min_size=1, max_size=6),
)
@settings(max_examples=100, deadline=None)
def test_identifier_canonical_serialization_is_stable(
    domain: str,
    components: list[str],
) -> None:
    resource = ResourceIdentifier(domain=domain, components=tuple(components))
    reconstructed = ResourceIdentifier.model_validate_json(resource.canonical_json)

    assert reconstructed == resource
    assert reconstructed.canonical_json == resource.canonical_json
    assert reconstructed.kind is ResourceKind.HIERARCHICAL
