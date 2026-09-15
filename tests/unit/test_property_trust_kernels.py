from __future__ import annotations

import string
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_evals.adversarial.delivery import _receipt_root as attack_receipt_root
from agent_evals.contracts.models import AuthorityPolicy, EvaluationScenario, ScenarioKind
from agent_evals.contracts.resource import (
    ResourceIdentifier,
    ResourceScope,
    parse_resource_identifier_payload,
    resource_identifier_payload,
)
from agent_evals.retrieval.receipt import _receipt_root as retrieval_receipt_root
from agent_evals.semantic.receipt import _receipt_root as semantic_receipt_root
from agent_evals.side_effect.receipt import _receipt_root as side_effect_receipt_root

_ASCII_DOMAIN_START = tuple(string.ascii_lowercase)
_ASCII_DOMAIN_REST = string.ascii_lowercase + string.digits + "_-"
_ASCII_COMPONENTS = string.ascii_letters + string.digits + "_-.:@"
_ASCII_TOOL = string.ascii_lowercase + string.digits + "_-"

_DOMAIN = st.builds(
    lambda first, rest: first + rest,
    st.sampled_from(_ASCII_DOMAIN_START),
    st.text(alphabet=_ASCII_DOMAIN_REST, max_size=11),
)
_COMPONENT = st.text(alphabet=_ASCII_COMPONENTS, min_size=1, max_size=24).filter(
    lambda value: value not in {".", ".."}
)
_COMPONENT_PATH = st.lists(_COMPONENT, min_size=1, max_size=6).map(tuple)
_SCOPE_PATH = st.lists(_COMPONENT, max_size=5).map(tuple)
_TOOL = st.text(alphabet=_ASCII_TOOL, min_size=1, max_size=20)

_JSON_SCALAR = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**63), max_value=2**63 - 1)
    | st.floats(allow_nan=False, allow_infinity=False, width=32)
    | st.text(max_size=20)
)
_JSON_VALUE = st.recursive(
    _JSON_SCALAR,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=12), children, max_size=4)
    ),
    max_leaves=20,
)
_JSON_MAPPING = st.dictionaries(st.text(max_size=12), _JSON_VALUE, max_size=8)

_RECEIPT_ROOTS = (
    attack_receipt_root,
    semantic_receipt_root,
    retrieval_receipt_root,
    side_effect_receipt_root,
)


def _reverse_mapping_order(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _reverse_mapping_order(child) for key, child in reversed(list(value.items()))}
    if isinstance(value, list):
        return [_reverse_mapping_order(child) for child in value]
    return value


@settings(max_examples=100, deadline=None)
@given(domain=_DOMAIN, components=_COMPONENT_PATH)
def test_canonical_resource_payload_round_trips_through_strict_parser(
    domain: str,
    components: tuple[str, ...],
) -> None:
    resource = ResourceIdentifier(domain=domain, components=components)
    payload = resource_identifier_payload(resource)

    assert parse_resource_identifier_payload(payload) == resource
    assert resource_identifier_payload(parse_resource_identifier_payload(payload)) == payload


@settings(max_examples=100, deadline=None)
@given(
    domain=_DOMAIN,
    components=_COMPONENT_PATH,
    omitted=st.sampled_from(("schema_version", "kind", "domain", "components")),
)
def test_resource_parser_rejects_canonical_equivalents_that_are_not_canonical_json(
    domain: str,
    components: tuple[str, ...],
    omitted: str,
) -> None:
    resource = ResourceIdentifier(domain=domain, components=components)
    payload = resource_identifier_payload(resource)

    tuple_components = dict(payload)
    tuple_components["components"] = tuple(components)
    with pytest.raises(ValueError, match="components must be a JSON string array"):
        parse_resource_identifier_payload(tuple_components)

    missing_field = dict(payload)
    missing_field.pop(omitted)
    with pytest.raises(ValueError, match="exact typed resource fields"):
        parse_resource_identifier_payload(missing_field)


@settings(max_examples=100, deadline=None)
@given(data=st.data(), domain=_DOMAIN, components=_COMPONENT_PATH)
def test_resource_scope_authorization_is_structural_domain_aware_and_transitive(
    data: st.DataObject,
    domain: str,
    components: tuple[str, ...],
) -> None:
    outer_depth = data.draw(st.integers(min_value=0, max_value=len(components)))
    inner_depth = data.draw(st.integers(min_value=outer_depth, max_value=len(components)))

    outer = ResourceScope(domain=domain, components=components[:outer_depth])
    inner = ResourceScope(domain=domain, components=components[:inner_depth])
    resource = ResourceIdentifier(domain=domain, components=components)

    assert outer.contains_scope(inner)
    assert inner.contains_identifier(resource)
    assert outer.contains_identifier(resource)

    foreign = ResourceIdentifier(domain=f"{domain}x", components=components)
    assert not outer.contains_identifier(foreign)


@settings(max_examples=100, deadline=None)
@given(domain=_DOMAIN, component=_COMPONENT, suffix=_COMPONENT)
def test_resource_scope_does_not_authorize_lexical_prefix_collisions(
    domain: str,
    component: str,
    suffix: str,
) -> None:
    scope = ResourceScope(domain=domain, components=(component,))
    resource = ResourceIdentifier(domain=domain, components=(f"{component}{suffix}",))

    assert not scope.contains_identifier(resource)


@settings(max_examples=100, deadline=None)
@given(
    tools=st.sets(_TOOL, max_size=6),
    scope_paths=st.lists(_SCOPE_PATH, max_size=5),
)
def test_scenario_contract_identity_is_invariant_to_unordered_authority_material(
    tools: set[str],
    scope_paths: list[tuple[str, ...]],
) -> None:
    scopes = tuple(ResourceScope(domain="tenant", components=path) for path in scope_paths)
    reversed_scopes = tuple(reversed(scopes))

    first = EvaluationScenario(
        scenario_id="property.contract-order",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Generated contract-order invariant.",
        authority=AuthorityPolicy(
            allowed_tools=frozenset(tools),
            allowed_resource_scopes=scopes,
        ),
        tags=frozenset(tools),
    )
    second = EvaluationScenario(
        scenario_id="property.contract-order",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Generated contract-order invariant.",
        authority=AuthorityPolicy(
            allowed_tools=frozenset(reversed(tuple(tools))),
            allowed_resource_scopes=reversed_scopes,
        ),
        tags=frozenset(reversed(tuple(tools))),
    )

    assert first.authority == second.authority
    assert first.identity == second.identity


@settings(max_examples=100, deadline=None)
@given(material=_JSON_MAPPING)
def test_receipt_roots_are_invariant_to_mapping_insertion_order(material: dict[str, Any]) -> None:
    reversed_material = _reverse_mapping_order(material)

    for root in _RECEIPT_ROOTS:
        assert root(material) == root(reversed_material)


@settings(max_examples=100, deadline=None)
@given(key=st.text(alphabet=string.ascii_letters, min_size=1, max_size=12), value=st.text(alphabet=string.ascii_letters + string.digits, max_size=24))
def test_receipt_root_domains_remain_distinct_for_identical_canonical_material(
    key: str,
    value: str,
) -> None:
    material = {key: value}
    roots = {root(material) for root in _RECEIPT_ROOTS}

    assert len(roots) == len(_RECEIPT_ROOTS)
