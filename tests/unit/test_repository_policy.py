from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_POLICY_SCRIPT = _PROJECT_ROOT / ".github/scripts/validate_runtime_policy.py"
_PINNED_CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"


def _policy_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    (workspace / ".github/workflows").mkdir(parents=True)
    (workspace / ".github/coverage").mkdir(parents=True)
    (workspace / ".github/scripts").mkdir(parents=True)
    (workspace / "docs").mkdir(parents=True)
    (workspace / "tests/integration").mkdir(parents=True)
    (workspace / "requirements/locks").mkdir(parents=True)
    (workspace / "requirements/compatibility").mkdir(parents=True)
    (workspace / "src/agent_evals").mkdir(parents=True)
    shutil.copy2(_PROJECT_ROOT / "pyproject.toml", workspace / "pyproject.toml")
    shutil.copy2(
        _PROJECT_ROOT / "requirements-dev-ci-build.txt",
        workspace / "requirements-dev-ci-build.txt",
    )
    shutil.copy2(
        _PROJECT_ROOT / ".github/scripts/validate_ci_locks.py",
        workspace / ".github/scripts/validate_ci_locks.py",
    )
    shutil.copy2(
        _PROJECT_ROOT / ".github/scripts/validate_dependency_compatibility.py",
        workspace / ".github/scripts/validate_dependency_compatibility.py",
    )
    shutil.copy2(
        _PROJECT_ROOT / ".github/scripts/validate_governance_policy.py",
        workspace / ".github/scripts/validate_governance_policy.py",
    )
    shutil.copy2(
        _PROJECT_ROOT / ".github/repository-governance.json",
        workspace / ".github/repository-governance.json",
    )
    shutil.copy2(_PROJECT_ROOT / ".github/CODEOWNERS", workspace / ".github/CODEOWNERS")
    shutil.copy2(
        _PROJECT_ROOT / "docs/REPOSITORY_GOVERNANCE.md",
        workspace / "docs/REPOSITORY_GOVERNANCE.md",
    )
    for lock in (_PROJECT_ROOT / "requirements/locks").glob("*.txt"):
        shutil.copy2(lock, workspace / "requirements/locks" / lock.name)
    for lock in (_PROJECT_ROOT / "requirements/compatibility").glob("*.txt"):
        shutil.copy2(lock, workspace / "requirements/compatibility" / lock.name)
    shutil.copy2(
        _PROJECT_ROOT / ".github/workflows/ci.yml",
        workspace / ".github/workflows/ci.yml",
    )
    shutil.copy2(
        _PROJECT_ROOT / ".github/workflows/publish-release.yml",
        workspace / ".github/workflows/publish-release.yml",
    )
    shutil.copy2(
        _PROJECT_ROOT / ".github/dependency-license-policy.json",
        workspace / ".github/dependency-license-policy.json",
    )
    shutil.copy2(
        _PROJECT_ROOT / ".github/workflows/deep-fuzz.yml",
        workspace / ".github/workflows/deep-fuzz.yml",
    )
    shutil.copy2(
        _PROJECT_ROOT / ".github/workflows/deep-mutation.yml",
        workspace / ".github/workflows/deep-mutation.yml",
    )
    shutil.copy2(
        _PROJECT_ROOT / ".github/coverage/thresholds.json",
        workspace / ".github/coverage/thresholds.json",
    )
    shutil.copy2(_PROJECT_ROOT / "src/agent_evals/py.typed", workspace / "src/agent_evals/py.typed")
    shutil.copy2(_PROJECT_ROOT / "tests/conftest.py", workspace / "tests/conftest.py")
    shutil.copy2(
        _PROJECT_ROOT / "tests/integration/test_mcp_remote_auth.py",
        workspace / "tests/integration/test_mcp_remote_auth.py",
    )
    shutil.copy2(
        _PROJECT_ROOT / "tests/integration/test_mcp_oauth_flow.py",
        workspace / "tests/integration/test_mcp_oauth_flow.py",
    )
    return workspace


def _run_policy(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_POLICY_SCRIPT)],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )


def _secondary_workflow(action: str) -> str:
    return f"""name: Secondary\non: workflow_dispatch\njobs:\n  check:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: {action}\n"""


def test_policy_rejects_floating_action_in_second_workflow(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    (workspace / ".github/workflows/release.yml").write_text(
        _secondary_workflow("actions/checkout@v7"),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "release.yml" in result.stderr
    assert "pinned to a full commit SHA" in result.stderr


def test_policy_accepts_pinned_action_in_second_workflow(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    (workspace / ".github/workflows/release.yaml").write_text(
        _secondary_workflow(_PINNED_CHECKOUT),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode == 0, result.stderr
    assert "workflows=5" in result.stdout


def test_policy_rejects_missing_reproducible_package_comparison(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    required = "python .github/scripts/package_artifact_manifest.py compare"
    assert required in source
    workflow.write_text(
        source.replace(required, "python .github/scripts/package_artifact_manifest.py verify", 1),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert (
        "package-reproduce must compare rebuilt bytes against the retained manifest"
        in result.stderr
    )


def test_policy_rejects_package_build_without_source_bound_epoch(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    required = 'SOURCE_DATE_EPOCH="$(git show -s --format=%ct "$GITHUB_SHA")"'
    assert source.count(required) >= 2
    workflow.write_text(source.replace(required, "SOURCE_DATE_EPOCH=0", 1), encoding="utf-8")

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert (
        "package build must derive SOURCE_DATE_EPOCH from the exact source commit" in result.stderr
    )


def test_policy_rejects_publish_without_retained_spdx_sbom(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/publish-release.yml"
    source = workflow.read_text(encoding="utf-8")
    required = "retained-supply-chain/release-sbom.spdx.json"
    assert required in source
    workflow.write_text(
        source.replace(required, "retained-supply-chain/missing-sbom.json", 1),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "publish-release workflow is missing required contract text" in result.stderr


def test_policy_rejects_license_refs_becoming_self_authorized(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    policy_path = workspace / ".github/dependency-license-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["allow_license_refs"] = True
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "fail closed on LicenseRef values" in result.stderr


def test_policy_rejects_unhashed_quality_dependency_install(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    required = '--require-hashes             -r "requirements/locks/core-py${lock_suffix}.txt"'
    assert required in source
    workflow.write_text(
        source.replace(required, required.replace("--require-hashes", ""), 1), encoding="utf-8"
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "quality must install the exact repository lock" in result.stderr


def test_policy_rejects_package_build_isolation(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    required = "python -m build --no-isolation"
    assert required in source
    workflow.write_text(source.replace(required, "python -m build", 1), encoding="utf-8")

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "package build must use the locked non-isolated build contract" in result.stderr


def test_policy_rejects_lock_hash_algorithm_tampering(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    lock = workspace / "requirements/locks/core-py311.txt"
    source = lock.read_text(encoding="utf-8")
    assert "--hash=sha256:" in source
    lock.write_text(source.replace("--hash=sha256:", "--hash=sha512:"), encoding="utf-8")

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "CI lock contract failed" in result.stderr


def test_policy_rejects_qualification_evidence_outside_trusted_main_push(
    tmp_path: Path,
) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    required = "if: github.event_name == 'push' && github.ref == 'refs/heads/main'"
    qualification_marker = "  qualification-evidence:\n"
    assert qualification_marker in source
    prefix, qualification = source.split(qualification_marker, 1)
    assert required in qualification
    workflow.write_text(
        prefix + qualification_marker + qualification.replace(required, "if: always()", 1),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "qualification-evidence must be restricted to trusted main pushes" in result.stderr


def test_policy_rejects_release_statement_outside_trusted_main_push(
    tmp_path: Path,
) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    required = "if: github.event_name == 'push' && github.ref == 'refs/heads/main'"
    statement_marker = "  release-statement:\n"
    assert statement_marker in source
    prefix, statement = source.split(statement_marker, 1)
    assert required in statement
    workflow.write_text(
        prefix + statement_marker + statement.replace(required, "if: always()", 1),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "release-statement must be restricted to trusted main pushes" in result.stderr


def test_policy_rejects_release_statement_self_dependency(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    statement_marker = "  release-statement:\n"
    signer_marker = "  release-provenance:\n"
    assert statement_marker in source
    assert signer_marker in source
    prefix, tail = source.split(statement_marker, 1)
    statement, suffix = tail.split(signer_marker, 1)
    anchor = "      - qualification-evidence\n"
    assert anchor in statement
    statement = statement.replace(
        anchor,
        anchor + "      - release-statement\n",
        1,
    )
    workflow.write_text(
        prefix + statement_marker + statement + signer_marker + suffix,
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "release-statement must not depend on itself" in result.stderr


def test_policy_rejects_release_statement_with_signing_authority(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    statement_marker = "  release-statement:\n"
    signer_marker = "  release-provenance:\n"
    assert statement_marker in source
    assert signer_marker in source
    prefix, tail = source.split(statement_marker, 1)
    statement, suffix = tail.split(signer_marker, 1)
    anchor = "    runs-on: ubuntu-24.04\n"
    assert anchor in statement
    statement = statement.replace(
        anchor,
        "    permissions:\n      id-token: write\n" + anchor,
        1,
    )
    workflow.write_text(
        prefix + statement_marker + statement + signer_marker + suffix,
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert (
        "release-statement must retain an unsigned statement without signing authority"
        in result.stderr
    )


def test_policy_rejects_publish_without_release_statement_verification(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/publish-release.yml"
    source = workflow.read_text(encoding="utf-8")
    required = "release_statement.py verify"
    assert required in source
    workflow.write_text(
        source.replace(required, "release_statement.py self-test", 1),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "publish-release workflow is missing required contract text" in result.stderr


def test_policy_rejects_publish_without_exact_candidate_source_binding(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/publish-release.yml"
    source = workflow.read_text(encoding="utf-8")
    required = "CI_COMMIT_SHA: ${{ steps.candidate.outputs.commit_sha }}"
    assert required in source
    workflow.write_text(
        source.replace(required, "CI_COMMIT_SHA: ${{ github.sha }}", 1),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "publish-release candidate source materialization is missing" in result.stderr


def test_policy_rejects_dynamic_candidate_checkout(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/publish-release.yml"
    source = workflow.read_text(encoding="utf-8")
    anchor = "      - name: Download exact CI-tested package artifact\n"
    assert anchor in source
    dynamic_checkout = (
        "      - name: Forbidden dynamic candidate checkout\n"
        "        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n"
        "        with:\n"
        "          ref: ${{ steps.candidate.outputs.commit_sha }}\n"
        "          persist-credentials: false\n"
    )
    workflow.write_text(
        source.replace(anchor, dynamic_checkout + anchor, 1),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "exactly one trusted default-branch checkout" in result.stderr


def test_policy_rejects_pypi_publication_without_trusted_publishing_contract(
    tmp_path: Path,
) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/publish-release.yml"
    source = workflow.read_text(encoding="utf-8")
    workflow.write_text(
        source + "\n# forbidden publication mutation\n# twine upload dist/*\n",
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "forbidden release behavior: twine upload" in result.stderr


def test_policy_rejects_provenance_signing_outside_trusted_main_push(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    required = "if: github.event_name == 'push' && github.ref == 'refs/heads/main'"
    signer_marker = "  release-provenance:\n"
    assert signer_marker in source
    prefix, signer = source.split(signer_marker, 1)
    assert required in signer
    workflow.write_text(
        prefix + signer_marker + signer.replace(required, "if: always()", 1),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "signing authority must be restricted to trusted main pushes" in result.stderr


def test_policy_rejects_provenance_without_oidc_permission(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    required = "      id-token: write\n"
    assert required in source
    workflow.write_text(source.replace(required, "", 1), encoding="utf-8")

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "missing least-privilege signing permission: id-token: write" in result.stderr


def test_policy_rejects_floating_attestation_action(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8")
    pinned = "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"
    assert pinned in source
    workflow.write_text(source.replace(pinned, "actions/attest@v4", 1), encoding="utf-8")

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "pinned to a full commit SHA" in result.stderr
    assert "actions/attest@v4" in result.stderr


def test_policy_rejects_publish_without_provenance_verification(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/publish-release.yml"
    source = workflow.read_text(encoding="utf-8")
    required = "gh attestation verify"
    assert required in source
    workflow.write_text(source.replace(required, "echo provenance-skipped", 1), encoding="utf-8")

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "publish-release workflow is missing required contract text" in result.stderr


def test_policy_rejects_publish_workflow_minting_fresh_attestation(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    workflow = workspace / ".github/workflows/publish-release.yml"
    source = workflow.read_text(encoding="utf-8")
    anchor = "permissions:\n  actions: read\n  contents: write\n"
    assert anchor in source
    workflow.write_text(
        source.replace(anchor, anchor + "  id-token: write\n", 1),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "verify retained provenance without minting new attestations" in result.stderr


def test_policy_rejects_missing_network_loopback_marker_registration(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    pyproject = workspace / "pyproject.toml"
    source = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(
        "\n".join(line for line in source.splitlines() if "network_loopback:" not in line) + "\n",
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "must register the network_loopback marker" in result.stderr


def test_policy_rejects_live_tests_from_ordinary_pytest_selection(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    pyproject = workspace / "pyproject.toml"
    source = pyproject.read_text(encoding="utf-8")
    assert " and not live" in source
    pyproject.write_text(source.replace(" and not live", "", 1), encoding="utf-8")

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "must exclude the live-provider marker" in result.stderr


def test_policy_rejects_mcp_remote_without_loopback_authority(tmp_path: Path) -> None:
    workspace = _policy_workspace(tmp_path)
    test_path = workspace / "tests/integration/test_mcp_remote_auth.py"
    source = test_path.read_text(encoding="utf-8")
    assert ", pytest.mark.network_loopback" in source
    test_path.write_text(
        source.replace(", pytest.mark.network_loopback", "", 1),
        encoding="utf-8",
    )

    result = _run_policy(workspace)

    assert result.returncode != 0
    assert "must opt into network_loopback authority" in result.stderr
