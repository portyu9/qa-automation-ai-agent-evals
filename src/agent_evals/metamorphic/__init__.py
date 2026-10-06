"""Metamorphic relations for agent behavior and authority contracts."""

from agent_evals.metamorphic.mutations import (
    MetamorphicEffectivenessPolicy,
    MetamorphicEffectivenessReport,
    MetamorphicMutantOutcome,
    MetamorphicMutantResult,
    MetamorphicMutationRecord,
    MetamorphicMutationSpec,
    generate_metamorphic_mutant,
)
from agent_evals.metamorphic.relations import (
    MetamorphicDecision,
    RelationResult,
    StateProjectionInvariant,
    authority_does_not_expand,
)

__all__ = [
    "MetamorphicDecision",
    "MetamorphicEffectivenessPolicy",
    "MetamorphicEffectivenessReport",
    "MetamorphicMutantOutcome",
    "MetamorphicMutantResult",
    "MetamorphicMutationRecord",
    "MetamorphicMutationSpec",
    "RelationResult",
    "StateProjectionInvariant",
    "authority_does_not_expand",
    "generate_metamorphic_mutant",
]
