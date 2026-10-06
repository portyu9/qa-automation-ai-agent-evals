"""Command-line operator surface for deterministic assurance workflows."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from pydantic import ValidationError

from agent_evals import operator

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_INTEGRITY = 4
EXIT_POLICY = 5

app = typer.Typer(add_completion=True, no_args_is_help=True)
scenario_app = typer.Typer(no_args_is_help=True)
session_app = typer.Typer(no_args_is_help=True)
evidence_app = typer.Typer(no_args_is_help=True)
store_app = typer.Typer(no_args_is_help=True)
report_app = typer.Typer(no_args_is_help=True)
calibration_app = typer.Typer(no_args_is_help=True)
ci_app = typer.Typer(no_args_is_help=True)
app.add_typer(scenario_app, name="scenario")
app.add_typer(session_app, name="session")
app.add_typer(evidence_app, name="evidence")
app.add_typer(store_app, name="store")
app.add_typer(report_app, name="report")
app.add_typer(calibration_app, name="calibration")
app.add_typer(ci_app, name="ci")


@dataclass(frozen=True, slots=True)
class _CliState:
    output_format: str
    explain: bool
    store_root: Path | None


@app.callback()
def root(
    ctx: typer.Context,
    output_format: str | None = typer.Option(None, "--format", help="json or jsonl"),
    explain: bool = typer.Option(False, "--explain", help="Include proof-chain explanations."),
    config: Annotated[
        Path | None,
        typer.Option(help="Versioned operator JSON config."),
    ] = None,
) -> None:
    """Inspect and operate the deterministic agent-assurance framework."""
    config_path = config
    if config_path is None and os.environ.get("AGENT_EVALS_CONFIG"):
        config_path = Path(os.environ["AGENT_EVALS_CONFIG"])
    settings: dict[str, Any] = {}
    if config_path is not None:
        raw = operator.load_json(config_path, label="operator config")
        if not isinstance(raw, dict):
            raise typer.BadParameter("operator config must be a JSON object")
        if raw.get("schema_version") != "agent-evals/operator-config/v1":
            raise typer.BadParameter(
                "operator config schema_version must be 'agent-evals/operator-config/v1'"
            )
        unknown = set(raw) - {"schema_version", "output_format", "explain", "store_root"}
        if unknown:
            raise typer.BadParameter(f"operator config has unknown keys: {sorted(unknown)!r}")
        settings = raw

    chosen_format = (
        output_format
        or os.environ.get("AGENT_EVALS_OUTPUT_FORMAT")
        or settings.get("output_format")
        or "json"
    )
    if chosen_format not in {"json", "jsonl"}:
        raise typer.BadParameter("--format must be json or jsonl")
    env_explain = os.environ.get("AGENT_EVALS_EXPLAIN", "").lower() in {"1", "true", "yes"}
    chosen_explain = explain or env_explain or settings.get("explain") is True
    configured_store = os.environ.get("AGENT_EVALS_STORE_ROOT") or settings.get("store_root")
    ctx.obj = _CliState(
        output_format=chosen_format,
        explain=chosen_explain,
        store_root=Path(configured_store) if isinstance(configured_store, str) else None,
    )


@app.command()
def doctor(
    ctx: typer.Context,
    deep: bool = typer.Option(False, "--deep", help="Run bounded local diagnostics."),
) -> None:
    """Report framework identity, optionally with bounded local diagnostics."""
    if deep:
        _dispatch(
            ctx,
            lambda: operator.deep_doctor(configured_store_root=_state(ctx).store_root),
        )
        return
    try:
        package_version = version("qa-automation-ai-agent-evals")
    except PackageNotFoundError:
        package_version = "source-tree"
    _emit(
        ctx,
        {
            "framework": "qa-automation-ai-agent-evals",
            "version": package_version,
            "core_requires_provider_credentials": False,
            "terminal_authority": "deterministic-evidence",
        },
    )


@scenario_app.command("validate")
def scenario_validate(ctx: typer.Context, path: Path) -> None:
    """Validate one versioned scenario and print its canonical identity."""
    _dispatch(ctx, lambda: operator.validate_scenario(path))


@app.command("run")
def run(ctx: typer.Context, request: Path) -> None:
    """Run exactly one pre-normalized deterministic operator-scripted observation."""
    _dispatch_async(ctx, lambda: operator.run_request(request, single=True))


@session_app.command("run")
def session_run(ctx: typer.Context, request: Path) -> None:
    """Run a fixed-horizon deterministic operator-scripted session."""
    _dispatch_async(ctx, lambda: operator.run_request(request, single=False))


@app.command("replay")
def replay(ctx: typer.Context, evidence: Path, scenario: Path, subject: Path) -> None:
    """Replay recorded evidence through deterministic evaluator logic without live execution."""
    _dispatch_async(
        ctx,
        lambda: operator.replay_or_regrade(
            evidence_path=evidence,
            scenario_path=scenario,
            subject_path=subject,
            include_evidence=True,
        ),
    )


@app.command("regrade")
def regrade(ctx: typer.Context, evidence: Path, scenario: Path, subject: Path) -> None:
    """Regrade recorded evidence and emit only deterministic grading results."""
    _dispatch_async(
        ctx,
        lambda: operator.replay_or_regrade(
            evidence_path=evidence,
            scenario_path=scenario,
            subject_path=subject,
            include_evidence=False,
        ),
    )


@evidence_app.command("verify")
def evidence_verify(ctx: typer.Context, path: Path) -> None:
    """Strictly validate one trial evidence envelope and rederive its root."""
    _dispatch(ctx, lambda: operator.verify_evidence(path))


@evidence_app.command("inspect")
def evidence_inspect(
    ctx: typer.Context,
    path: Path,
    include_payloads: bool = typer.Option(
        False,
        "--include-payloads",
        help="Explicitly include event payloads; omitted by default.",
    ),
) -> None:
    """Inspect validated evidence without exposing event payloads by default."""
    _dispatch(ctx, lambda: operator.inspect_evidence(path, include_payloads=include_payloads))


@store_app.command("verify-all")
def store_verify_all(ctx: typer.Context, root: Path) -> None:
    """Verify every immutable local evidence-store record and report partial/locked entries."""
    _dispatch(ctx, lambda: operator.verify_store(root))


@report_app.command("verify")
def report_verify(ctx: typer.Context, path: Path) -> None:
    """Revalidate a v6/v7 assurance report and all bound derived claims."""
    _dispatch(ctx, lambda: operator.verify_report(path))


@app.command("compare")
def compare(
    ctx: typer.Context,
    baseline: Path,
    candidate: Path,
    alpha: float = typer.Option(0.05, "--alpha"),
) -> None:
    """Compare paired PASS/FAIL baseline and candidate verdict vectors."""
    _dispatch(ctx, lambda: operator.compare_verdicts(baseline, candidate, alpha=alpha))


@app.command("minimize")
def minimize(
    ctx: typer.Context,
    evidence: Path,
    scenario: Path,
    subject: Path,
    max_evaluations: int = typer.Option(1_000, "--max-evaluations", min=1),
) -> None:
    """Delta-minimize an evidence event trace while preserving its exact non-PASS verdict."""
    _dispatch_async(
        ctx,
        lambda: operator.minimize_evidence(
            evidence_path=evidence,
            scenario_path=scenario,
            subject_path=subject,
            max_evaluations=max_evaluations,
        ),
    )


@calibration_app.command("run")
def calibration_run(ctx: typer.Context, request: Path) -> None:
    """Derive an integrity-bound semantic calibration receipt from validated observations."""
    _dispatch(ctx, lambda: operator.calibration_run(request))


@calibration_app.command("verify")
def calibration_verify(ctx: typer.Context, receipt: Path) -> None:
    """Revalidate a semantic calibration receipt and all derived metrics."""
    _dispatch(ctx, lambda: operator.calibration_verify(receipt))


@ci_app.command("check-policy")
def ci_check_policy(
    ctx: typer.Context,
    root: Annotated[Path | None, typer.Option(help="Repository root.")] = None,
) -> None:
    """Execute repository-owned runtime, security-stack, and semantic workflow policy checks."""
    selected_root = root if root is not None else Path.cwd()
    _dispatch(ctx, lambda: operator.check_repository_policy(selected_root.resolve()))


def _dispatch(ctx: typer.Context, operation: Callable[[], dict[str, Any]]) -> None:
    try:
        payload = operation()
    except (ValidationError, ValueError, OSError, RuntimeError) as exc:
        _emit_error(ctx, exc)
        raise typer.Exit(EXIT_VALIDATION) from None
    _emit_result(ctx, payload)


def _dispatch_async(ctx: typer.Context, operation: Callable[[], Any]) -> None:
    import asyncio

    try:
        payload = asyncio.run(operation())
    except (ValidationError, ValueError, OSError, RuntimeError) as exc:
        _emit_error(ctx, exc)
        raise typer.Exit(EXIT_VALIDATION) from None
    if not isinstance(payload, dict):
        _emit_error(ctx, RuntimeError("operator async command returned a non-object result"))
        raise typer.Exit(EXIT_VALIDATION)
    _emit_result(ctx, cast(dict[str, Any], payload))


def _emit_result(ctx: typer.Context, payload: dict[str, Any]) -> None:
    value = dict(payload)
    proof = value.pop("_proof", None)
    exit_code = value.pop("_exit_code", EXIT_OK)
    if _state(ctx).explain and proof is not None:
        value["proof_chain"] = proof
    _emit(ctx, value)
    if exit_code:
        raise typer.Exit(int(exit_code))


def _emit_error(ctx: typer.Context, exc: Exception) -> None:
    payload: dict[str, Any] = {
        "status": "error",
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
    if _state(ctx).explain:
        payload["proof_chain"] = ["the requested operation failed before an authoritative result"]
    typer.echo(_serialize(_state(ctx), payload), err=True)


def _emit(ctx: typer.Context, payload: dict[str, Any]) -> None:
    typer.echo(_serialize(_state(ctx), payload))


def _serialize(state: _CliState, payload: dict[str, Any]) -> str:
    if state.output_format == "jsonl":
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _state(ctx: typer.Context) -> _CliState:
    return cast(_CliState, ctx.obj)


if __name__ == "__main__":
    app()
