"""Denormalization smells are review hints and do not fail the build."""

from __future__ import annotations

import io
import textwrap
import unittest
from pathlib import Path

from orm_synapse.cli import main
from orm_synapse.denormalize import analyze_models, limit_to_changes, parse_unified_diff
from orm_synapse.parser import parse_models_file


def _models(source: str, path: str = "shop/models.py"):
    return parse_models_file(path, textwrap.dedent(source))


class AnalyzeTest(unittest.TestCase):
    def test_id_list_repeated_group_and_copied_attribute(self) -> None:
        models = _models(
            """
            from django.db import models

            class Order(models.Model):
                company = models.ForeignKey("Company", on_delete=models.CASCADE)
                company_name = models.CharField(max_length=100)
                company_id_cache = models.IntegerField(default=0)
                phone_1 = models.CharField(max_length=20)
                phone_2 = models.CharField(max_length=20)
                phone_3 = models.CharField(max_length=20)
                job_ids = models.TextField(default="")
            """
        )
        codes = {(item.code, item.field) for item in analyze_models(models)}
        self.assertIn(("DOL018", "job_ids"), codes)
        self.assertIn(("DOL019", "phone_1"), codes)
        self.assertIn(("DOL020", "company_name"), codes)
        self.assertNotIn(("DOL020", "company_id_cache"), codes)

    def test_scalar_id_without_a_foreign_key_is_quiet(self) -> None:
        models = _models(
            """
            from django.db import models

            class Lead(models.Model):
                company_id = models.PositiveIntegerField(default=0)
                note = models.CharField(max_length=10)
            """
        )
        self.assertEqual(analyze_models(models), [])

    def test_two_numbered_columns_are_not_a_group(self) -> None:
        models = _models(
            """
            from django.db import models

            class Contact(models.Model):
                phone_1 = models.CharField(max_length=20)
                phone_2 = models.CharField(max_length=20)
            """
        )
        self.assertEqual(analyze_models(models), [])

    def test_inherited_id_list_is_reported_once(self) -> None:
        models = _models(
            """
            from django.db import models

            class LeadBase(models.Model):
                job_ids = models.TextField(default="")

                class Meta:
                    abstract = True

            class Lead(LeadBase):
                name = models.CharField(max_length=10)

            class LeadArchive(LeadBase):
                reason = models.CharField(max_length=10)
            """
        )
        findings = [item for item in analyze_models(models) if item.code == "DOL018"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].field, "job_ids")

    def test_proxy_is_skipped(self) -> None:
        models = _models(
            """
            from django.db import models

            class Lead(models.Model):
                job_ids = models.TextField(default="")

            class LeadProxy(Lead):
                class Meta:
                    proxy = True
            """
        )
        findings = analyze_models(models)
        self.assertEqual([item.model for item in findings], ["Lead"])

    def test_suppression_comment(self) -> None:
        path = Path(__file__).parent / "_denorm_suppress_tmp.py"
        source = textwrap.dedent(
            """
            from django.db import models

            class Order(models.Model):
                # orm-synapse-disable-next-line DOL018
                job_ids = models.TextField(default="")
                company = models.ForeignKey("Company", on_delete=models.CASCADE)
                company_name = models.CharField(max_length=100)
            """
        )
        path.write_text(source, encoding="utf-8")
        self.addCleanup(path.unlink)
        codes = {item.code for item in analyze_models(parse_models_file(str(path), source))}
        self.assertNotIn("DOL018", codes)
        self.assertIn("DOL020", codes)


class CommandTest(unittest.TestCase):
    def test_default_exit_is_zero_and_strict_fails(self) -> None:
        import shutil
        import tempfile

        app = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(app, ignore_errors=True))
        model = app / "models.py"
        model.write_text(
            "from django.db import models\n\n"
            "class Order(models.Model):\n"
            "    job_ids = models.TextField(default='')\n",
            encoding="utf-8",
        )

        import contextlib

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["denormalize", "--path", str(app), "--quiet"])
        self.assertEqual(code, 0)
        self.assertIn("DOL018", out.getvalue())

        with contextlib.redirect_stdout(io.StringIO()):
            strict = main(["denormalize", "--path", str(app), "--strict", "--quiet"])
        self.assertEqual(strict, 1)

        github = io.StringIO()
        with contextlib.redirect_stdout(github):
            main(["denormalize", "--path", str(app), "--format", "github", "--quiet"])
        self.assertIn("::warning ", github.getvalue())
        self.assertNotIn("::error", github.getvalue())


_ORDER = (
    "from django.db import models\n"
    "\n"
    "class Order(models.Model):\n"
    "    company = models.ForeignKey('Company', on_delete=models.CASCADE)\n"
    "    company_name = models.CharField(max_length=100)\n"
    "    phone_1 = models.CharField(max_length=20)\n"
    "    phone_2 = models.CharField(max_length=20)\n"
    "    phone_3 = models.CharField(max_length=20)\n"
    "    job_ids = models.TextField(default='')\n"
)
# 0-based: class=2, company_name=4, phone_1=5, phone_3=7, job_ids=8


def _diff(*lines: int, path: str = "models.py") -> str:
    body = "".join(
        f"@@ -0,0 +{line + 1},1 @@\n+kept\n" for line in lines
    )
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"{body}"
    )


class AddedScopeTest(unittest.TestCase):
    def test_added_lines_are_zero_based(self) -> None:
        added = parse_unified_diff(_diff(4))
        self.assertEqual(added, {"models.py": {4}})

    def test_an_old_column_stays_quiet(self) -> None:
        import shutil
        import tempfile

        app = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(app, ignore_errors=True))
        model = app / "models.py"
        model.write_text(_ORDER, encoding="utf-8")
        models = parse_models_file(str(model), _ORDER)
        findings = analyze_models(models)

        only_name = limit_to_changes(findings, models, parse_unified_diff(_diff(4)), str(app))
        self.assertEqual({(item.code, item.field) for item in only_name}, {("DOL020", "company_name")})

        only_phone = limit_to_changes(findings, models, parse_unified_diff(_diff(7)), str(app))
        self.assertEqual({item.code for item in only_phone}, {"DOL019"})

        new_table = limit_to_changes(findings, models, parse_unified_diff(_diff(2)), str(app))
        self.assertEqual(
            {item.code for item in new_table},
            {"DOL018", "DOL019", "DOL020"},
        )

        untouched = limit_to_changes(findings, models, parse_unified_diff(_diff(3)), str(app))
        self.assertEqual(untouched, [])

    def test_cli_only_added_skips_existing_columns(self) -> None:
        import contextlib
        import shutil
        import tempfile

        app = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(app, ignore_errors=True))
        (app / "models.py").write_text(_ORDER, encoding="utf-8")
        diff = app / "pr.diff"
        diff.write_text(_diff(4), encoding="utf-8")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main([
                "denormalize",
                "--path",
                str(app),
                "--only-added",
                str(diff),
                "--quiet",
            ])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("DOL020", text)
        self.assertNotIn("DOL018", text)
        self.assertNotIn("DOL019", text)

        empty = app / "empty.diff"
        empty.write_text(_diff(3), encoding="utf-8")
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet):
            main(["denormalize", "--path", str(app), "--only-added", str(empty), "--quiet"])
        self.assertIn("No new tables or columns to review.", quiet.getvalue())
