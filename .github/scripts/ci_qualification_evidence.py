from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "agent-evals/ci-qualification-evidence/v1"
EXPECTED_WORKFLOW = "CI"
EXPECTED_REF = "refs/heads/main"
EXPECTED_EVENT = "push"
PASS_VERDICT = "PASS"

REQUIRED_JOB_IDS = (
    "policy",
    "quality",
    "mutation",
    "openai-adapter",
    "mcp-lab",
    "mcp-remote-auth",
    "mcp-oauth-flow",
    "package",
    "package-reverify",
    "package-reproduce",
    "release-supply-chain",
    "release-supply-chain-reverify",
    "ci-gate",
    "protected-gate",
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class QualificationEvidenceError(ValueError):
    """CI qualification evidence failed strict validation."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise QualificationEvidenceError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


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


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise QualificationEvidenceError(
            f"{label} keys mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _require_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise QualificationEvidenceError(f"{label} must be an integer >= 1")
    return value


def _require_text(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise QualificationEvidenceError(f"{label} must be non-empty normalized text")
    return value


def _require_repository(value: object) -> str:
    repository = _require_text(value, "repository")
    if _REPOSITORY.fullmatch(repository) is None:
        raise QualificationEvidenceError("repository must be canonical owner/name text")
    return repository


def _require_sha(value: object) -> str:
    if type(value) is not str or _SHA40.fullmatch(value) is None:
        raise QualificationEvidenceError("commit_sha must be a lowercase 40-character Git SHA")
    return value


def _parse_job_results(values: list[str]) -> tuple[dict[str, str], ...]:
    parsed: dict[str, str] = {}
    for raw in values:
        if type(raw) is not str or "=" not in raw:
            raise QualificationEvidenceError("job result must use exact job-id=result syntax")
        job_id, result = raw.rsplit("=", 1)
        if job_id in parsed:
            raise QualificationEvidenceError(f"duplicate job result: {job_id}")
        parsed[job_id] = result

    expected = set(REQUIRED_JOB_IDS)
    actual = set(parsed)
    if actual != expected:
        raise QualificationEvidenceError(
            f"job result set mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    failed = {job_id: parsed[job_id] for job_id in REQUIRED_JOB_IDS if parsed[job_id] != "success"}
    if failed:
        raise QualificationEvidenceError(f"all required CI jobs must succeed: {failed}")
    return tuple({"job_id": job_id, "result": "success"} for job_id in REQUIRED_JOB_IDS)


def build_evidence(
    *,
    repository: str,
    commit_sha: str,
    ref: str,
    workflow: str,
    run_id: int,
    run_attempt: int,
    event: str,
    job_results: list[str],
) -> dict[str, Any]:
    repository = _require_repository(repository)
    commit_sha = _require_sha(commit_sha)
    if ref != EXPECTED_REF:
        raise QualificationEvidenceError(f"ref must be exactly {EXPECTED_REF}")
    if workflow != EXPECTED_WORKFLOW:
        raise QualificationEvidenceError(f"workflow must be exactly {EXPECTED_WORKFLOW}")
    if event != EXPECTED_EVENT:
        raise QualificationEvidenceError(f"event must be exactly {EXPECTED_EVENT}")
    run_id = _require_positive_int(run_id, "run_id")
    run_attempt = _require_positive_int(run_attempt, "run_attempt")
    jobs = _parse_job_results(job_results)
    return {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "commit_sha": commit_sha,
        "ref": ref,
        "workflow": workflow,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "event": event,
        "jobs": jobs,
        "verdict": PASS_VERDICT,
    }


def validate_evidence(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise QualificationEvidenceError("CI qualification evidence must be a JSON object")
    evidence = value
    _require_exact_keys(
        evidence,
        {
            "schema_version",
            "repository",
            "commit_sha",
            "ref",
            "workflow",
            "run_id",
            "run_attempt",
            "event",
            "jobs",
            "verdict",
        },
        "CI qualification evidence",
    )
    if evidence["schema_version"] != SCHEMA_VERSION:
        raise QualificationEvidenceError("unsupported CI qualification evidence schema")
    _require_repository(evidence["repository"])
    _require_sha(evidence["commit_sha"])
    if evidence["ref"] != EXPECTED_REF:
        raise QualificationEvidenceError(f"evidence ref must be exactly {EXPECTED_REF}")
    if evidence["workflow"] != EXPECTED_WORKFLOW:
        raise QualificationEvidenceError(f"evidence workflow must be exactly {EXPECTED_WORKFLOW}")
    if evidence["event"] != EXPECTED_EVENT:
        raise QualificationEvidenceError(f"evidence event must be exactly {EXPECTED_EVENT}")
    _require_positive_int(evidence["run_id"], "run_id")
    _require_positive_int(evidence["run_attempt"], "run_attempt")
    if evidence["verdict"] != PASS_VERDICT:
        raise QualificationEvidenceError("CI qualification verdict must be PASS")

    jobs = evidence["jobs"]
    if type(jobs) not in (list, tuple):
        raise QualificationEvidenceError("jobs must be an ordered array")
    if len(jobs) != len(REQUIRED_JOB_IDS):
        raise QualificationEvidenceError("jobs must contain the exact required job set")
    normalized: list[dict[str, str]] = []
    for expected_job_id, item in zip(REQUIRED_JOB_IDS, jobs, strict=True):
        if type(item) is not dict:
            raise QualificationEvidenceError("each job result must be a JSON object")
        _require_exact_keys(item, {"job_id", "result"}, "job result")
        if item["job_id"] != expected_job_id:
            raise QualificationEvidenceError(
                "job results must use the canonical required order "
                f"(expected {expected_job_id!r}, got {item['job_id']!r})"
            )
        if item["result"] != "success":
            raise QualificationEvidenceError(f"required CI job {expected_job_id!r} did not succeed")
        normalized.append({"job_id": expected_job_id, "result": "success"})

    return {
        "schema_version": SCHEMA_VERSION,
        "repository": evidence["repository"],
        "commit_sha": evidence["commit_sha"],
        "ref": EXPECTED_REF,
        "workflow": EXPECTED_WORKFLOW,
        "run_id": evidence["run_id"],
        "run_attempt": evidence["run_attempt"],
        "event": EXPECTED_EVENT,
        "jobs": tuple(normalized),
        "verdict": PASS_VERDICT,
    }


def load_evidence(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise QualificationEvidenceError(f"could not read evidence file: {path}") from exc
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise QualificationEvidenceError("CI qualification evidence must be UTF-8") from exc
    try:
        parsed = json.loads(
            decoded,
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                QualificationEvidenceError(f"non-finite JSON value: {value}")
            ),
        )
    except json.JSONDecodeError as exc:
        raise QualificationEvidenceError("CI qualification evidence is malformed JSON") from exc
    validated = validate_evidence(parsed)
    canonical = _canonical_bytes(validated)
    if raw != canonical:
        raise QualificationEvidenceError("CI qualification evidence is not canonical JSON")
    return validated


def verify_expected(
    evidence: dict[str, Any],
    *,
    repository: str,
    commit_sha: str,
    ref: str,
    workflow: str,
    run_id: int,
    run_attempt: int,
    event: str,
) -> None:
    expected = {
        "repository": _require_repository(repository),
        "commit_sha": _require_sha(commit_sha),
        "ref": ref,
        "workflow": workflow,
        "run_id": _require_positive_int(run_id, "expected run_id"),
        "run_attempt": _require_positive_int(run_attempt, "expected run_attempt"),
        "event": event,
    }
    if expected["ref"] != EXPECTED_REF:
        raise QualificationEvidenceError(f"expected ref must be exactly {EXPECTED_REF}")
    if expected["workflow"] != EXPECTED_WORKFLOW:
        raise QualificationEvidenceError(f"expected workflow must be exactly {EXPECTED_WORKFLOW}")
    if expected["event"] != EXPECTED_EVENT:
        raise QualificationEvidenceError(f"expected event must be exactly {EXPECTED_EVENT}")
    for key, expected_value in expected.items():
        if evidence[key] != expected_value:
            raise QualificationEvidenceError(
                f"CI qualification evidence {key} mismatch: {evidence[key]!r} != {expected_value!r}"
            )


def create_command(args: argparse.Namespace) -> None:
    evidence = build_evidence(
        repository=args.repository,
        commit_sha=args.commit_sha,
        ref=args.ref,
        workflow=args.workflow,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        event=args.event,
        job_results=args.job_result,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_canonical_bytes(evidence))
    load_evidence(args.output)


def verify_command(args: argparse.Namespace) -> None:
    evidence = load_evidence(args.evidence)
    verify_expected(
        evidence,
        repository=args.repository,
        commit_sha=args.commit_sha,
        ref=args.ref,
        workflow=args.workflow,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        event=args.event,
    )


def _valid_job_args() -> list[str]:
    return [f"{job_id}=success" for job_id in REQUIRED_JOB_IDS]


def self_test() -> None:
    sha = "a" * 40
    repo = "owner/repo"
    with tempfile.TemporaryDirectory(prefix="ci-qualification-self-test-") as tmp:
        path = Path(tmp) / "ci-qualification-evidence.json"
        evidence = build_evidence(
            repository=repo,
            commit_sha=sha,
            ref=EXPECTED_REF,
            workflow=EXPECTED_WORKFLOW,
            run_id=123,
            run_attempt=4,
            event=EXPECTED_EVENT,
            job_results=_valid_job_args(),
        )
        path.write_bytes(_canonical_bytes(evidence))
        loaded = load_evidence(path)
        verify_expected(
            loaded,
            repository=repo,
            commit_sha=sha,
            ref=EXPECTED_REF,
            workflow=EXPECTED_WORKFLOW,
            run_id=123,
            run_attempt=4,
            event=EXPECTED_EVENT,
        )

        invalid_job_sets = (
            _valid_job_args()[:-1],
            [*_valid_job_args(), "unexpected=success"],
            [
                *[item for item in _valid_job_args() if not item.startswith("ci-gate=")],
                "ci-gate=failure",
            ],
            [*_valid_job_args(), "policy=success"],
        )
        for jobs in invalid_job_sets:
            try:
                build_evidence(
                    repository=repo,
                    commit_sha=sha,
                    ref=EXPECTED_REF,
                    workflow=EXPECTED_WORKFLOW,
                    run_id=123,
                    run_attempt=4,
                    event=EXPECTED_EVENT,
                    job_results=jobs,
                )
            except QualificationEvidenceError:
                pass
            else:
                raise QualificationEvidenceError("self-test accepted invalid job result set")

        canonical = path.read_text(encoding="utf-8")
        malformed_variants = (
            canonical[:-2] + ',"schema_version":"agent-evals/ci-qualification-evidence/v1"}\n',
            json.dumps(evidence, indent=2, default=list) + "\n",
            canonical.replace('"verdict":"PASS"', '"verdict":"FAIL"'),
            canonical.replace('"job_id":"policy"', '"job_id":"quality"', 1),
        )
        for index, variant in enumerate(malformed_variants):
            bad = Path(tmp) / f"bad-{index}.json"
            bad.write_text(variant, encoding="utf-8")
            try:
                load_evidence(bad)
            except QualificationEvidenceError:
                pass
            else:
                raise QualificationEvidenceError(
                    f"self-test accepted invalid evidence variant {index}"
                )

        for key, bad_value in (
            ("repository", "other/repo"),
            ("commit_sha", "b" * 40),
            ("ref", "refs/heads/other"),
            ("workflow", "Other"),
            ("run_id", 124),
            ("run_attempt", 5),
            ("event", "workflow_dispatch"),
        ):
            kwargs: dict[str, object] = {
                "repository": repo,
                "commit_sha": sha,
                "ref": EXPECTED_REF,
                "workflow": EXPECTED_WORKFLOW,
                "run_id": 123,
                "run_attempt": 4,
                "event": EXPECTED_EVENT,
            }
            kwargs[key] = bad_value
            try:
                verify_expected(loaded, **kwargs)  # type: ignore[arg-type]
            except QualificationEvidenceError:
                pass
            else:
                raise QualificationEvidenceError(
                    f"self-test accepted mismatched expected field {key}"
                )


def add_context_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--event", required=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    add_context_arguments(create)
    create.add_argument("--job-result", action="append", default=[], required=True)
    create.add_argument("--output", type=Path, required=True)

    verify = sub.add_parser("verify")
    add_context_arguments(verify)
    verify.add_argument("--evidence", type=Path, required=True)

    sub.add_parser("self-test")

    args = parser.parse_args()
    try:
        if args.command == "create":
            create_command(args)
        elif args.command == "verify":
            verify_command(args)
        else:
            self_test()
    except (QualificationEvidenceError, OSError, TypeError, ValueError) as exc:
        raise SystemExit(f"CI qualification evidence failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
