# Contributing

Thank you for improving `qa-automation-ai-agent-evals`. This project treats evaluation logic as assurance infrastructure: changes are reviewed not only for correctness, but also for whether they preserve trust boundaries, historical replay meaning, and fail-closed behavior.

## Local setup

Use a supported Python version declared by `pyproject.toml` and install the development dependencies:

```bash
python -m pip install -e '.[dev]'
```

For deterministic OpenAI Agents SDK and MCP integration work:

```bash
python -m pip install -e '.[dev,openai,mcp]'
```

The default unit suite intentionally excludes optional integration markers:

```bash
pytest
ruff check .
ruff format --check --diff .
mypy
bandit -q -r src
pip-audit
```

Run the integration lanes relevant to a change before opening a PR:

```bash
pytest -m openai tests/integration/test_openai_*.py
pytest -m mcp tests/integration/test_mcp_*.py
pytest -m mcp_remote tests/integration/test_mcp_*.py
pytest -m mcp_oauth tests/integration/test_mcp_*.py
```

Do not add live-provider calls to deterministic CI lanes.

## Assurance invariants

Contributions must preserve these rules unless an explicit, reviewed architecture change replaces them with a stronger contract:

- the evaluated agent is the subject, never the terminal oracle;
- missing/unverifiable evaluation preconditions remain explicit uncertainty rather than green behavior;
- deterministic policy/safety failures cannot be rescued by semantic grading;
- evaluator-owned evidence cannot be self-issued by an untrusted adapter/subject;
- handoff authority may preserve or narrow effective authority, never re-expand it;
- approval evidence must bind the exact invocation/authority context it authorizes;
- replay is historical verification/regrading, not a claim that external side effects or provider behavior were rerun;
- hashes prove content integrity/identity only where documented; they are not signatures or authenticated provenance.

Read `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, and `docs/LIMITATIONS.md` before changing a trust boundary.

## Evidence and schema changes

Treat changes to evidence events, receipts, canonicalization, identities, reports, release gates, authorization, or historical loaders as behavior-bearing schema work.

A green current-head test suite is not sufficient if the change can reinterpret or invalidate previously valid persisted evidence under the same schema identity. Either preserve the historical contract exactly or introduce an explicit version transition with tests for old and new semantics.

When changing canonical identity material, add golden/compatibility tests and document the identity-domain transition.

## Pull requests

Keep PRs narrowly scoped. Include tests for behavior-bearing changes and update documentation when a claim, non-claim, schema, trust boundary, or operator contract changes.

In the PR description, call out:

- affected backlog/issue IDs;
- assurance/trust boundaries touched;
- evidence/replay compatibility impact;
- security impact;
- statistical-contract impact;
- integration lanes required;
- any deliberate non-claim that remains after the change.

Do not merge known semantic uncertainty just because CI is green. Resolve blocking review findings or explicitly redesign/split the change.

## Security and sensitive data

Never commit API keys, tokens, credentials, private production transcripts, sensitive customer data, or raw secrets as fixtures. Use synthetic values and follow `.github/SECURITY.md` for vulnerability reports.

## Dependency and CI changes

GitHub Actions must remain commit-SHA pinned. Keep workflow permissions least-privilege and preserve `persist-credentials: false` for checkout unless a separately reviewed workflow requires a stronger permission. Executable dependency/runtime truth belongs in repository manifests and policy checks rather than duplicated prose.
