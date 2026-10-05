from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import quote

import package_artifact_manifest as package_manifest

EVIDENCE_SCHEMA = "agent-evals/release-supply-chain-evidence/v1"
POLICY_SCHEMA = "agent-evals/dependency-license-policy/v1"
SPDX_VERSION = "SPDX-2.3"
SBOM_NAME = "release-sbom.spdx.json"
EVIDENCE_NAME = "release-supply-chain-evidence.json"
PROJECT_NAME = "qa-automation-ai-agent-evals"

_LICENSE_CLASSIFIERS = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: BSD License": "BSD-2-Clause OR BSD-3-Clause",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
}
_LICENSE_ALIASES = {
    "MIT": "MIT",
    "MIT License": "MIT",
    "Apache-2.0": "Apache-2.0",
    "Apache Software License": "Apache-2.0",
    "BSD-2-Clause": "BSD-2-Clause",
    "BSD-3-Clause": "BSD-3-Clause",
    "ISC": "ISC",
    "ISC License": "ISC",
    "PSF-2.0": "PSF-2.0",
    "Python-2.0": "Python-2.0",
    "MPL-2.0": "MPL-2.0",
}
_LICENSE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")


class SupplyChainError(ValueError):
    """Release supply-chain evidence failed closed verification."""


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SupplyChainError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise SupplyChainError(f"non-finite JSON number is not allowed: {value}")


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SupplyChainError(f"{label} must be a regular file")
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SupplyChainError(f"{label} is not valid UTF-8 JSON") from exc
    if type(value) is not dict:
        raise SupplyChainError(f"{label} root must be an object")
    if raw != _canonical_bytes(value):
        raise SupplyChainError(f"{label} JSON is not canonical")
    return value


def _exact_keys(value: dict[str, Any], keys: set[str], *, label: str) -> None:
    if set(value) != keys:
        raise SupplyChainError(f"{label} keys do not match the versioned contract")


def _context(
    *,
    repository: str,
    commit_sha: str,
    workflow: str,
    run_id: int,
    run_attempt: int,
) -> dict[str, object]:
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise SupplyChainError("repository must be canonical owner/name text")
    if re.fullmatch(r"[0-9a-f]{40}", commit_sha) is None:
        raise SupplyChainError("commit_sha must be a lowercase 40-character Git SHA")
    if not workflow or workflow != workflow.strip() or len(workflow) > 256:
        raise SupplyChainError("workflow must be trimmed non-empty text <= 256 chars")
    if type(run_id) is not int or run_id < 1:
        raise SupplyChainError("run_id must be an integer >= 1")
    if type(run_attempt) is not int or run_attempt < 1:
        raise SupplyChainError("run_attempt must be an integer >= 1")
    return {
        "repository": repository,
        "commit_sha": commit_sha,
        "workflow": workflow,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }


def _artifact_binding(package_dir: Path, source: dict[str, object]) -> tuple[str, str]:
    package_manifest.verify_manifest(
        package_dir,
        repository=str(source["repository"]),
        commit_sha=str(source["commit_sha"]),
        workflow=str(source["workflow"]),
        run_id=int(source["run_id"]),
        run_attempt=int(source["run_attempt"]),
    )
    manifest_path = package_dir / "artifact-manifest.json"
    manifest = package_manifest._load_manifest(manifest_path)
    wheel = next(
        item
        for item in manifest["artifacts"]
        if type(item) is dict and item.get("kind") == "wheel"
    )
    return _sha256(manifest_path), str(wheel["sha256"])


def _policy(path: Path) -> tuple[dict[str, Any], str]:
    policy = _load_json(path, label="dependency license policy")
    _exact_keys(
        policy,
        {
            "schema_version",
            "allowed_spdx_licenses",
            "denied_spdx_licenses",
            "allow_license_refs",
        },
        label="dependency license policy",
    )
    if policy["schema_version"] != POLICY_SCHEMA:
        raise SupplyChainError("unsupported dependency license policy schema")
    allowed = policy["allowed_spdx_licenses"]
    denied = policy["denied_spdx_licenses"]
    for label, values in (("allowed", allowed), ("denied", denied)):
        if (
            type(values) is not list
            or any(type(item) is not str or not item for item in values)
            or values != sorted(set(values))
        ):
            raise SupplyChainError(f"{label} license list must be sorted unique strings")
    if not allowed or set(allowed) & set(denied):
        raise SupplyChainError("license policy allow/deny sets are invalid")
    if type(policy["allow_license_refs"]) is not bool:
        raise SupplyChainError("allow_license_refs must be boolean")
    return policy, _sha256(path)


def _declared_license(dist: metadata.Distribution) -> str:
    expression = dist.metadata.get("License-Expression")
    if expression and expression.strip():
        return expression.strip()
    for classifier in dist.metadata.get_all("Classifier", []):
        mapped = _LICENSE_CLASSIFIERS.get(classifier)
        if mapped is not None:
            return mapped
    raw = dist.metadata.get("License")
    if raw:
        mapped = _LICENSE_ALIASES.get(raw.strip())
        if mapped is not None:
            return mapped
    return "NOASSERTION"


def _check_license(expression: str, policy: dict[str, Any], package: str) -> None:
    tokens = {
        token
        for token in _LICENSE_TOKEN.findall(expression)
        if token.upper() not in {"AND", "OR", "WITH"}
    }
    if not tokens or expression in {"NOASSERTION", "NONE"}:
        raise SupplyChainError(f"dependency license is unknown for {package}")
    if any(token.startswith("LicenseRef-") for token in tokens) and not policy["allow_license_refs"]:
        raise SupplyChainError(f"LicenseRef is not allowed for {package}")
    denied = set(policy["denied_spdx_licenses"])
    blocked = sorted(tokens & denied)
    if blocked:
        raise SupplyChainError(f"dependency license denied for {package}: {blocked}")
    allowed = set(policy["allowed_spdx_licenses"])
    unknown = sorted(
        token
        for token in tokens
        if not token.startswith("LicenseRef-") and token not in allowed
    )
    if unknown:
        raise SupplyChainError(f"dependency license is not allowlisted for {package}: {unknown}")


def _closure(root_name: str) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    try:
        from packaging.markers import default_environment
        from packaging.requirements import InvalidRequirement, Requirement
    except ImportError as exc:
        raise SupplyChainError("packaging is required for runtime dependency resolution") from exc
    installed: dict[str, metadata.Distribution] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            installed[_canonical_name(name)] = dist
    root = _canonical_name(root_name)
    if root not in installed:
        raise SupplyChainError(f"installed root distribution not found: {root_name}")
    env = default_environment()
    env["extra"] = ""
    queue = [root]
    seen: set[str] = set()
    records: dict[str, dict[str, str]] = {}
    edges: set[tuple[str, str]] = set()
    while queue:
        name = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)
        dist = installed.get(name)
        if dist is None:
            raise SupplyChainError(f"required installed distribution is missing: {name}")
        records[name] = {
            "name": name,
            "version": dist.version,
            "license": _declared_license(dist),
        }
        for raw in dist.requires or []:
            try:
                requirement = Requirement(raw)
            except InvalidRequirement as exc:
                raise SupplyChainError(f"invalid installed requirement for {name}: {raw!r}") from exc
            if requirement.marker is not None and not requirement.marker.evaluate(env):
                continue
            dependency = _canonical_name(requirement.name)
            target = installed.get(dependency)
            if target is None:
                raise SupplyChainError(f"runtime dependency is not installed: {dependency}")
            if requirement.specifier and target.version not in requirement.specifier:
                raise SupplyChainError(
                    f"installed dependency version violates requirement: {dependency}"
                )
            edges.add((name, dependency))
            if dependency not in seen:
                queue.append(dependency)
    return [records[name] for name in sorted(records)], sorted(edges)


def _spdx_id(name: str) -> str:
    return "SPDXRef-Package-" + re.sub(r"[^A-Za-z0-9.-]", "-", name)


def _sbom(
    packages: list[dict[str, str]],
    edges: list[tuple[str, str]],
    *,
    source: dict[str, object],
    artifact_manifest_sha256: str,
    wheel_sha256: str,
    source_date_epoch: int,
) -> dict[str, Any]:
    if type(source_date_epoch) is not int or source_date_epoch < 1:
        raise SupplyChainError("source_date_epoch must be an integer >= 1")
    root = _canonical_name(PROJECT_NAME)
    by_name = {item["name"]: item for item in packages}
    if root not in by_name:
        raise SupplyChainError("runtime closure does not contain the project root")
    spdx_packages: list[dict[str, Any]] = []
    for item in packages:
        entry: dict[str, Any] = {
            "SPDXID": _spdx_id(item["name"]),
            "name": item["name"],
            "versionInfo": item["version"],
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": item["license"],
            "licenseDeclared": item["license"],
            "copyrightText": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": (
                        f"pkg:pypi/{quote(item['name'], safe='.-')}@"
                        f"{quote(item['version'], safe='.+-')}"
                    ),
                }
            ],
        }
        if item["name"] == root:
            entry["checksums"] = [{"algorithm": "SHA256", "checksumValue": wheel_sha256}]
        spdx_packages.append(entry)
    relationships = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": _spdx_id(root),
        },
        *[
            {
                "spdxElementId": _spdx_id(parent),
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": _spdx_id(child),
            }
            for parent, child in edges
        ],
    ]
    created = datetime.fromtimestamp(
        source_date_epoch, tz=UTC
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{PROJECT_NAME}-{by_name[root]['version']}-runtime",
        "documentNamespace": (
            f"https://github.com/{source['repository']}/spdx/"
            f"{source['commit_sha']}/{artifact_manifest_sha256}"
        ),
        "creationInfo": {
            "created": created,
            "creators": ["Tool: agent-evals-release-supply-chain/v1"],
        },
        "packages": spdx_packages,
        "relationships": relationships,
    }


def create(
    package_dir: Path,
    evidence_dir: Path,
    policy_path: Path,
    *,
    repository: str,
    commit_sha: str,
    workflow: str,
    run_id: int,
    run_attempt: int,
    source_date_epoch: int,
) -> None:
    source = _context(
        repository=repository,
        commit_sha=commit_sha,
        workflow=workflow,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    manifest_digest, wheel_digest = _artifact_binding(package_dir, source)
    policy, policy_digest = _policy(policy_path)
    packages, edges = _closure(PROJECT_NAME)
    for item in packages:
        _check_license(item["license"], policy, item["name"])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    sbom_path = evidence_dir / SBOM_NAME
    sbom_path.write_bytes(
        _canonical_bytes(
            _sbom(
                packages,
                edges,
                source=source,
                artifact_manifest_sha256=manifest_digest,
                wheel_sha256=wheel_digest,
                source_date_epoch=source_date_epoch,
            )
        )
    )
    evidence = {
        "schema_version": EVIDENCE_SCHEMA,
        "source": source,
        "package_artifact_manifest": {
            "filename": "artifact-manifest.json",
            "sha256": manifest_digest,
        },
        "sbom": {
            "filename": SBOM_NAME,
            "sha256": _sha256(sbom_path),
            "spdx_version": SPDX_VERSION,
        },
        "license_policy": {
            "schema_version": POLICY_SCHEMA,
            "sha256": policy_digest,
        },
        "runtime": {
            "root_package": _canonical_name(PROJECT_NAME),
            "package_count": len(packages),
            "packages": packages,
        },
        "license_verdict": {
            "status": "PASS",
            "denied_or_unknown_packages": [],
        },
    }
    (evidence_dir / EVIDENCE_NAME).write_bytes(_canonical_bytes(evidence))


def verify(
    package_dir: Path,
    evidence_dir: Path,
    policy_path: Path,
    *,
    repository: str,
    commit_sha: str,
    workflow: str,
    run_id: int,
    run_attempt: int,
) -> None:
    expected = _context(
        repository=repository,
        commit_sha=commit_sha,
        workflow=workflow,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    manifest_digest, wheel_digest = _artifact_binding(package_dir, expected)
    policy, policy_digest = _policy(policy_path)
    evidence = _load_json(evidence_dir / EVIDENCE_NAME, label="supply-chain evidence")
    _exact_keys(
        evidence,
        {
            "schema_version",
            "source",
            "package_artifact_manifest",
            "sbom",
            "license_policy",
            "runtime",
            "license_verdict",
        },
        label="supply-chain evidence",
    )
    if evidence["schema_version"] != EVIDENCE_SCHEMA:
        raise SupplyChainError("unsupported supply-chain evidence schema")
    source = evidence["source"]
    if type(source) is not dict:
        raise SupplyChainError("supply-chain evidence source must be an object")
    for key in ("repository", "commit_sha", "workflow", "run_id"):
        if source.get(key) != expected[key]:
            raise SupplyChainError(f"supply-chain evidence source mismatch for {key}")
    attempt = source.get("run_attempt")
    if type(attempt) is not int or attempt < 1 or attempt > int(expected["run_attempt"]):
        raise SupplyChainError("supply-chain evidence run attempt is invalid")
    if evidence["package_artifact_manifest"] != {
        "filename": "artifact-manifest.json",
        "sha256": manifest_digest,
    }:
        raise SupplyChainError("evidence does not bind the retained package manifest")
    if evidence["license_policy"] != {
        "schema_version": POLICY_SCHEMA,
        "sha256": policy_digest,
    }:
        raise SupplyChainError("evidence does not bind the checked-in license policy")
    sbom_ref = evidence["sbom"]
    if type(sbom_ref) is not dict:
        raise SupplyChainError("SBOM binding must be an object")
    _exact_keys(sbom_ref, {"filename", "sha256", "spdx_version"}, label="SBOM binding")
    sbom_path = evidence_dir / SBOM_NAME
    if (
        sbom_ref["filename"] != SBOM_NAME
        or sbom_ref["spdx_version"] != SPDX_VERSION
        or sbom_ref["sha256"] != _sha256(sbom_path)
    ):
        raise SupplyChainError("SBOM binding is invalid")
    sbom = _load_json(sbom_path, label="SPDX SBOM")
    _exact_keys(
        sbom,
        {
            "spdxVersion",
            "dataLicense",
            "SPDXID",
            "name",
            "documentNamespace",
            "creationInfo",
            "packages",
            "relationships",
        },
        label="SPDX SBOM",
    )
    if (
        sbom["spdxVersion"] != SPDX_VERSION
        or sbom["dataLicense"] != "CC0-1.0"
        or sbom["SPDXID"] != "SPDXRef-DOCUMENT"
        or sbom["documentNamespace"]
        != f"https://github.com/{repository}/spdx/{commit_sha}/{manifest_digest}"
    ):
        raise SupplyChainError("SPDX document identity/binding is invalid")
    packages, edges = _closure(PROJECT_NAME)
    for item in packages:
        _check_license(item["license"], policy, item["name"])
    expected_runtime = {
        "root_package": _canonical_name(PROJECT_NAME),
        "package_count": len(packages),
        "packages": packages,
    }
    if evidence["runtime"] != expected_runtime:
        raise SupplyChainError("runtime dependency closure does not match retained evidence")
    if evidence["license_verdict"] != {
        "status": "PASS",
        "denied_or_unknown_packages": [],
    }:
        raise SupplyChainError("license verdict is not a clean PASS")
    spdx_packages = sbom["packages"]
    if type(spdx_packages) is not list or len(spdx_packages) != len(packages):
        raise SupplyChainError("SPDX package set does not match runtime closure")
    expected_identity = {
        item["name"]: (item["version"], item["license"]) for item in packages
    }
    actual_identity: dict[str, tuple[str, str]] = {}
    root = _canonical_name(PROJECT_NAME)
    for item in spdx_packages:
        if type(item) is not dict:
            raise SupplyChainError("SPDX package entry must be an object")
        name = item.get("name")
        version = item.get("versionInfo")
        license_declared = item.get("licenseDeclared")
        if type(name) is not str or type(version) is not str or type(license_declared) is not str:
            raise SupplyChainError("SPDX package identity fields must be strings")
        canonical = _canonical_name(name)
        if canonical in actual_identity:
            raise SupplyChainError("SPDX package names must be unique")
        actual_identity[canonical] = (version, license_declared)
        if canonical == root and item.get("checksums") != [
            {"algorithm": "SHA256", "checksumValue": wheel_digest}
        ]:
            raise SupplyChainError("SPDX root package does not bind retained wheel digest")
    if actual_identity != expected_identity:
        raise SupplyChainError("SPDX package identities/licenses do not match runtime closure")
    expected_edges = {(_spdx_id(a), _spdx_id(b)) for a, b in edges}
    actual_edges = {
        (item.get("spdxElementId"), item.get("relatedSpdxElement"))
        for item in sbom["relationships"]
        if type(item) is dict and item.get("relationshipType") == "DEPENDS_ON"
    }
    if actual_edges != expected_edges:
        raise SupplyChainError("SPDX dependency relationships do not match runtime closure")


def self_test() -> None:
    policy = {
        "schema_version": POLICY_SCHEMA,
        "allowed_spdx_licenses": ["Apache-2.0", "BSD-3-Clause", "MIT"],
        "denied_spdx_licenses": ["AGPL-3.0-only"],
        "allow_license_refs": False,
    }
    _check_license("MIT OR Apache-2.0", policy, "allowed")
    for expression in ("NOASSERTION", "GPL-3.0-only", "AGPL-3.0-only", "LicenseRef-Proprietary"):
        try:
            _check_license(expression, policy, "rejected")
        except SupplyChainError:
            pass
        else:
            raise SupplyChainError(f"self-test accepted unsafe license: {expression}")
    if _canonical_bytes({"b": 2, "a": 1}) != b'{"a":1,"b":2}\n':
        raise SupplyChainError("canonical JSON self-test failed")
    try:
        json.loads('{"a":1,"a":2}', object_pairs_hook=_strict_object)
    except SupplyChainError:
        pass
    else:
        raise SupplyChainError("duplicate-key self-test failed")
    print("release supply-chain self-test: ok")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    for command in ("create", "verify"):
        item = sub.add_parser(command)
        item.add_argument("--package-dir", type=Path, required=True)
        item.add_argument("--evidence-dir", type=Path, required=True)
        item.add_argument("--policy", type=Path, required=True)
        item.add_argument("--repository", required=True)
        item.add_argument("--commit-sha", required=True)
        item.add_argument("--workflow", required=True)
        item.add_argument("--run-id", type=int, required=True)
        item.add_argument("--run-attempt", type=int, required=True)
        if command == "create":
            item.add_argument("--source-date-epoch", type=int, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "self-test":
            self_test()
        elif args.command == "create":
            create(
                args.package_dir,
                args.evidence_dir,
                args.policy,
                repository=args.repository,
                commit_sha=args.commit_sha,
                workflow=args.workflow,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
                source_date_epoch=args.source_date_epoch,
            )
            print(f"created {args.evidence_dir / SBOM_NAME} and {args.evidence_dir / EVIDENCE_NAME}")
        else:
            verify(
                args.package_dir,
                args.evidence_dir,
                args.policy,
                repository=args.repository,
                commit_sha=args.commit_sha,
                workflow=args.workflow,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
            )
            print(f"verified {args.evidence_dir / EVIDENCE_NAME}")
    except (SupplyChainError, package_manifest.ManifestError, OSError) as exc:
        raise SystemExit(f"release supply-chain verification failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
