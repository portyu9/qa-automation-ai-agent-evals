"""Command-line entry point for deterministic framework diagnostics."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version

import typer

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def doctor() -> None:
    """Report local framework identity without requiring a model provider."""
    try:
        package_version = version("qa-automation-ai-agent-evals")
    except PackageNotFoundError:
        package_version = "source-tree"
    typer.echo(
        json.dumps(
            {
                "framework": "qa-automation-ai-agent-evals",
                "version": package_version,
                "core_requires_provider_credentials": False,
                "terminal_authority": "deterministic-evidence",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    app()
