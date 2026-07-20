"""Regression: every CLI subcommand must import and execute cleanly.

The v0.6.0 → v0.7.0 audit surfaced two bugs where a subcommand's body
referenced module-level names that were never imported (or that used the
wrong attribute case) — the unit tests still passed because they exercised
the helper functions directly, never the argparse dispatch path.

This suite runs each subcommand end-to-end via ``main([...])`` against the
miniapp fixture and the migration_risks fixture. Any `NameError`,
`ImportError`, or `AttributeError` in a subcommand body surfaces as a
test failure instead of a crash the next user sees.
"""

from __future__ import annotations

import contextlib
import io
import json as _json
import unittest
from pathlib import Path

from django_orm_lens.cli import main

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
MINIAPP = FIXTURE_ROOT / "miniapp"
MIGRATION_RISKS = FIXTURE_ROOT / "migration_risks"


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        exit_code = main(argv)
    return exit_code, out.getvalue(), err.getvalue()


class SubcommandsSmokeTest(unittest.TestCase):
    """Every subcommand runs without a NameError / ImportError / AttributeError."""

    def test_scan_runs(self) -> None:
        code, out, _err = _run(
            ["scan", "--path", str(MINIAPP), "--format", "table"]
        )
        self.assertEqual(code, 0)
        self.assertIn("Order", out)

    def test_list_runs(self) -> None:
        code, out, _err = _run(["list", "--path", str(MINIAPP)])
        self.assertEqual(code, 0)
        self.assertIn("orders.Order", out)

    def test_er_runs(self) -> None:
        code, out, _err = _run(["er", "--path", str(MINIAPP)])
        self.assertEqual(code, 0)
        self.assertIn("erDiagram", out)

    def test_describe_runs(self) -> None:
        code, out, _err = _run(
            ["describe", "orders.Order", "--path", str(MINIAPP)]
        )
        self.assertEqual(code, 0)
        self.assertIn("Order", out)

    def test_hover_runs(self) -> None:
        code, out, _err = _run(
            ["hover", "orders.Order", "--path", str(MINIAPP)]
        )
        self.assertEqual(code, 0)
        self.assertIn("Order", out)

    def test_nplusone_runs(self) -> None:
        # Miniapp has no n+1 patterns — but the subcommand must dispatch
        # without a NameError (the pre-v0.7 bug was scan_for_nplusone +
        # _build_schema_from_index not being imported at module level).
        code, out, _err = _run(
            ["nplusone", "--path", str(MINIAPP), "--exit-zero"]
        )
        self.assertEqual(code, 0)
        self.assertIn("N+1", out)

    def test_migration_risk_text_format(self) -> None:
        # Text format previously crashed with AttributeError because the
        # print used camelCase attrs (filePath / lineNumber) instead of the
        # snake_case dataclass fields (file_path / line_number).
        code, out, _err = _run(
            [
                "migration-risk",
                "--path",
                str(MIGRATION_RISKS / "add_field_notnull"),
                "--exit-zero",
            ]
        )
        self.assertEqual(code, 0)
        # A finding should be printed with "file:line [severity/confidence]".
        self.assertTrue(
            any(":" in line and "[" in line for line in out.splitlines()),
            f"expected 'file:line [severity/confidence]' line in output, got: {out!r}",
        )

    def test_migration_risk_json_format(self) -> None:
        # JSON path uses to_dict() — separate from the text path bug,
        # but worth pinning too.
        code, out, _err = _run(
            [
                "migration-risk",
                "--path",
                str(MIGRATION_RISKS / "add_field_notnull"),
                "--format",
                "json",
                "--exit-zero",
            ]
        )
        self.assertEqual(code, 0)
        payload = _json.loads(out)
        self.assertIn("findings", payload)


if __name__ == "__main__":
    unittest.main()
