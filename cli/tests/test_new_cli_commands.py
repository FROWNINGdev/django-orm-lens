"""End-to-end argparse coverage for the four newest CLI subcommands.

``cascade``, ``suggest-indexes``, ``signals``, and ``migration-deps``
landed after the v0.7 dispatch-path audit (see
test_cli_subcommands_smoke.py) and their argparse wiring — flag names,
format branches, exit codes — had no test walking ``main([...])``. The
analyzer internals are unit-tested elsewhere; this suite pins the CLI
contract: output format markers per ``--format``, exit 2 on unresolvable
model/app, and the sarif/github CI format plumbing of ``nplusone`` /
``migration-risk``.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from django_orm_lens.cli import main

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
MINIAPP = FIXTURE_ROOT / "miniapp"
MIGRATION_RISKS = FIXTURE_ROOT / "migration_risks"


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        exit_code = main(argv)
    return exit_code, out.getvalue(), err.getvalue()


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# cascade
# ---------------------------------------------------------------------------


class CascadeCommandTest(unittest.TestCase):
    def test_text_output_groups_by_on_delete(self) -> None:
        code, out, _err = _run(
            ["cascade", "orders.Order", "--path", str(MINIAPP)]
        )
        self.assertEqual(code, 0)
        self.assertIn("deleting one orders.Order row:", out)
        # LineItem.order is a CASCADE FK onto Order in the fixture.
        self.assertIn("CASCADE-deletes rows in", out)
        self.assertIn("orders.LineItem", out)
        self.assertIn("via order", out)

    def test_json_output_has_target_and_buckets(self) -> None:
        code, out, _err = _run(
            ["cascade", "orders.Order", "--path", str(MINIAPP), "--format", "json"]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["target"], "orders.Order")
        for bucket in ("cascade_kills", "set_null", "protected"):
            self.assertIn(bucket, payload)
        kills = payload["cascade_kills"]
        self.assertEqual(len(kills), 1)
        self.assertEqual(kills[0]["model"], "orders.LineItem")
        self.assertEqual(kills[0]["via_field"], "order")

    def test_unknown_model_exits_2(self) -> None:
        code, out, err = _run(
            ["cascade", "GhostModel", "--path", str(MINIAPP)]
        )
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("'GhostModel' not found", err)


# ---------------------------------------------------------------------------
# suggest-indexes
# ---------------------------------------------------------------------------


class SuggestIndexesCommandTest(unittest.TestCase):
    def _make_workspace(self, tmp: str) -> None:
        blog = Path(tmp) / "blog"
        _write(
            blog / "models.py",
            "from django.db import models\n\n\n"
            "class Article(models.Model):\n"
            "    status = models.CharField(max_length=20)\n"
            "    author = models.CharField(max_length=50)\n",
        )
        # Two distinct .filter(status=...) sites — crosses the >=2 threshold
        # so a single-field proposal must appear.
        _write(
            blog / "views.py",
            "from .models import Article\n\n\n"
            "def published():\n"
            "    return Article.objects.filter(status='published')\n\n\n"
            "def drafts():\n"
            "    return Article.objects.filter(status='draft')\n",
        )

    def test_json_proposes_index_for_repeated_filter_field(self) -> None:
        with TemporaryDirectory() as tmp:
            self._make_workspace(tmp)
            code, out, _err = _run(
                ["suggest-indexes", "Article", "--path", tmp, "--format", "json"]
            )
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["target"], "blog.Article")
            proposed = payload["proposed_indexes"]
            self.assertTrue(proposed, "expected at least one proposed index")
            self.assertIn(["status"], [p["fields"] for p in proposed])

    def test_unknown_model_exits_2(self) -> None:
        with TemporaryDirectory() as tmp:
            self._make_workspace(tmp)
            code, _out, err = _run(
                ["suggest-indexes", "GhostModel", "--path", tmp]
            )
            self.assertEqual(code, 2)
            self.assertIn("'GhostModel' not found", err)


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------


class SignalsCommandTest(unittest.TestCase):
    def _make_workspace(self, tmp: str) -> None:
        shop = Path(tmp) / "shop"
        _write(
            shop / "models.py",
            "from django.db import models\n\n\n"
            "class Order(models.Model):\n"
            "    status = models.CharField(max_length=20)\n",
        )
        _write(
            shop / "handlers.py",
            "from django.db.models.signals import post_save\n"
            "from django.dispatch import receiver\n\n"
            "from .models import Order\n\n\n"
            "@receiver(post_save, sender=Order)\n"
            "def on_order_saved(sender, instance, **kwargs):\n"
            "    pass\n",
        )

    def test_text_output_shows_edge(self) -> None:
        with TemporaryDirectory() as tmp:
            self._make_workspace(tmp)
            code, out, _err = _run(["signals", "--path", tmp])
            self.assertEqual(code, 0)
            self.assertIn(
                "shop.Order --post_save--> shop.handlers.on_order_saved", out
            )

    def test_json_output_edge_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            self._make_workspace(tmp)
            code, out, _err = _run(
                ["signals", "--path", tmp, "--format", "json"]
            )
            self.assertEqual(code, 0)
            payload = json.loads(out)
            edges = payload["edges"]
            self.assertEqual(len(edges), 1)
            edge = edges[0]
            self.assertEqual(edge["signal"], "post_save")
            self.assertEqual(edge["sender"], "shop.Order")
            self.assertEqual(edge["handler"], "shop.handlers.on_order_saved")
            self.assertTrue(edge.get("builtin"))


# ---------------------------------------------------------------------------
# migration-deps
# ---------------------------------------------------------------------------


class MigrationDepsCommandTest(unittest.TestCase):
    def _make_app(self, tmp: str) -> None:
        mig = Path(tmp) / "shop" / "migrations"
        _write(mig / "__init__.py", "")
        _write(
            mig / "0001_initial.py",
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = []\n"
            "    operations = [migrations.CreateModel(name='Order', fields=[])]\n",
        )
        # Hyphen in the stem exercises mermaid node-id sanitization.
        _write(
            mig / "0002_add-status.py",
            "from django.db import migrations, models\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('shop', '0001_initial')]\n"
            "    operations = [migrations.AddField(model_name='order',\n"
            "        name='status', field=models.CharField(max_length=20,\n"
            "        default=''))]\n",
        )

    def test_text_output_lists_roots_and_leaves(self) -> None:
        with TemporaryDirectory() as tmp:
            self._make_app(tmp)
            code, out, _err = _run(["migration-deps", "shop", "--path", tmp])
            self.assertEqual(code, 0)
            self.assertIn("app: shop", out)
            self.assertIn("roots:", out)
            self.assertIn("0001_initial", out)
            self.assertIn("leaves:", out)
            self.assertIn("0002_add-status", out)

    def test_json_output_shape(self) -> None:
        with TemporaryDirectory() as tmp:
            self._make_app(tmp)
            code, out, _err = _run(
                ["migration-deps", "shop", "--path", tmp, "--format", "json"]
            )
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["app_label"], "shop")
            self.assertEqual(payload["roots"], ["0001_initial"])
            self.assertEqual(payload["leaves"], ["0002_add-status"])
            self.assertEqual(
                [m["name"] for m in payload["migrations"]],
                ["0001_initial", "0002_add-status"],
            )

    def test_mermaid_output_sanitizes_node_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            self._make_app(tmp)
            code, out, _err = _run(
                ["migration-deps", "shop", "--path", tmp, "--format", "mermaid"]
            )
            self.assertEqual(code, 0)
            lines = out.splitlines()
            self.assertEqual(lines[0], "graph TD")
            # Node id is sanitized (hyphen -> underscore) but the label keeps
            # the on-disk migration name.
            self.assertIn('  0002_add_status["0002_add-status"]', lines)
            self.assertIn("  0001_initial --> 0002_add_status", lines)

    def test_missing_app_exits_2(self) -> None:
        with TemporaryDirectory() as tmp:
            self._make_app(tmp)
            code, _out, err = _run(["migration-deps", "ghostapp", "--path", tmp])
            self.assertEqual(code, 2)
            self.assertIn("no migrations folder found", err)


# ---------------------------------------------------------------------------
# nplusone / migration-risk CI format plumbing through main()
# ---------------------------------------------------------------------------


class CiFormatSmokeTest(unittest.TestCase):
    def test_nplusone_sarif_on_clean_fixture_is_valid_empty_run(self) -> None:
        code, out, _err = _run(
            ["nplusone", "--path", str(MINIAPP), "--format", "sarif"]
        )
        self.assertEqual(code, 0)  # no findings -> success exit
        doc = json.loads(out)
        self.assertEqual(doc["version"], "2.1.0")
        run = doc["runs"][0]
        self.assertEqual(run["tool"]["driver"]["name"], "django-orm-lens")
        self.assertEqual(run["results"], [])

    def test_nplusone_sarif_with_finding_exits_1(self) -> None:
        with TemporaryDirectory() as tmp:
            shop = Path(tmp) / "shop"
            _write(
                shop / "models.py",
                "from django.db import models\n\n\n"
                "class Customer(models.Model):\n"
                "    email = models.EmailField()\n\n\n"
                "class Order(models.Model):\n"
                "    customer = models.ForeignKey(Customer,\n"
                "        on_delete=models.CASCADE)\n",
            )
            _write(
                shop / "views.py",
                "from .models import Order\n\n\n"
                "def report():\n"
                "    orders = Order.objects.all()\n"
                "    for order in orders:\n"
                "        print(order.customer.email)\n",
            )
            code, out, _err = _run(
                ["nplusone", "--path", tmp, "--format", "sarif"]
            )
            self.assertEqual(code, 1)  # findings gate the pipeline
            doc = json.loads(out)
            results = doc["runs"][0]["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["ruleId"], "nplusone")
            self.assertEqual(results[0]["level"], "warning")
            uri = results[0]["locations"][0]["physicalLocation"][
                "artifactLocation"
            ]["uri"]
            self.assertEqual(uri, "shop/views.py")

    def test_migration_risk_github_annotates_critical_finding(self) -> None:
        code, out, _err = _run(
            [
                "migration-risk",
                "--path",
                str(MIGRATION_RISKS / "add_field_notnull"),
                "--format",
                "github",
            ]
        )
        self.assertEqual(code, 1)  # critical finding -> exit 1
        lines = out.splitlines()
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertTrue(line.startswith("::error file="), line)
        # Path is relativized against --path so annotations attach in PRs.
        self.assertIn("migrations/0002_add_status.py", line)
        self.assertIn(",line=", line)
        self.assertIn(
            "title=django-orm-lens%3A add_field_not_null_no_default", line
        )

    def test_migration_risk_github_silent_and_green_on_safe_fixture(self) -> None:
        code, out, _err = _run(
            [
                "migration-risk",
                "--path",
                str(MIGRATION_RISKS / "add_field_notnull_safe"),
                "--format",
                "github",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, "")


class MainReturnsIntForInProcessCallers(unittest.TestCase):
    """``main()`` must *return* error codes, never let SystemExit kill the
    host process — the MCP layer and these very tests call it in-process."""

    def test_migration_deps_nondir_path_returns_2(self) -> None:
        code, _out, err = _run(
            ["migration-deps", "someapp", "--path", "definitely/not/a/dir"]
        )
        self.assertEqual(code, 2)
        self.assertIn("is not a directory", err)

    def test_scan_nondir_path_returns_2_instead_of_raising(self) -> None:
        # _load_index still raises SystemExit internally; main() translates.
        code, _out, err = _run(["scan", "--path", "definitely/not/a/dir"])
        self.assertEqual(code, 2)
        self.assertIn("is not a directory", err)


if __name__ == "__main__":
    unittest.main()


class ModuleEntryPointTests(unittest.TestCase):
    """`python -m django_orm_lens` must work wherever the console script does.

    Regression guard: the package shipped without a __main__.py through
    1.5.0, so `python -m django_orm_lens` failed with "No module named
    django_orm_lens.__main__" even though the CLI itself was fine.
    """

    def test_module_invocation_reports_version(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "django_orm_lens", "--version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("django-orm-lens", proc.stdout)

    def test_module_invocation_matches_console_script_help(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "django_orm_lens", "--help"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("scan", proc.stdout)
