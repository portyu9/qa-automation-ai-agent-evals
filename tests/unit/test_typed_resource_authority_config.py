from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.contracts.models import AuthorityPolicy, HandoffAuthorityGrant
from agent_evals.contracts.resource import ResourceScope


def scope(*components: str) -> ResourceScope:
    return ResourceScope(domain="tenant", components=components)


def test_root_authority_rejects_legacy_resource_prefix_configuration() -> None:
    with pytest.raises(ValidationError, match="allowed_resource_prefixes"):
        AuthorityPolicy.model_validate(
            {
                "allowed_tools": ["read"],
                "allowed_resource_prefixes": ["tenant/7/"],
            }
        )


def test_root_authority_rejects_mixed_legacy_and_typed_resource_configuration() -> None:
    with pytest.raises(ValidationError, match="allowed_resource_prefixes"):
        AuthorityPolicy.model_validate(
            {
                "allowed_tools": ["read"],
                "allowed_resource_scopes": [scope("7").model_dump(mode="json")],
                "allowed_resource_prefixes": ["tenant/7/"],
            }
        )


def test_delegated_authority_rejects_legacy_resource_prefix_configuration() -> None:
    with pytest.raises(ValidationError, match="allowed_resource_prefixes"):
        HandoffAuthorityGrant.model_validate(
            {
                "source_agent": "root",
                "target_agent": "worker",
                "allowed_tools": ["read"],
                "allowed_resource_prefixes": ["tenant/7/"],
            }
        )


def test_delegated_authority_rejects_mixed_legacy_and_typed_resource_configuration() -> None:
    with pytest.raises(ValidationError, match="allowed_resource_prefixes"):
        HandoffAuthorityGrant.model_validate(
            {
                "source_agent": "root",
                "target_agent": "worker",
                "allowed_tools": ["read"],
                "allowed_resource_scopes": [scope("7").model_dump(mode="json")],
                "allowed_resource_prefixes": ["tenant/7/"],
            }
        )
