"""Tests for the three newest migration-risk rules.

``runpython_no_reverse``, ``alter_unique_together_lock``, and
``alter_index_together_deprecated`` shipped after the original rule 1-7
suite in test_migration_risk.py and had no coverage of their own — a
regression in any of them would only surface as a user-visible false
positive/negative. Same fixture mechanics as the original suite: build a
synthetic ``<app>/migrations/000N_*.py`` layout in a temp dir, run
``analyze_migration_risks``, assert on the emitted rule set.
"""

from __future__ import annotations

import unittest
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory

from django_orm_lens.migrations_parser import (
    MigrationRisk,
    analyze_migration_risks,
)

# ---------------------------------------------------------------------------
# helpers (mirror test_migration_risk.py)
# ---------------------------------------------------------------------------


def _write(app_dir: Path, name: str, body: str) -> None:
    (app_dir / "migrations").mkdir(parents=True, exist_ok=True)
    (app_dir / "migrations" / f"{name}.py").write_text(body, encoding="utf-8")
    init = app_dir / "migrations" / "__init__.py"
    if not init.exists():
        init.write_text("", encoding="utf-8")


def _by_rule(findings: Iterable[MigrationRisk]) -> dict[str, list[MigrationRisk]]:
    out: dict[str, list[MigrationRisk]] = {}
    for f in findings:
        out.setdefault(f.rule, []).append(f)
    return out


_EMPTY_INITIAL = (
    "from django.db import migrations\n"
    "class Migration(migrations.Migration):\n"
    "    dependencies = []\n    operations = []\n"
)


# ---------------------------------------------------------------------------
# Rule: RunPython without reverse_code
# ---------------------------------------------------------------------------


class RunPythonNoReverseTest(unittest.TestCase):
    def test_positive_forward_only_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(app, "0001_initial", _EMPTY_INITIAL)
            _write(
                app, "0002_backfill",
                "from django.db import migrations\n\n"
                "def forward(apps, schema_editor):\n"
                "    pass\n\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.RunPython(forward)]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema={})
            rules = _by_rule(findings)
            self.assertIn("runpython_no_reverse", rules)
            f = rules["runpython_no_reverse"][0]
            self.assertEqual(f.severity, "warning")
            self.assertEqual(f.confidence, "medium")
            self.assertEqual(f.operation, "RunPython")
            self.assertEqual(f.migration, "0002_backfill")

    def test_negative_positional_noop_reverse(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(app, "0001_initial", _EMPTY_INITIAL)
            _write(
                app, "0002_backfill",
                "from django.db import migrations\n\n"
                "def forward(apps, schema_editor):\n"
                "    pass\n\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.RunPython(\n"
                "        forward, migrations.RunPython.noop)]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema={})
            self.assertNotIn("runpython_no_reverse", _by_rule(findings))

    def test_negative_keyword_reverse_code(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(app, "0001_initial", _EMPTY_INITIAL)
            _write(
                app, "0002_backfill",
                "from django.db import migrations\n\n"
                "def forward(apps, schema_editor):\n"
                "    pass\n\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.RunPython(\n"
                "        code=forward,\n"
                "        reverse_code=migrations.RunPython.noop)]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema={})
            self.assertNotIn("runpython_no_reverse", _by_rule(findings))


# ---------------------------------------------------------------------------
# Rule: AlterUniqueTogether on a populated table
# ---------------------------------------------------------------------------


class AlterUniqueTogetherLockTest(unittest.TestCase):
    def test_positive_on_populated_table(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(app, "0001_initial", _EMPTY_INITIAL)
            _write(
                app, "0002_unique",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.AlterUniqueTogether(\n"
                "        name='order', unique_together={('a', 'b')})]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema={})
            rules = _by_rule(findings)
            self.assertIn("alter_unique_together_lock", rules)
            f = rules["alter_unique_together_lock"][0]
            self.assertEqual(f.severity, "warning")
            self.assertEqual(f.confidence, "medium")
            self.assertEqual(f.model, "order")

    def test_negative_in_initial_migration(self) -> None:
        """Empty-table heuristic: the very first migration of an app creates
        the table, so the unique index builds against zero rows — safe."""
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n"
                "    operations = [migrations.AlterUniqueTogether(\n"
                "        name='order', unique_together={('a', 'b')})]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema={})
            self.assertNotIn("alter_unique_together_lock", _by_rule(findings))

    def test_negative_clearing_constraint_with_empty_literal(self) -> None:
        """Removing the constraint (empty collection literal) is safe — no
        index is built, nothing validates against existing rows."""
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(app, "0001_initial", _EMPTY_INITIAL)
            _write(
                app, "0002_clear",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.AlterUniqueTogether(\n"
                "        name='order', unique_together=[])]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema={})
            self.assertNotIn("alter_unique_together_lock", _by_rule(findings))


def test_clearing_constraint_with_set_call_is_not_flagged() -> None:
    """``unique_together=set()`` is what makemigrations writes when the
    constraint is removed; semantically identical to ``[]`` and just as
    safe. The analyzer accepts the ``set()`` call form alongside the
    empty literals."""
    with TemporaryDirectory() as tmp:
        app = Path(tmp) / "orders"
        _write(app, "0001_initial", _EMPTY_INITIAL)
        _write(
            app, "0002_clear",
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('orders', '0001_initial')]\n"
            "    operations = [migrations.AlterUniqueTogether(\n"
            "        name='order', unique_together=set())]\n",
        )
        findings = analyze_migration_risks(tmp, current_schema={})
        assert "alter_unique_together_lock" not in _by_rule(findings)


# ---------------------------------------------------------------------------
# Rule: AlterIndexTogether is deprecated/removed
# ---------------------------------------------------------------------------


class AlterIndexTogetherDeprecatedTest(unittest.TestCase):
    def test_flagged_in_later_migration(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(app, "0001_initial", _EMPTY_INITIAL)
            _write(
                app, "0002_index",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.AlterIndexTogether(\n"
                "        name='order', index_together={('a', 'b')})]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema={})
            rules = _by_rule(findings)
            self.assertIn("alter_index_together_deprecated", rules)
            f = rules["alter_index_together_deprecated"][0]
            self.assertEqual(f.severity, "info")
            self.assertEqual(f.confidence, "high")
            self.assertEqual(f.model, "order")

    def test_flagged_even_in_initial_migration(self) -> None:
        """Unlike the lock rules, deprecation does not depend on table
        contents — the operation fails to import on Django 5.1 no matter
        which migration it sits in, so 0001_initial must be flagged too."""
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n"
                "    operations = [migrations.AlterIndexTogether(\n"
                "        name='order', index_together={('a', 'b')})]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema={})
            self.assertIn(
                "alter_index_together_deprecated", _by_rule(findings)
            )


if __name__ == "__main__":
    unittest.main()
