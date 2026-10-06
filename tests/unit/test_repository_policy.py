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
    (workspace / "requirements/locks").mkdir(parents=True)
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
    for lock in (_PROJECT_ROOT / "requirements/locks").glob("*.txt"):
        shutil.copy2(lock, workspace / "requirements/locks" / lock.name)
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
    required = 'export SOURCE_DATE_EPOCH="$(git show -s --format=%ct "$GITHUB_SHA")"'
    assert source.count(required) >= 2
    workflow.write_text(source.replace(required, "export SOURCE_DATE_EPOCH=0", 1), encoding="utf-8")

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
    assert "--require-hashes" in source
    workflow.write_text(source.replace("--require-hashes", "", 1), encoding="utf-8")

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
