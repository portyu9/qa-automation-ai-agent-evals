#!/usr/bin/env python3
"""Fail-closed dependency lock publisher + governor regression tests."""

from __future__ import annotations

import re
import shutil
import tempfile
import tomllib
from pathlib import Path

import validate_ci_locks as snapshot_policy
import validate_dependency_compatibility as compatibility_policy
from dependency_governance import GovernanceError, PolicyBlock, load_config
from dependency_lock_provenance import validate_published_pip_chain
from dependency_lock_publisher import (
    MAX_LOCK_BYTES,
    ROOT,
    expected_paths,
    validate_artifacts,
    validate_run,
)
from generate_ci_lock import _normalize_header


def assert_refused(action, *arguments) -> None:  # type: ignore[no-untyped-def]
    try:
        action(*arguments)
    except (GovernanceError, PolicyBlock, ValueError, OSError, KeyError):
        return
    raise AssertionError("security regression: invalid evidence was accepted")


class FakeApi:
    repository = "portyu9/qa-automation-ai-agent-evals"

    def __init__(self) -> None:
        self.source = "a" * 40
        self.child = "b" * 40
        self.base = "c" * 40
        self.source_manifest = (ROOT / "pyproject.toml").read_text()
        self.data = {
            f"/commits/{self.source}": {
                "sha": self.source,
                "parents": [{"sha": self.base}],
                "files": [{"filename": "pyproject.toml"}],
            },
            f"/commits/{self.child}": {
                "sha": self.child,
                "author": {"login": "github-actions[bot]", "id": 41898282},
                "committer": {"login": "web-flow"},
                "commit": {
                    "author": {
                        "name": "github-actions[bot]",
                        "email": "41898282+github-actions[bot]@users.noreply.github.com",
                    },
                    "committer": {"name": "GitHub", "email": "noreply@github.com"},
                    "verification": {"verified": True, "reason": "valid", "signature": "signed"},
                    "message": (
                        "chore: publish trusted Dependabot dependency lock graph\n\n"
                        f"Generated from Dependabot source head {self.source} by trusted default-branch "
                        "dependency-lock-publisher."
                    ),
                },
                "parents": [{"sha": self.source}],
                "files": [{"filename": "requirements/locks/mcp-py311.txt"}],
            },
        }

    def get(self, path: str) -> dict:
        return self.data[path]


def _manifest_for_committed_lock_fixture() -> str:
    """Align this historical fixture with committed trusted locks, not a pending bot manifest.

    A canonical Dependabot pip PR legitimately changes pyproject.toml before
    publishing its new lock graph. The positive self-test must use the old
    committed lock graph's own direct pins; the production validator continues
    to validate generated artifacts against the *exact PR source manifest*.
    """
    manifest = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = tomllib.loads(manifest)["project"]
    accepted_pins = snapshot_policy.parse_lock(
        ROOT / "requirements/locks/openai-mcp-py311.txt", "3.11"
    )
    for requirements in project.get("optional-dependencies", {}).values():
        for requirement in requirements:
            required_pin = snapshot_policy.exact_pin(requirement)
            name = snapshot_policy.requirement_name(requirement)
            if required_pin is None or name not in accepted_pins:
                continue
            fixture_pin = f"{name}=={accepted_pins[name]}"
            if required_pin == fixture_pin:
                continue
            literal = f'"{requirement}"'
            if manifest.count(literal) != 1:
                raise AssertionError(f"ambiguous direct-pin fixture for {name}")
            aligned = re.sub(
                r"==[^,;\s]+", f"=={accepted_pins[name]}", requirement, count=1
            )
            manifest = manifest.replace(literal, f'"{aligned}"', 1)
    return manifest


def test_compatibility_artifact_selection_header() -> None:
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "fixture.txt"
        output.write_text("sample==1.0 \\\n    --hash=sha256:" + "a" * 64 + "\n", encoding="utf-8")
        _normalize_header(
            output, profile="core", boundary="minimum", input_digest="b" * 64
        )
        content = output.read_text(encoding="utf-8")
        header = compatibility_policy.parse_header(content, filename=output.name)
        assert header["Artifact-Selection"] == "linux-x86_64"
        assert header["Input-SHA256"] == "b" * 64
        assert header["Boundary"] == "minimum"
        assert_refused(
            lambda data: compatibility_policy.parse_header(data, filename=output.name),
            content.replace("# Artifact-Selection: linux-x86_64\n", ""),
        )


def test_lock_artifact_validator() -> None:
    expected = expected_paths()
    assert len(expected) == 12
    assert len(set(expected.values())) == 12
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for stem, (path, _) in expected.items():
            folder = root / f"lock-{stem}"
            folder.mkdir()
            shutil.copyfile(ROOT / path, folder / f"{stem}.txt")
        manifest = _manifest_for_committed_lock_fixture()
        actual = validate_artifacts(root, manifest)
        assert set(actual) == {path for path, _ in expected.values()}
        assert all(100 < len(data) < MAX_LOCK_BYTES for data in actual.values())

        extra = root / "lock-malicious"
        extra.mkdir()
        assert_refused(validate_artifacts, root, manifest)
        extra.rmdir()

        committed_mcp = snapshot_policy.parse_lock(
            ROOT / "requirements/locks/mcp-py311.txt", "3.11"
        )["mcp"]
        wrong_manifest = manifest.replace(f"mcp=={committed_mcp}", "mcp==99.0.0")
        assert wrong_manifest != manifest
        assert_refused(validate_artifacts, root, wrong_manifest)

        lock = root / "lock-mcp-py311" / "mcp-py311.txt"
        saved = lock.read_bytes()
        lock.write_bytes(
            saved.replace(f"mcp=={committed_mcp}".encode(), b"mcp==99.0.0")
        )
        assert lock.read_bytes() != saved
        assert_refused(validate_artifacts, root, manifest)
        lock.write_bytes(saved)

        link = root / "lock-mcp-py311" / "mcp-py311.txt"
        link.unlink()
        link.symlink_to(ROOT / "requirements/locks/mcp-py311.txt")
        assert_refused(validate_artifacts, root, manifest)


def test_canonical_publisher_refusals() -> None:
    api = FakeApi()
    source, child, base = api.source, api.child, api.base
    pull = {
        "number": 341,
        "commits": 2,
        "head": {"ref": "dependabot/pip/routine-dependencies", "sha": child},
    }
    commits = [{"sha": source}, {"sha": child}]
    files = [
        {"filename": "pyproject.toml", "status": "modified"},
        {"filename": "requirements/locks/mcp-py311.txt", "status": "modified"},
    ]
    config = load_config()
    # This fixture lacks a real prior source artifact; all violations should
    # fail independently of any generated lock graph.
    actor = api.data[f"/commits/{child}"]["author"]
    actor["id"] = 1
    assert_refused(validate_published_pip_chain, api, pull, commits, files, base, child, config)
    actor["id"] = 41898282
    api.data[f"/commits/{child}"]["commit"]["verification"]["verified"] = False
    assert_refused(validate_published_pip_chain, api, pull, commits, files, base, child, config)
    api.data[f"/commits/{child}"]["commit"]["verification"]["verified"] = True
    api.data[f"/commits/{child}"]["parents"] = [{"sha": "f" * 40}]
    assert_refused(validate_published_pip_chain, api, pull, commits, files, base, child, config)
    api.data[f"/commits/{child}"]["parents"] = [{"sha": source}]
    api.data[f"/commits/{child}"]["files"].append({"filename": ".github/workflows/ci.yml"})
    assert_refused(validate_published_pip_chain, api, pull, commits, files, base, child, config)
    api.data[f"/commits/{child}"]["files"].pop()
    assert_refused(
        validate_published_pip_chain,
        api,
        pull,
        commits,
        [
            {"filename": "pyproject.toml", "status": "modified"},
            {"filename": ".github/dependency-governance.json", "status": "modified"},
        ],
        base,
        child,
        config,
    )
    event = {
        "workflow_run": {
            "name": "dependency-locks",
            "path": ".github/workflows/dependency-locks.yml",
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "head_repository": {"full_name": api.repository},
            "head_branch": "dependabot/pip/routine-dependencies",
            "head_sha": child,
            "pull_requests": [{"number": 341}, {"number": 342}],
        }
    }
    assert_refused(validate_run, api, event)


if __name__ == "__main__":
    test_compatibility_artifact_selection_header()
    test_lock_artifact_validator()
    test_canonical_publisher_refusals()
    print("dependency lock publisher self-check passed")
