"""Fail closed when CodeQL SARIF contains any code-scanning alert."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _sarif_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    files = sorted(path.rglob("*.sarif"))
    files.extend(sorted(path.rglob("*.sarif.json")))
    seen: set[Path] = set()
    unique: list[Path] = []
    for item in files:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _rule_for_result(run: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    driver = ((run.get("tool") or {}).get("driver") or {})
    rules = driver.get("rules") or []
    index = result.get("ruleIndex")
    if isinstance(index, int) and 0 <= index < len(rules):
        rule = rules[index]
        if isinstance(rule, dict):
            return rule

    rule_id = result.get("ruleId") or ((result.get("rule") or {}).get("id"))
    for rule in rules:
        if isinstance(rule, dict) and rule.get("id") == rule_id:
            return rule
    return {}


def _location(result: dict[str, Any]) -> str:
    locations = result.get("locations") or []
    if not locations:
        return "unknown"
    physical = (locations[0].get("physicalLocation") or {})
    artifact = (physical.get("artifactLocation") or {}).get("uri") or ""
    region = physical.get("region") or {}
    line = region.get("startLine")
    return artifact + (f":{line}" if artifact and line else "") or "unknown"


def evaluate(paths: list[Path]) -> tuple[int, list[str]]:
    errors: list[str] = []
    alert_count = 0
    sarif_count = 0

    for supplied in paths:
        files = _sarif_files(supplied)
        if not files:
            errors.append(f"no SARIF files found at {supplied}")
            continue

        for sarif in files:
            sarif_count += 1
            try:
                payload = json.loads(sarif.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"unable to read SARIF {sarif}: {exc}")
                continue

            runs = payload.get("runs")
            if not isinstance(runs, list) or not runs:
                errors.append(f"SARIF {sarif} contains no runs")
                continue

            for run in runs:
                if not isinstance(run, dict):
                    errors.append(f"SARIF {sarif} contains an invalid run")
                    continue
                for result in run.get("results") or []:
                    if not isinstance(result, dict):
                        errors.append(f"SARIF {sarif} contains an invalid result")
                        continue

                    alert_count += 1
                    rule = _rule_for_result(run, result)
                    properties = rule.get("properties") or {}
                    result_properties = result.get("properties") or {}
                    security_severity = (
                        result_properties.get("security-severity")
                        or properties.get("security-severity")
                        or "unrated"
                    )
                    level = result.get("level") or (
                        (rule.get("defaultConfiguration") or {}).get("level")
                    ) or "unspecified"
                    tags = ",".join(str(tag) for tag in (properties.get("tags") or []))
                    message = ((result.get("message") or {}).get("text") or "").strip()
                    print(
                        "BLOCKING CodeQL alert: "
                        f"rule={result.get('ruleId') or rule.get('id') or 'unknown'} "
                        f"level={level} "
                        f"security-severity={security_severity} "
                        f"location={_location(result)} "
                        f"tags={tags or '<none>'} "
                        f"message={message or '<no message>'}"
                    )

    if sarif_count == 0 and not errors:
        errors.append("no CodeQL SARIF input was evaluated")

    print(f"CodeQL zero-alert gate: files={sarif_count} alerts={alert_count}")
    return alert_count, errors


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "usage: validate_codeql_sarif.py <sarif-file-or-directory> [...]",
            file=sys.stderr,
        )
        return 2

    alerts, errors = evaluate([Path(item) for item in args])
    if errors:
        print("CodeQL zero-alert gate failed closed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    if alerts:
        print(
            f"CodeQL zero-alert gate rejected {alerts} code-scanning alert(s)",
            file=sys.stderr,
        )
        return 1

    print("CodeQL zero-alert gate passed: no code-scanning alerts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
