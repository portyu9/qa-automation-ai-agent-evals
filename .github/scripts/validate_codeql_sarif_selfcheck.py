from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from validate_codeql_sarif import evaluate


def sarif(
    *,
    rule_id: str = "actions/missing-workflow-permissions",
    security_severity: str | None = "5.0",
    security_tag: bool = True,
) -> dict:
    properties: dict[str, object] = {}
    if security_severity is not None:
        properties["security-severity"] = security_severity
    if security_tag:
        properties["tags"] = ["security", "external/cwe/cwe-275"]
    return {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "CodeQL",
                        "rules": [
                            {
                                "id": rule_id,
                                "properties": properties,
                                "defaultConfiguration": {"level": "warning"},
                            }
                        ],
                    }
                },
                "results": [
                    {
                        "ruleId": rule_id,
                        "ruleIndex": 0,
                        "level": "warning",
                        "message": {"text": "fixture alert"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": ".github/workflows/example.yml"},
                                    "region": {"startLine": 1},
                                }
                            }
                        ],
                    }
                ],
            }
        ],
    }


class CodeqlSarifGateSelfCheck(unittest.TestCase):
    def evaluate_fixture(self, payload: dict) -> tuple[int, list[str]]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.sarif"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return evaluate([path])

    def test_medium_security_alert_blocks(self) -> None:
        alerts, errors = self.evaluate_fixture(sarif(security_severity="5.0"))
        self.assertEqual(alerts, 1)
        self.assertEqual(errors, [])

    def test_high_security_alert_blocks(self) -> None:
        alerts, errors = self.evaluate_fixture(sarif(security_severity="9.0"))
        self.assertEqual(alerts, 1)
        self.assertEqual(errors, [])

    def test_unrated_security_alert_blocks(self) -> None:
        alerts, errors = self.evaluate_fixture(sarif(security_severity=None))
        self.assertEqual(alerts, 1)
        self.assertEqual(errors, [])

    def test_nonsecurity_code_scanning_result_still_blocks(self) -> None:
        alerts, errors = self.evaluate_fixture(
            sarif(rule_id="example/quality", security_severity=None, security_tag=False)
        )
        self.assertEqual(alerts, 1)
        self.assertEqual(errors, [])

    def test_missing_sarif_fails_closed(self) -> None:
        alerts, errors = evaluate([Path("/definitely/missing/codeql-results")])
        self.assertEqual(alerts, 0)
        self.assertTrue(any("no SARIF files found" in item for item in errors))

    def test_empty_results_pass(self) -> None:
        payload = sarif()
        payload["runs"][0]["results"] = []
        alerts, errors = self.evaluate_fixture(payload)
        self.assertEqual(alerts, 0)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
