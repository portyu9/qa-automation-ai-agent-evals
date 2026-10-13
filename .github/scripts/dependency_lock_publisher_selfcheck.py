#!/usr/bin/env python3
"""Fail-closed dependency lock publisher + governor regression tests."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from dependency_governance import GovernanceError, PolicyBlock, load_config
from dependency_lock_publisher import (
    MAX_LOCK_BYTES, ROOT, expected_paths, validate_artifacts, validate_run,
)
from dependency_lock_provenance import validate_published_pip_chain


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
        manifest = (ROOT / "pyproject.toml").read_text()
        actual = validate_artifacts(root, manifest)
        assert set(actual) == {path for path, _ in expected.values()}
        assert all(100 < len(data) < MAX_LOCK_BYTES for data in actual.values())

        extra = root / "lock-malicious"
        extra.mkdir()
        assert_refused(validate_artifacts, root, manifest)
        extra.rmdir()

        wrong_manifest = manifest.replace("mcp==2.2.0", "mcp==99.0.0")
        assert wrong_manifest != manifest
        assert_refused(validate_artifacts, root, wrong_manifest)

        lock = root / "lock-mcp-py311" / "mcp-py311.txt"
        saved = lock.read_bytes()
        lock.write_bytes(saved.replace(b"mcp==2.2.0", b"mcp==99.0.0"))
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
        "number": 341, "commits": 2,
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
    assert_refused(
        validate_published_pip_chain, api, pull, commits, files, base, child, config
    )
    actor["id"] = 41898282
    api.data[f"/commits/{child}"]["commit"]["verification"]["verified"] = False
    assert_refused(
        validate_published_pip_chain, api, pull, commits, files, base, child, config
    )
    api.data[f"/commits/{child}"]["commit"]["verification"]["verified"] = True
    api.data[f"/commits/{child}"]["parents"] = [{"sha": "f" * 40}]
    assert_refused(
        validate_published_pip_chain, api, pull, commits, files, base, child, config
    )
    api.data[f"/commits/{child}"]["parents"] = [{"sha": source}]
    api.data[f"/commits/{child}"]["files"].append({"filename": ".github/workflows/ci.yml"})
    assert_refused(
        validate_published_pip_chain, api, pull, commits, files, base, child, config
    )
    api.data[f"/commits/{child}"]["files"].pop()
    assert_refused(
        validate_published_pip_chain, api, pull, commits, [
            {"filename": "pyproject.toml", "status": "modified"},
            {"filename": ".github/dependency-governance.json", "status": "modified"},
        ], base, child, config
    )
    event = {
        "workflow_run": {
            "name": "dependency-locks", "path": ".github/workflows/dependency-locks.yml",
            "event": "pull_request", "status": "completed", "conclusion": "success",
            "head_repository": {"full_name": api.repository},
            "head_branch": "dependabot/pip/routine-dependencies",
            "head_sha": child,
            "pull_requests": [{"number": 341}, {"number": 342}],
        }
    }
    assert_refused(validate_run, api, event)


if __name__ == "__main__":
    test_lock_artifact_validator()
    test_canonical_publisher_refusals()
    print("dependency lock publisher self-check passed")
