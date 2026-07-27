"""Tests for ci_formats — SARIF 2.1.0 and GitHub workflow-command serializers.

These formats are consumed by machines (GitHub Code Scanning, the Actions
log parser), not humans — a malformed ``$schema``, a wrong ``level`` string,
or an unescaped ``%``/newline silently drops annotations instead of raising
anywhere we would notice. Each serializer is a pure function over the
analyzer dataclasses, so we pin the exact envelope shape here: schema/version
constants, driver identity, severity→level mapping, root-relative POSIX
URIs, per-rule dedup, and GitHub's property/data escaping rules.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from django_orm_lens.ci_formats import (
    migration_risks_github,
    migration_risks_sarif,
    nplusone_github,
    nplusone_sarif,
)
from django_orm_lens.migrations_parser import MigrationRisk
from django_orm_lens.query_analyzer import NPlusOneFinding


def _nplusone_finding(**overrides) -> NPlusOneFinding:
    base = dict(
        file="shop/views.py",
        line=12,
        loop_var="order",
        queryset_var="orders",
        accessed=["customer"],
        suggested_fix='.select_related("customer")',
        confidence="high",
    )
    base.update(overrides)
    return NPlusOneFinding(**base)


def _migration_risk(**overrides) -> MigrationRisk:
    base = dict(
        file_path="orders/migrations/0002_add_status.py",
        line_number=7,
        app="orders",
        migration="0002_add_status",
        operation="AddField",
        model="order",
        field="status",
        rule="add_field_not_null_no_default",
        description="Adds NOT NULL column 'status' without a default.",
        mitigation="Add null=True first, backfill, then set null=False.",
        confidence="high",
        severity="critical",
    )
    base.update(overrides)
    return MigrationRisk(**base)


class NPlusOneSarifTest(unittest.TestCase):
    def test_envelope_schema_version_and_driver(self) -> None:
        doc = nplusone_sarif([_nplusone_finding()])

        self.assertTrue(doc["$schema"].endswith("sarif-schema-2.1.0.json"))
        self.assertEqual(doc["version"], "2.1.0")
        self.assertEqual(len(doc["runs"]), 1)
        driver = doc["runs"][0]["tool"]["driver"]
        self.assertEqual(driver["name"], "django-orm-lens")
        self.assertEqual([r["id"] for r in driver["rules"]], ["nplusone"])

    def test_confidence_to_level_mapping(self) -> None:
        doc = nplusone_sarif(
            [
                _nplusone_finding(confidence="high"),
                _nplusone_finding(
                    confidence="medium",
                    line=30,
                    accessed=["tags"],
                    suggested_fix='.prefetch_related("tags")',
                ),
            ]
        )
        results = doc["runs"][0]["results"]

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["level"], "warning")  # high
        self.assertEqual(results[1]["level"], "note")  # medium
        self.assertEqual({r["ruleId"] for r in results}, {"nplusone"})

    def test_location_uri_and_start_line(self) -> None:
        doc = nplusone_sarif([_nplusone_finding(file="shop/views.py", line=12)])
        location = doc["runs"][0]["results"][0]["locations"][0]
        physical = location["physicalLocation"]

        self.assertEqual(physical["artifactLocation"]["uri"], "shop/views.py")
        self.assertEqual(physical["region"]["startLine"], 12)

    def test_message_carries_suggested_fix(self) -> None:
        doc = nplusone_sarif([_nplusone_finding()])
        message = doc["runs"][0]["results"][0]["message"]["text"]

        self.assertIn('.select_related("customer")', message)
        self.assertIn("orders", message)  # queryset var named in prose


class MigrationRisksSarifTest(unittest.TestCase):
    def test_severity_to_level_mapping(self) -> None:
        doc = migration_risks_sarif(
            [
                _migration_risk(severity="critical"),
                _migration_risk(
                    severity="warning",
                    rule="runsql_no_reverse",
                    operation="RunSQL",
                    line_number=11,
                ),
                _migration_risk(
                    severity="info",
                    rule="remove_field_unverified",
                    operation="RemoveField",
                    line_number=15,
                ),
            ]
        )
        levels = [r["level"] for r in doc["runs"][0]["results"]]

        self.assertEqual(levels, ["error", "warning", "note"])

    def test_rules_array_deduped_by_rule_id(self) -> None:
        doc = migration_risks_sarif(
            [
                _migration_risk(line_number=7),
                _migration_risk(line_number=21, field="code"),  # same rule again
                _migration_risk(
                    severity="warning",
                    rule="runsql_no_reverse",
                    operation="RunSQL",
                    line_number=30,
                ),
            ]
        )
        run = doc["runs"][0]

        self.assertEqual(len(run["results"]), 3)
        rule_ids = [r["id"] for r in run["tool"]["driver"]["rules"]]
        self.assertEqual(
            rule_ids, ["add_field_not_null_no_default", "runsql_no_reverse"]
        )

    def test_help_uri_points_at_rule_anchor(self) -> None:
        doc = migration_risks_sarif([_migration_risk()])
        rule = doc["runs"][0]["tool"]["driver"]["rules"][0]

        self.assertTrue(
            rule["helpUri"].endswith(
                "docs/rules/migrations.md#add_field_not_null_no_default"
            ),
            rule["helpUri"],
        )

    def test_absolute_path_becomes_root_relative_posix_uri(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            abs_path = root / "orders" / "migrations" / "0002_add_status.py"
            doc = migration_risks_sarif(
                [_migration_risk(file_path=str(abs_path))], root=str(root)
            )
            uri = doc["runs"][0]["results"][0]["locations"][0][
                "physicalLocation"
            ]["artifactLocation"]["uri"]

            self.assertEqual(uri, "orders/migrations/0002_add_status.py")

    def test_relative_posix_path_is_preserved(self) -> None:
        doc = migration_risks_sarif(
            [_migration_risk(file_path="orders/migrations/0002_add_status.py")],
            root=None,
        )
        uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]

        self.assertEqual(uri, "orders/migrations/0002_add_status.py")


class NPlusOneGithubTest(unittest.TestCase):
    def test_high_confidence_is_warning_command(self) -> None:
        out = nplusone_github([_nplusone_finding(confidence="high")])

        self.assertTrue(out.startswith("::warning "), out)
        self.assertIn("file=shop/views.py", out)
        self.assertIn(",line=12,", out)
        self.assertIn("title=", out)

    def test_medium_confidence_is_notice_command(self) -> None:
        out = nplusone_github([_nplusone_finding(confidence="medium")])

        self.assertTrue(out.startswith("::notice "), out)

    def test_title_colon_is_escaped(self) -> None:
        out = nplusone_github([_nplusone_finding()])

        # 'django-orm-lens: N+1 query' — the colon must become %3A inside
        # the title= property or GitHub truncates the annotation.
        self.assertIn("title=django-orm-lens%3A N+1 query", out)
        self.assertNotIn("title=django-orm-lens: ", out)

    def test_percent_and_newline_in_message_are_escaped(self) -> None:
        finding = _nplusone_finding(
            suggested_fix='.select_related("customer")\ncovers 100% of loops'
        )
        out = nplusone_github([finding])

        self.assertEqual(len(out.splitlines()), 1)  # newline must not survive
        self.assertIn("%0A", out)
        self.assertIn("100%25", out)

    def test_empty_findings_produce_empty_string(self) -> None:
        self.assertEqual(nplusone_github([]), "")


class MigrationRisksGithubTest(unittest.TestCase):
    def test_severity_to_command_mapping(self) -> None:
        out = migration_risks_github(
            [
                _migration_risk(severity="critical"),
                _migration_risk(
                    severity="warning", rule="runsql_no_reverse", line_number=11
                ),
                _migration_risk(
                    severity="info",
                    rule="remove_field_unverified",
                    line_number=15,
                ),
            ]
        )
        lines = out.splitlines()

        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("::error "), lines[0])
        self.assertTrue(lines[1].startswith("::warning "), lines[1])
        self.assertTrue(lines[2].startswith("::notice "), lines[2])

    def test_line_has_file_line_and_escaped_title(self) -> None:
        out = migration_risks_github([_migration_risk()])

        self.assertIn("file=orders/migrations/0002_add_status.py", out)
        self.assertIn(",line=7,", out)
        self.assertIn("title=django-orm-lens%3A add_field_not_null_no_default", out)

    def test_comma_in_property_value_is_escaped(self) -> None:
        # A comma inside file= would split the property list — must be %2C.
        out = migration_risks_github(
            [_migration_risk(file_path="app,v2/migrations/0002_add_status.py")]
        )

        self.assertIn("file=app%2Cv2/migrations/0002_add_status.py", out)

    def test_percent_and_newline_in_message_are_escaped(self) -> None:
        out = migration_risks_github(
            [
                _migration_risk(
                    description="Locks 100% of writes.",
                    mitigation="Step 1\nStep 2",
                )
            ]
        )

        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn("100%25", out)
        self.assertIn("Step 1%0AStep 2", out)

    def test_absolute_path_with_root_is_relativized(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            abs_path = root / "orders" / "migrations" / "0002_add_status.py"
            out = migration_risks_github(
                [_migration_risk(file_path=str(abs_path))], root=str(root)
            )

            self.assertIn("file=orders/migrations/0002_add_status.py", out)

    def test_empty_findings_produce_empty_string(self) -> None:
        self.assertEqual(migration_risks_github([]), "")


if __name__ == "__main__":
    unittest.main()
