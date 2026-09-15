from __future__ import annotations

import importlib.util
import json
import re
import sys
import tomllib
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _PROJECT_ROOT / ".github/scripts/run_deep_mutation.py"
_MANIFEST = _PROJECT_ROOT / ".github/mutation/deep_targets.json"
_WORKFLOW = _PROJECT_ROOT / ".github/workflows/deep-mutation.yml"
_PYPROJECT = _PROJECT_ROOT / "pyproject.toml"
_CI = _PROJECT_ROOT / ".github/workflows/ci.yml"

_REQUIRED_SOURCES = {
    "src/agent_evals/authority.py",
    "src/agent_evals/runtime/preconditions.py",
    "src/agent_evals/runtime/_evaluator_core.py",
    "src/agent_evals/runtime/evaluator.py",
    "src/agent_evals/runtime/grading.py",
    "src/agent_evals/oracles/deterministic.py",
    "src/agent_evals/side_effect/oracle.py",
    "src/agent_evals/adversarial/delivery.py",
    "src/agent_evals/retrieval/receipt.py",
    "src/agent_evals/retrieval/verification.py",
    "src/agent_evals/semantic/receipt.py",
    "src/agent_evals/semantic/verification.py",
    "src/agent_evals/side_effect/receipt.py",
    "src/agent_evals/side_effect/verification.py",
    "src/agent_evals/evidence/store.py",
    "src/agent_evals/gates/release.py",
}
_INITIAL_PR_TARGETS = {
    "src/agent_evals/evidence/limits.py",
    "src/agent_evals/statistics/limits.py",
}


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_deep_mutation_runner", _RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_RUNNER_MODULE = _load_runner()
DeepMutationPolicyError = _RUNNER_MODULE.DeepMutationPolicyError
load_manifest = _RUNNER_MODULE.load_manifest
replace_mutmut_section = _RUNNER_MODULE.replace_mutmut_section
survivor_names = _RUNNER_MODULE.survivor_names


def _payload() -> dict[str, object]:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _write_manifest(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_checked_in_manifest_covers_named_item34_trust_surfaces() -> None:
    manifest = load_manifest(_MANIFEST, repository_root=_PROJECT_ROOT)

    observed_sources = {source for campaign in manifest.campaigns for source in campaign.sources}
    assert observed_sources == _REQUIRED_SOURCES
    assert manifest.minimum_score == 95.0
    assert manifest.max_children == 2
    assert manifest.campaign_timeout_seconds == 900
    assert len(manifest.campaigns) == 10
    assert all(campaign.tests for campaign in manifest.campaigns)
    assert all(
        not source.startswith("src/agent_evals/adapters/openai_")
        for source in observed_sources
    )


def test_manifest_pins_same_mutmut_version_as_development_dependency() -> None:
    payload = _payload()
    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))

    assert payload["tool"] == {"name": "mutmut", "version": "3.8.0"}
    assert "mutmut==3.8.0" in project["project"]["optional-dependencies"]["dev"]


def test_manifest_rejects_lower_score(tmp_path: Path) -> None:
    payload = _payload()
    payload["minimum_score"] = 94.99

    with pytest.raises(DeepMutationPolicyError, match="minimum_score"):
        load_manifest(_write_manifest(tmp_path, payload))


def test_manifest_rejects_missing_campaign(tmp_path: Path) -> None:
    payload = _payload()
    campaigns = payload["campaigns"]
    assert isinstance(campaigns, list)
    payload["campaigns"] = campaigns[:-1]

    with pytest.raises(DeepMutationPolicyError, match="campaign set mismatch"):
        load_manifest(_write_manifest(tmp_path, payload))


def test_manifest_rejects_duplicate_source_entry(tmp_path: Path) -> None:
    payload = _payload()
    campaigns = payload["campaigns"]
    assert isinstance(campaigns, list)
    first = campaigns[0]
    assert isinstance(first, dict)
    sources = first["sources"]
    assert isinstance(sources, list)
    sources.append(sources[0])

    with pytest.raises(DeepMutationPolicyError, match="must not contain duplicates"):
        load_manifest(_write_manifest(tmp_path, payload))


def test_manifest_rejects_provider_adapter_target(tmp_path: Path) -> None:
    payload = _payload()
    campaigns = payload["campaigns"]
    assert isinstance(campaigns, list)
    first = campaigns[0]
    assert isinstance(first, dict)
    first["sources"] = ["src/agent_evals/adapters/openai_agents.py"]

    with pytest.raises(DeepMutationPolicyError, match="provider adapter"):
        load_manifest(_write_manifest(tmp_path, payload))


def test_manifest_path_validation_rejects_missing_checked_in_file(tmp_path: Path) -> None:
    payload = _payload()
    campaigns = payload["campaigns"]
    assert isinstance(campaigns, list)
    first = campaigns[0]
    assert isinstance(first, dict)
    first["sources"] = ["src/agent_evals/not_real.py"]
    path = _write_manifest(tmp_path, payload)

    with pytest.raises(DeepMutationPolicyError, match="references missing file"):
        load_manifest(path, repository_root=_PROJECT_ROOT)


def test_campaign_config_replacement_preserves_unrelated_pyproject_sections() -> None:
    manifest = load_manifest(_MANIFEST)
    original = _PYPROJECT.read_text(encoding="utf-8")
    campaign = manifest.campaigns[0]

    rendered = replace_mutmut_section(original, campaign)
    parsed = tomllib.loads(rendered)

    assert set(parsed["tool"]["mutmut"]["only_mutate"]) == set(campaign.sources)
    assert parsed["tool"]["mutmut"]["pytest_add_cli_args_test_selection"] == list(campaign.tests)
    assert parsed["tool"]["coverage"] == tomllib.loads(original)["tool"]["coverage"]
    assert rendered.count("[tool.mutmut]") == 1


def test_survivor_parser_returns_only_explicit_survivors() -> None:
    text = """
agent_evals.foo.x__mutmut_1: killed
agent_evals.foo.x__mutmut_2: survived
agent_evals.foo.x__mutmut_3: timeout
agent_evals.foo.x__mutmut_4: survived
"""

    assert survivor_names(text) == (
        "agent_evals.foo.x__mutmut_2",
        "agent_evals.foo.x__mutmut_4",
    )


def test_deep_workflow_is_least_privilege_exact_head_and_non_release_authority() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert "pull_request:" in workflow
    assert "paths:" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "timeout-minutes: 180" in workflow
    assert "github.event.pull_request.head.sha || github.sha" in workflow
    assert "ref: ${{ env.EXACT_COMMIT }}" in workflow
    assert "persist-credentials: false" in workflow
    assert "if: always()" in workflow
    assert "retention-days: 21" in workflow
    assert "deploy" not in workflow.lower()
    assert "release" not in workflow.lower()
    assert "contents: write" not in workflow
    assert "actions: write" not in workflow

    action_refs = re.findall(r"uses:\s+[^@\s]+@([^\s]+)", workflow)
    assert action_refs
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs)


def test_deep_workflow_pr_trigger_is_limited_to_assurance_infrastructure() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    assert '      - ".github/mutation/**"' in workflow
    assert '      - ".github/scripts/run_deep_mutation.py"' in workflow
    assert '      - ".github/workflows/deep-mutation.yml"' in workflow
    assert '      - "MUTATION_ASSURANCE.md"' in workflow
    assert "src/agent_evals/**" not in workflow


def test_item33_pr_gate_remains_narrow_and_at_same_floor() -> None:
    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    ordinary_mutmut = project["tool"]["mutmut"]
    ci = _CI.read_text(encoding="utf-8")

    assert set(ordinary_mutmut["only_mutate"]) == _INITIAL_PR_TARGETS
    assert "MINIMUM_MUTATION_SCORE: Final = 95.0" in (
        _PROJECT_ROOT / ".github/scripts/check_mutation_score.py"
    ).read_text(encoding="utf-8")
    assert "Mutation assurance / trust kernels" in ci
    assert "deep-mutation" not in ci


def test_manifest_mutations_do_not_share_nested_state_between_test_cases() -> None:
    first = _payload()
    second = deepcopy(first)
    first_campaigns = first["campaigns"]
    second_campaigns = second["campaigns"]
    assert isinstance(first_campaigns, list)
    assert isinstance(second_campaigns, list)
    first_campaigns.pop()

    assert len(second_campaigns) == 10
