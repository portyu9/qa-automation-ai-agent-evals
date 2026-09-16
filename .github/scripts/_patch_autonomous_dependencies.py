from pathlib import Path

controller = Path('.github/scripts/dependency_governance.py')
text = controller.read_text(encoding='utf-8')

text = text.replace(
    'import argparse\nimport json\n',
    'import argparse\nimport base64\nimport copy\nimport json\n',
    1,
)
text = text.replace(
    'import re\nimport urllib.error\n',
    'import re\nimport tomllib\nimport urllib.error\n',
    1,
)
text = text.replace(
    'SHA = re.compile(r"^[0-9a-f]{40}$")\n',
    'SHA = re.compile(r"^[0-9a-f]{40}$")\n'
    'DEPENDENCY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")\n'
    'MAX_MANIFEST_BYTES = 256 * 1024\n',
    1,
)
text = text.replace(
    '    if config.get("pipMode") != "manual":\n'
    '        errors.append("pipMode must equal manual")\n',
    '    if config.get("pipMode") != "exact-subject-green":\n'
    '        errors.append("pipMode must equal exact-subject-green")\n'
    '    if config.get("pipManifestPaths") != ["pyproject.toml"]:\n'
    '        errors.append("pipManifestPaths must equal [pyproject.toml]")\n',
    1,
)
text = text.replace(
    '        "version-update:semver-patch",\n'
    '        "version-update:semver-minor",\n'
    '        "security-update:semver-patch",\n'
    '        "security-update:semver-minor",\n',
    '        "version-update:semver-patch",\n'
    '        "version-update:semver-minor",\n'
    '        "version-update:semver-major",\n'
    '        "security-update:semver-patch",\n'
    '        "security-update:semver-minor",\n'
    '        "security-update:semver-major",\n',
    1,
)
text = text.replace(
    '            "allowedActionUpdateTypes must be exactly patch/minor version and security updates"\n',
    '            "allowedActionUpdateTypes must be exactly patch/minor/major version and security updates"\n',
    1,
)
text = text.replace(
    '            old_v = next(iter(old_versions))\n'
    '            new_v = next(iter(new_versions))\n'
    '            if old_v[0] != new_v[0]:\n'
    '                raise PolicyBlock(f"major action update requires manual review: {action}")\n'
    '            if next(iter(old_shas)) == next(iter(new_shas)):\n',
    '            old_v = next(iter(old_versions))\n'
    '            new_v = next(iter(new_versions))\n'
    '            if new_v <= old_v:\n'
    '                raise PolicyBlock(f"action update must advance the semantic version: {action}")\n'
    '            if next(iter(old_shas)) == next(iter(new_shas)):\n',
    1,
)

marker = '\n\ndef verify_merge_subject(\n'
insert = r'''


def _repo_text_at_sha(api: GitHubApi, path: str, sha: str) -> str:
    payload = api.get(
        f"/contents/{urllib.parse.quote(path, safe='/')}?ref={urllib.parse.quote(sha, safe='')}"
    )
    if not isinstance(payload, dict) or payload.get("type") != "file":
        raise PolicyBlock(f"unable to resolve repository file at exact subject: {path}")
    size = payload.get("size")
    encoded = payload.get("content")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size < 1
        or size > MAX_MANIFEST_BYTES
        or payload.get("encoding") != "base64"
        or not isinstance(encoded, str)
    ):
        raise PolicyBlock(f"repository file exceeds bounded manifest contract: {path}")
    try:
        raw = base64.b64decode("".join(encoded.split()), validate=True)
        text = raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise PolicyBlock(f"repository file is not canonical UTF-8/base64: {path}") from exc
    if len(raw) != size or not text or "\x00" in text:
        raise PolicyBlock(f"repository file identity/size contract failed: {path}")
    return text


def _canonical_dependency_name(raw: str, *, context: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise PolicyBlock(f"{context} contains an invalid dependency declaration")
    lowered = raw.lower()
    if any(token in lowered for token in ("@", ";", "://", "git+", "file:", "../", "./")):
        raise PolicyBlock(f"{context} introduces URL/VCS/path/marker authority: {raw}")
    match = DEPENDENCY_NAME.match(raw.strip())
    if match is None:
        raise PolicyBlock(f"{context} contains an unparseable dependency declaration: {raw}")
    remainder = raw.strip()[match.end() :].lstrip()
    if remainder.startswith("["):
        close = remainder.find("]")
        if close <= 1:
            raise PolicyBlock(f"{context} contains malformed dependency extras: {raw}")
        remainder = remainder[close + 1 :].lstrip()
    if remainder and remainder[0] not in "<>=!~":
        raise PolicyBlock(f"{context} contains unsupported dependency syntax: {raw}")
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


def _dependency_map(values: Any, *, context: str) -> dict[str, str]:
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise PolicyBlock(f"{context} must be a string list")
    result: dict[str, str] = {}
    for raw in values:
        name = _canonical_dependency_name(raw, context=context)
        if name in result:
            raise PolicyBlock(f"{context} contains duplicate dependency identity: {name}")
        result[name] = raw
    return result


def _validate_same_dependency_identities(before: Any, after: Any, *, context: str) -> bool:
    old = _dependency_map(before, context=context)
    new = _dependency_map(after, context=context)
    if set(old) != set(new):
        raise PolicyBlock(f"{context} dependency identities changed; add/remove/rename requires review")
    return old != new


def validate_pyproject_dependency_semantics(before_text: str, after_text: str) -> None:
    try:
        before = tomllib.loads(before_text)
        after = tomllib.loads(after_text)
    except tomllib.TOMLDecodeError as exc:
        raise PolicyBlock(f"pyproject.toml is not valid TOML: {exc}") from exc
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise PolicyBlock("pyproject.toml root must be a table")

    before_control = copy.deepcopy(before)
    after_control = copy.deepcopy(after)
    changed = False

    for original, control, label in (
        (before, before_control, "before"),
        (after, after_control, "after"),
    ):
        project = original.get("project")
        build = original.get("build-system")
        control_project = control.get("project")
        control_build = control.get("build-system")
        if not all(isinstance(item, dict) for item in (project, build, control_project, control_build)):
            raise PolicyBlock(f"{label} pyproject lacks project/build-system tables")
        control_project["dependencies"] = []
        optional = project.get("optional-dependencies", {})
        control_optional = control_project.get("optional-dependencies", {})
        if not isinstance(optional, dict) or not isinstance(control_optional, dict):
            raise PolicyBlock(f"{label} optional-dependencies must be a table")
        control_project["optional-dependencies"] = {key: [] for key in sorted(optional)}
        control_build["requires"] = []

    if before_control != after_control:
        raise PolicyBlock("pyproject change includes non-dependency semantic authority")

    before_project = before["project"]
    after_project = after["project"]
    changed |= _validate_same_dependency_identities(
        before_project.get("dependencies", []),
        after_project.get("dependencies", []),
        context="project.dependencies",
    )

    before_optional = before_project.get("optional-dependencies", {})
    after_optional = after_project.get("optional-dependencies", {})
    if set(before_optional) != set(after_optional):
        raise PolicyBlock("optional dependency group identities changed")
    for group in sorted(before_optional):
        changed |= _validate_same_dependency_identities(
            before_optional[group],
            after_optional[group],
            context=f"project.optional-dependencies.{group}",
        )

    changed |= _validate_same_dependency_identities(
        before["build-system"].get("requires", []),
        after["build-system"].get("requires", []),
        context="build-system.requires",
    )
    if not changed:
        raise PolicyBlock("pyproject dependency update contains no dependency-spec change")


def validate_pip_semantics(
    api: GitHubApi,
    files: list[dict[str, Any]],
    base_sha: str,
    head_sha: str,
    config: dict[str, Any],
) -> None:
    allowed = set(config["pipManifestPaths"])
    paths = {str(row["filename"]) for row in files}
    if paths != allowed:
        raise PolicyBlock(f"pip update must change exactly {sorted(allowed)}; got {sorted(paths)}")
    for row in files:
        if row.get("status") != "modified":
            raise PolicyBlock("pip manifest must be modified in place")
    path = config["pipManifestPaths"][0]
    before = _repo_text_at_sha(api, path, base_sha)
    after = _repo_text_at_sha(api, path, head_sha)
    validate_pyproject_dependency_semantics(before, after)


def validate_change_semantics(
    api: GitHubApi,
    files: list[dict[str, Any]],
    base_sha: str,
    head_sha: str,
    config: dict[str, Any],
) -> str:
    paths = [str(row["filename"]) for row in files]
    if paths and all(
        path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))
        for path in paths
    ):
        validate_action_semantics(files)
        return "github-actions"
    if config["pipMode"] == "exact-subject-green" and set(paths) == set(config["pipManifestPaths"]):
        validate_pip_semantics(api, files, base_sha, head_sha, config)
        return "pip"
    raise PolicyBlock("mixed or unsupported dependency change set requires manual review")
'''
if marker not in text:
    raise SystemExit('verify_merge_subject marker not found')
text = text.replace(marker, insert + marker, 1)

text = text.replace(
    '    files = changed_files(api, number, config)\n'
    '    validate_action_semantics(files)\n'
    '    merge_sha = verify_merge_subject(api, pr, number, head_sha, base_sha)\n',
    '    files = changed_files(api, number, config)\n'
    '    ecosystem = validate_change_semantics(api, files, base_sha, head_sha, config)\n'
    '    merge_sha = verify_merge_subject(api, pr, number, head_sha, base_sha)\n',
    1,
)
text = text.replace(
    '        "mergeSha": merge_sha,\n'
    '        "files": [str(row["filename"]) for row in files],\n',
    '        "mergeSha": merge_sha,\n'
    '        "ecosystem": ecosystem,\n'
    '        "files": [str(row["filename"]) for row in files],\n',
    1,
)

old_major_test = '''    try:\n        validate_action_semantics(\n            [\n                {\n                    "filename": ".github/workflows/ci.yml",\n                    "status": "modified",\n                    "patch": "@@ -1 +1 @@\\n-      - uses: actions/checkout@"\n                    + "a" * 40\n                    + " # v7.0.1\\n"\n                    "+      - uses: actions/checkout@" + "b" * 40 + " # v8.0.0\\n",\n                }\n            ]\n        )\n    except PolicyBlock:\n        pass\n    else:\n        raise GovernanceError("semantic validator accepted action major update")\n'''
new_major_test = '''    validate_action_semantics(\n        [\n            {\n                "filename": ".github/workflows/ci.yml",\n                "status": "modified",\n                "patch": "@@ -1 +1 @@\\n-      - uses: actions/checkout@"\n                + "a" * 40\n                + " # v7.0.1\\n"\n                "+      - uses: actions/checkout@" + "b" * 40 + " # v8.0.0\\n",\n            }\n        ]\n    )\n\n    base_manifest = """[build-system]\nrequires = [\"hatchling==1.32.0\"]\nbuild-backend = \"hatchling.build\"\n[project]\nname = \"example\"\nversion = \"1.0.0\"\ndependencies = [\"alpha>=1,<2\"]\n[project.optional-dependencies]\ndev = [\"beta==2.0.0\"]\n"""\n    major_manifest = base_manifest.replace(\"alpha>=1,<2\", \"alpha>=2,<3\")\n    validate_pyproject_dependency_semantics(base_manifest, major_manifest)\n    for unsafe in (\n        base_manifest.replace('version = \"1.0.0\"', 'version = \"2.0.0\"'),\n        base_manifest.replace('[\"alpha>=1,<2\"]', '[\"alpha>=1,<2\", \"gamma>=1\"]'),\n        base_manifest.replace('alpha>=1,<2', 'alpha @ https://example.invalid/pkg.whl'),\n        base_manifest.replace('alpha>=1,<2', 'alpha>=1,<2; python_version >= \"3.12\"'),\n    ):\n        try:\n            validate_pyproject_dependency_semantics(base_manifest, unsafe)\n        except PolicyBlock:\n            pass\n        else:\n            raise GovernanceError(\"pip semantic validator accepted authority expansion\")\n'''
if old_major_test not in text:
    raise SystemExit('major self-test block not found')
text = text.replace(old_major_test, new_major_test, 1)

controller.write_text(text, encoding='utf-8')

config = Path('.github/dependency-governance.json')
config_text = config.read_text(encoding='utf-8')
config_text = config_text.replace('"pipMode": "manual",', '"pipMode": "exact-subject-green",\n  "pipManifestPaths": [\n    "pyproject.toml"\n  ],', 1)
config_text = config_text.replace(
    '    "version-update:semver-minor",\n    "security-update:semver-patch",',
    '    "version-update:semver-minor",\n    "version-update:semver-major",\n    "security-update:semver-patch",',
    1,
)
config_text = config_text.replace(
    '    "security-update:semver-minor"\n',
    '    "security-update:semver-minor",\n    "security-update:semver-major"\n',
    1,
)
config.write_text(config_text, encoding='utf-8')

doc = Path('docs/DEPENDABOT_AUTOMATION.md')
doc_text = doc.read_text(encoding='utf-8')
doc_text = doc_text.replace(
    'Autonomous merge is restricted to GitHub Actions patch/minor updates generated by the canonical Dependabot identity. Governance requires a current `main` base, repository-owned head, verified Dependabot commit provenance, a one-for-one immutable action-SHA-only workflow diff, an exact prospective merge subject, and green `ci-gate` plus `CodeQL` checks on the exact head.\n\nControl-plane changes, major action updates, arbitrary workflow edits, manual-review labels, stale PRs, and Python dependency changes remain manual. Dependabot uses native rebasing; governance does not call the update-branch API.',
    'Autonomous merge covers canonical Dependabot Python and GitHub Actions version/security updates, including major versions, only after exact-subject qualification. Governance requires a current `main` base, repository-owned head, verified Dependabot commit provenance, an exact prospective merge subject, and green `ci-gate` plus `CodeQL` checks on the exact head.\n\nGitHub Actions changes must be one-for-one immutable action-SHA replacements for the same action identity and an advancing semantic version; arbitrary workflow edits remain blocked. Python changes must modify only `pyproject.toml` dependency specifications: package identities and optional-dependency groups must remain unchanged, additions/removals/renames are rejected, direct URL/VCS/path/marker authority is rejected, and every non-dependency TOML semantic must remain identical. The CI matrix installs the candidate `pyproject.toml` graph on Python 3.11-3.14 and `ci-gate` aggregates the behavioral, typing, security, packaging, mutation, OpenAI, and MCP evidence before merge.\n\nGovernance/recovery/workflow control-plane files, manual-review labels, stale PRs, and mixed-ecosystem diffs remain fail-closed. Dependabot uses native rebasing; governance does not call the update-branch API.',
    1,
)
doc.write_text(doc_text, encoding='utf-8')

print('patched autonomous dependency governance')
