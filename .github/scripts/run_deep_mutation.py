from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION: Final = 1
MUTATION_TOOL: Final = "mutmut"
MUTATION_TOOL_VERSION: Final = "3.8.0"
MINIMUM_ALLOWED_SCORE: Final = 95.0
_REQUIRED_CAMPAIGNS: Final = frozenset(
    {
        "authority",
        "preconditions",
        "evaluator",
        "deterministic-oracles",
        "attack-delivery-receipt",
        "retrieval-receipt",
        "semantic-receipt",
        "side-effect-receipt",
        "evidence-store",
        "release-gate",
    }
)
_MUTMUT_SECTION = re.compile(r"(?ms)^\[tool\.mutmut\]\n.*?(?=^\[[^\n]+\]\n|\Z)")
_CAMPAIGN_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class DeepMutationPolicyError(ValueError):
    """The checked-in deep mutation contract is malformed or incomplete."""


@dataclass(frozen=True, slots=True)
class Campaign:
    campaign_id: str
    surface: str
    sources: tuple[str, ...]
    tests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeepMutationManifest:
    minimum_score: float
    max_children: int
    campaign_timeout_seconds: int
    campaigns: tuple[Campaign, ...]


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _exact_string_list(value: object, *, label: str) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise DeepMutationPolicyError(f"{label} must be a non-empty exact JSON array")
    result: list[str] = []
    for entry in value:
        if type(entry) is not str or not entry:
            raise DeepMutationPolicyError(f"{label} entries must be non-empty exact strings")
        result.append(entry)
    if len(result) != len(set(result)):
        raise DeepMutationPolicyError(f"{label} must not contain duplicates")
    return tuple(result)


def load_manifest(path: Path, *, repository_root: Path | None = None) -> DeepMutationManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DeepMutationPolicyError(f"deep mutation manifest is missing: {path}") from exc
    except (UnicodeError, json.JSONDecodeError, OSError) as exc:
        raise DeepMutationPolicyError(f"cannot read deep mutation manifest {path}: {exc}") from exc

    if type(payload) is not dict:
        raise DeepMutationPolicyError("deep mutation manifest root must be an exact JSON object")
    expected_root = {
        "schema_version",
        "tool",
        "minimum_score",
        "max_children",
        "campaign_timeout_seconds",
        "campaigns",
    }
    if set(payload) != expected_root:
        raise DeepMutationPolicyError("deep mutation manifest root schema does not match policy")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != SCHEMA_VERSION:
        raise DeepMutationPolicyError(f"schema_version must be exact integer {SCHEMA_VERSION}")

    tool = payload["tool"]
    if type(tool) is not dict or set(tool) != {"name", "version"}:
        raise DeepMutationPolicyError("tool must contain exactly name and version")
    if tool["name"] != MUTATION_TOOL or tool["version"] != MUTATION_TOOL_VERSION:
        raise DeepMutationPolicyError(
            f"mutation tool must be exactly {MUTATION_TOOL} {MUTATION_TOOL_VERSION}"
        )

    minimum_score = payload["minimum_score"]
    if type(minimum_score) not in (int, float):
        raise DeepMutationPolicyError("minimum_score must be an exact JSON number")
    minimum_score = float(minimum_score)
    if not MINIMUM_ALLOWED_SCORE <= minimum_score <= 100.0:
        raise DeepMutationPolicyError(
            f"minimum_score must be between {MINIMUM_ALLOWED_SCORE:.2f} and 100.00"
        )

    max_children = payload["max_children"]
    if type(max_children) is not int or not 1 <= max_children <= 4:
        raise DeepMutationPolicyError("max_children must be an exact integer between 1 and 4")

    timeout_seconds = payload["campaign_timeout_seconds"]
    if type(timeout_seconds) is not int or not 60 <= timeout_seconds <= 1800:
        raise DeepMutationPolicyError(
            "campaign_timeout_seconds must be an exact integer between 60 and 1800"
        )

    raw_campaigns = payload["campaigns"]
    if type(raw_campaigns) is not list or not raw_campaigns:
        raise DeepMutationPolicyError("campaigns must be a non-empty exact JSON array")

    campaigns: list[Campaign] = []
    campaign_ids: set[str] = set()
    for index, raw_campaign in enumerate(raw_campaigns):
        label = f"campaigns[{index}]"
        if type(raw_campaign) is not dict or set(raw_campaign) != {
            "id",
            "surface",
            "sources",
            "tests",
        }:
            raise DeepMutationPolicyError(f"{label} schema does not match policy")
        campaign_id = raw_campaign["id"]
        surface = raw_campaign["surface"]
        if type(campaign_id) is not str or not _CAMPAIGN_ID.fullmatch(campaign_id):
            raise DeepMutationPolicyError(f"{label}.id is not canonical kebab-case")
        if campaign_id in campaign_ids:
            raise DeepMutationPolicyError(f"duplicate campaign id: {campaign_id}")
        campaign_ids.add(campaign_id)
        if type(surface) is not str or not surface.strip():
            raise DeepMutationPolicyError(f"{label}.surface must be a non-empty exact string")

        sources = _exact_string_list(raw_campaign["sources"], label=f"{label}.sources")
        tests = _exact_string_list(raw_campaign["tests"], label=f"{label}.tests")
        for source in sources:
            if not source.startswith("src/agent_evals/") or not source.endswith(".py"):
                raise DeepMutationPolicyError(
                    f"source is outside agent_evals Python code: {source}"
                )
            if source.startswith("src/agent_evals/adapters/openai_"):
                raise DeepMutationPolicyError(
                    f"provider adapter is outside deterministic deep-mutation scope: {source}"
                )
        for test in tests:
            if not test.startswith("tests/") or not test.endswith(".py"):
                raise DeepMutationPolicyError(f"test is outside the repository test tree: {test}")

        campaigns.append(
            Campaign(
                campaign_id=campaign_id,
                surface=surface,
                sources=sources,
                tests=tests,
            )
        )

    if campaign_ids != _REQUIRED_CAMPAIGNS:
        missing = sorted(_REQUIRED_CAMPAIGNS - campaign_ids)
        unexpected = sorted(campaign_ids - _REQUIRED_CAMPAIGNS)
        raise DeepMutationPolicyError(
            f"deep mutation campaign set mismatch: missing={missing}, unexpected={unexpected}"
        )

    if repository_root is not None:
        for campaign in campaigns:
            for relative_path in (*campaign.sources, *campaign.tests):
                if not (repository_root / relative_path).is_file():
                    raise DeepMutationPolicyError(
                        f"campaign {campaign.campaign_id} references missing file {relative_path}"
                    )

    return DeepMutationManifest(
        minimum_score=minimum_score,
        max_children=max_children,
        campaign_timeout_seconds=timeout_seconds,
        campaigns=tuple(campaigns),
    )


def render_mutmut_section(campaign: Campaign) -> str:
    sources = json.dumps(list(campaign.sources), ensure_ascii=True)
    tests = json.dumps(list(campaign.tests), ensure_ascii=True)
    return (
        "[tool.mutmut]\n"
        'source_paths = ["src/agent_evals"]\n'
        f"only_mutate = {sources}\n"
        f"pytest_add_cli_args_test_selection = {tests}\n"
        'process_isolation = "fork"\n\n'
    )


def replace_mutmut_section(pyproject_text: str, campaign: Campaign) -> str:
    matches = tuple(_MUTMUT_SECTION.finditer(pyproject_text))
    if len(matches) != 1:
        raise DeepMutationPolicyError(
            f"pyproject.toml must contain exactly one [tool.mutmut] section; observed {len(matches)}"
        )
    return _MUTMUT_SECTION.sub(render_mutmut_section(campaign), pyproject_text, count=1)


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def run_command(
    args: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=_text(exc.stdout),
            stderr=_text(exc.stderr) + f"\ncommand timed out after {timeout_seconds} seconds\n",
            timed_out=True,
        )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def survivor_names(results_text: str) -> tuple[str, ...]:
    survivors: list[str] = []
    for line in results_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == "survived":
            mutant = parts[0].removesuffix(":")
            if mutant:
                survivors.append(mutant)
    return tuple(survivors)


def _write_command_log(path: Path, command: list[str], result: CommandResult) -> None:
    path.write_text(
        "command: "
        + " ".join(command)
        + f"\nreturncode: {result.returncode}\ntimed_out: {str(result.timed_out).lower()}\n"
        + "\n--- stdout ---\n"
        + result.stdout
        + "\n--- stderr ---\n"
        + result.stderr,
        encoding="utf-8",
    )


def _load_counts(path: Path) -> dict[str, int] | None:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    if type(payload) is not dict:
        return None
    counts: dict[str, int] = {}
    for key, value in payload.items():
        if type(key) is not str or type(value) is not int:
            return None
        counts[key] = value
    return counts


def _score(counts: dict[str, int] | None) -> float | None:
    if counts is None:
        return None
    killed = counts.get("killed")
    total = counts.get("total")
    if type(killed) is not int or type(total) is not int or total <= 0:
        return None
    return killed * 100.0 / total


def _campaign_summary(
    campaign: Campaign,
    *,
    minimum_score: float,
    counts: dict[str, int] | None,
    passed: bool,
    run_result: CommandResult,
    export_result: CommandResult,
    results_result: CommandResult,
    gate_result: CommandResult,
) -> dict[str, object]:
    return {
        "campaign_id": campaign.campaign_id,
        "surface": campaign.surface,
        "sources": list(campaign.sources),
        "tests": list(campaign.tests),
        "minimum_score": minimum_score,
        "score": _score(counts),
        "counts": counts,
        "passed": passed,
        "mutmut_run_exit_code": run_result.returncode,
        "mutmut_run_timed_out": run_result.timed_out,
        "export_exit_code": export_result.returncode,
        "results_exit_code": results_result.returncode,
        "policy_gate_exit_code": gate_result.returncode,
    }


def run_deep_mutation(
    *,
    repository_root: Path,
    manifest_path: Path,
    output_dir: Path,
) -> int:
    manifest_bytes = manifest_path.read_bytes()
    manifest = load_manifest(manifest_path, repository_root=repository_root)
    installed_version = importlib.metadata.version(MUTATION_TOOL)
    if installed_version != MUTATION_TOOL_VERSION:
        raise DeepMutationPolicyError(
            f"installed {MUTATION_TOOL} version {installed_version} does not match "
            f"required {MUTATION_TOOL_VERSION}"
        )

    commit_result = run_command(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, timeout_seconds=30
    )
    if commit_result.returncode != 0:
        raise DeepMutationPolicyError(f"cannot resolve exact git commit: {commit_result.stderr}")
    commit_sha = commit_result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise DeepMutationPolicyError(f"git returned noncanonical commit SHA {commit_sha!r}")

    pyproject_path = repository_root / "pyproject.toml"
    original_pyproject = pyproject_path.read_text(encoding="utf-8")
    output_dir = output_dir.resolve()
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True)
    (output_dir / "manifest.json").write_bytes(manifest_bytes)

    summaries: list[dict[str, object]] = []
    all_passed = True
    try:
        for campaign in manifest.campaigns:
            campaign_dir = output_dir / campaign.campaign_id
            campaign_dir.mkdir()
            shutil.rmtree(repository_root / "mutants", ignore_errors=True)

            generated_pyproject = replace_mutmut_section(original_pyproject, campaign)
            pyproject_path.write_text(generated_pyproject, encoding="utf-8")
            (campaign_dir / "generated-pyproject.toml").write_text(
                generated_pyproject, encoding="utf-8"
            )

            run_args = ["mutmut", "run", "--max-children", str(manifest.max_children)]
            run_result = run_command(
                run_args,
                cwd=repository_root,
                timeout_seconds=manifest.campaign_timeout_seconds,
            )
            _write_command_log(campaign_dir / "mutmut-run.log", run_args, run_result)
            exit_file = campaign_dir / "mutation-run-exit-code.txt"
            exit_file.write_text(f"{run_result.returncode}\n", encoding="ascii")

            export_args = ["mutmut", "export-cicd-stats"]
            export_result = run_command(export_args, cwd=repository_root, timeout_seconds=60)
            _write_command_log(campaign_dir / "mutmut-export.log", export_args, export_result)

            source_stats = repository_root / "mutants" / "mutmut-cicd-stats.json"
            retained_stats = campaign_dir / "mutmut-cicd-stats.json"
            if source_stats.is_file():
                shutil.copyfile(source_stats, retained_stats)

            results_args = ["mutmut", "results"]
            results_result = run_command(results_args, cwd=repository_root, timeout_seconds=60)
            _write_command_log(campaign_dir / "mutmut-results.log", results_args, results_result)
            results_text = results_result.stdout + results_result.stderr
            (campaign_dir / "mutation-results.txt").write_text(results_text, encoding="utf-8")

            survivor_report: list[str] = []
            for survivor in survivor_names(results_text):
                show_args = ["mutmut", "show", survivor]
                show_result = run_command(show_args, cwd=repository_root, timeout_seconds=30)
                survivor_report.append(
                    f"===== {survivor} =====\n"
                    + show_result.stdout
                    + ("\n" + show_result.stderr if show_result.stderr else "")
                )
            (campaign_dir / "survivor-diffs.txt").write_text(
                "\n".join(survivor_report), encoding="utf-8"
            )

            gate_args = [
                sys.executable,
                ".github/scripts/check_mutation_score.py",
                str(retained_stats),
                "--run-exit-code-file",
                str(exit_file),
            ]
            gate_result = run_command(gate_args, cwd=repository_root, timeout_seconds=60)
            _write_command_log(campaign_dir / "mutation-policy.log", gate_args, gate_result)

            counts = _load_counts(retained_stats)
            score = _score(counts)
            declared_threshold_passed = score is not None and score >= manifest.minimum_score
            if gate_result.returncode == 0 and not declared_threshold_passed:
                with (campaign_dir / "mutation-policy.log").open("a", encoding="utf-8") as handle:
                    handle.write(
                        "\ndeep mutation policy failed: declared campaign threshold "
                        f"{manifest.minimum_score:.2f}% not satisfied; observed={score!r}\n"
                    )

            passed = (
                run_result.returncode == 0
                and export_result.returncode == 0
                and results_result.returncode == 0
                and gate_result.returncode == 0
                and declared_threshold_passed
            )
            summaries.append(
                _campaign_summary(
                    campaign,
                    minimum_score=manifest.minimum_score,
                    counts=counts,
                    passed=passed,
                    run_result=run_result,
                    export_result=export_result,
                    results_result=results_result,
                    gate_result=gate_result,
                )
            )
            all_passed = all_passed and passed
    finally:
        pyproject_path.write_text(original_pyproject, encoding="utf-8")
        shutil.rmtree(repository_root / "mutants", ignore_errors=True)

    if pyproject_path.read_text(encoding="utf-8") != original_pyproject:
        raise DeepMutationPolicyError("pyproject.toml was not restored exactly after mutation runs")

    aggregate = {
        "schema_version": SCHEMA_VERSION,
        "commit_sha": commit_sha,
        "tool": {"name": MUTATION_TOOL, "version": installed_version},
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "minimum_score": manifest.minimum_score,
        "campaign_count": len(summaries),
        "all_passed": all_passed,
        "campaigns": summaries,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if all_passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run checked-in deep mutation campaigns with fail-closed evidence retention."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(".github/mutation/deep_targets.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("deep-mutation-results"),
    )
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[2]
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = repository_root / manifest_path
    output_dir = args.output
    if not output_dir.is_absolute():
        output_dir = repository_root / output_dir

    try:
        return run_deep_mutation(
            repository_root=repository_root,
            manifest_path=manifest_path,
            output_dir=output_dir,
        )
    except DeepMutationPolicyError as exc:
        parser.exit(1, f"deep mutation policy failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
