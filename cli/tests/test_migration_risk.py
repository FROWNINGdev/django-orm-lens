"""Tests for the migration risk analyzer (analyze_migration_risks).

Each test builds a synthetic ``<app>/migrations/`` layout inside ``tmp_path``
and asserts the emitted :class:`MigrationRisk` set. We cover one positive
and one negative case per rule plus edge cases: empty folder, malformed
file, multi-risk file, and confidence differentiation.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, Iterable, List

from django_orm_lens.migrations_parser import (
    MigrationRisk,
    MigrationRiskAnalyzer,
    analyze_migration_risks,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write(app_dir: Path, name: str, body: str) -> None:
    (app_dir / "migrations").mkdir(parents=True, exist_ok=True)
    (app_dir / "migrations" / f"{name}.py").write_text(body, encoding="utf-8")
    init = app_dir / "migrations" / "__init__.py"
    if not init.exists():
        init.write_text("", encoding="utf-8")


def _by_rule(findings: Iterable[MigrationRisk]) -> Dict[str, List[MigrationRisk]]:
    out: Dict[str, List[MigrationRisk]] = {}
    for f in findings:
        out.setdefault(f.rule, []).append(f)
    return out


def _empty_schema() -> Dict[str, Dict[str, set]]:
    """Explicitly opt out of cross-reference so tests don't accidentally pick
    up the analyzer's own package models. Callers that need cross-ref
    supply their own schema."""
    return {}


# ---------------------------------------------------------------------------
# Rule 1: AddField NOT NULL without default
# ---------------------------------------------------------------------------


class AddFieldNotNullTest(unittest.TestCase):
    def test_positive_add_notnull_no_default_on_populated_table(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app,
                "0001_initial",
                (
                    "from django.db import migrations, models\n\n"
                    "class Migration(migrations.Migration):\n"
                    "    dependencies = []\n"
                    "    operations = [migrations.CreateModel(name='Order', fields=[])]\n"
                ),
            )
            _write(
                app,
                "0002_add_status",
                (
                    "from django.db import migrations, models\n\n"
                    "class Migration(migrations.Migration):\n"
                    "    dependencies = [('orders', '0001_initial')]\n"
                    "    operations = [\n"
                    "        migrations.AddField(model_name='order', name='status',\n"
                    "            field=models.CharField(max_length=20))\n"
                    "    ]\n"
                ),
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            rules = _by_rule(findings)
            self.assertIn("add_field_not_null_no_default", rules)
            f = rules["add_field_not_null_no_default"][0]
            self.assertEqual(f.severity, "critical")
            self.assertEqual(f.confidence, "high")
            self.assertEqual(f.model, "order")
            self.assertEqual(f.field, "status")
            self.assertEqual(f.migration, "0002_add_status")

    def test_negative_with_default_is_safe(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app,
                "0001_initial",
                (
                    "from django.db import migrations, models\n\n"
                    "class Migration(migrations.Migration):\n"
                    "    dependencies = []\n"
                    "    operations = [migrations.CreateModel(name='Order', fields=[])]\n"
                ),
            )
            _write(
                app,
                "0002_add_status",
                (
                    "from django.db import migrations, models\n\n"
                    "class Migration(migrations.Migration):\n"
                    "    dependencies = [('orders', '0001_initial')]\n"
                    "    operations = [\n"
                    "        migrations.AddField(model_name='order', name='status',\n"
                    "            field=models.CharField(max_length=20, default='new'))\n"
                    "    ]\n"
                ),
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertNotIn(
                "add_field_not_null_no_default", _by_rule(findings)
            )

    def test_negative_null_true_is_safe(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n"
                "    operations = []\n",
            )
            _write(
                app, "0002_add_note",
                "from django.db import migrations, models\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.AddField(model_name='order',\n"
                "        name='note', field=models.TextField(null=True))]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertNotIn(
                "add_field_not_null_no_default", _by_rule(findings)
            )

    def test_negative_initial_migration_is_safe(self) -> None:
        """Rule 1 only fires when the table is already populated
        (heuristic: not the first migration in its app)."""
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations, models\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n"
                "    operations = [\n"
                "        migrations.CreateModel(name='Order', fields=[]),\n"
                "        migrations.AddField(model_name='order', name='status',\n"
                "            field=models.CharField(max_length=20)),\n"
                "    ]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertNotIn(
                "add_field_not_null_no_default", _by_rule(findings)
            )


# ---------------------------------------------------------------------------
# Rule 2a/2b: RemoveField / DeleteModel cross-reference
# ---------------------------------------------------------------------------


class RemoveFieldAndDeleteModelTest(unittest.TestCase):
    def test_positive_remove_field_still_referenced(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_drop_status",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.RemoveField(model_name='order',\n"
                "        name='status')]\n",
            )
            schema = {"orders": {"order": {"status", "id"}}}
            findings = analyze_migration_risks(tmp, current_schema=schema)
            rules = _by_rule(findings)
            self.assertIn("remove_field_still_referenced", rules)
            f = rules["remove_field_still_referenced"][0]
            self.assertEqual(f.severity, "critical")
            self.assertEqual(f.confidence, "high")
            self.assertEqual(f.field, "status")

    def test_negative_remove_field_gone_from_current_schema(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_drop_status",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.RemoveField(model_name='order',\n"
                "        name='status')]\n",
            )
            # `status` NOT in schema → safe.
            schema = {"orders": {"order": {"id"}}}
            findings = analyze_migration_risks(tmp, current_schema=schema)
            self.assertNotIn(
                "remove_field_still_referenced", _by_rule(findings)
            )

    def test_positive_delete_model_still_referenced(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_drop_order",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.DeleteModel(name='Order')]\n",
            )
            schema = {"orders": {"order": {"id"}}}
            findings = analyze_migration_risks(tmp, current_schema=schema)
            rules = _by_rule(findings)
            self.assertIn("delete_model_still_referenced", rules)
            self.assertEqual(rules["delete_model_still_referenced"][0].model, "Order")

    def test_negative_delete_model_removed_from_schema(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_drop_order",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.DeleteModel(name='Order')]\n",
            )
            schema = {"orders": {}}  # Order no longer defined
            findings = analyze_migration_risks(tmp, current_schema=schema)
            self.assertNotIn(
                "delete_model_still_referenced", _by_rule(findings)
            )

    def test_unverified_when_schema_unavailable(self) -> None:
        """If we pass ``None`` for schema AND the workspace has no models.py,
        removed field/model gets a low-confidence info flag."""
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_drop_status",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.RemoveField(model_name='order',\n"
                "        name='status')]\n",
            )
            findings = analyze_migration_risks(tmp)  # schema=None → auto-scan
            rules = _by_rule(findings)
            self.assertIn("remove_field_unverified", rules)
            self.assertEqual(rules["remove_field_unverified"][0].confidence, "low")
            self.assertEqual(rules["remove_field_unverified"][0].severity, "info")


# ---------------------------------------------------------------------------
# Rule 3: RenameField / RenameModel
# ---------------------------------------------------------------------------


class RenameOperationsTest(unittest.TestCase):
    def test_rename_field_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_rename",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.RenameField(model_name='order',\n"
                "        old_name='status', new_name='state')]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            rules = _by_rule(findings)
            self.assertIn("rename_field_rolling_deploy", rules)
            f = rules["rename_field_rolling_deploy"][0]
            self.assertEqual(f.severity, "warning")
            self.assertEqual(f.confidence, "medium")

    def test_rename_model_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_rename",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.RenameModel(old_name='Order',\n"
                "        new_name='Purchase')]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertIn("rename_model_rolling_deploy", _by_rule(findings))

    def test_negative_no_renames_no_flag(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n"
                "    operations = [migrations.CreateModel(name='Order', fields=[])]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertEqual(findings, [])


# ---------------------------------------------------------------------------
# Rule 4: AddIndex without CONCURRENTLY
# ---------------------------------------------------------------------------


class AddIndexTest(unittest.TestCase):
    def test_add_index_flagged_on_populated_table(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_index",
                "from django.db import migrations, models\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.AddIndex(model_name='order',\n"
                "        index=models.Index(fields=['status'], name='order_status_idx'))]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertIn("add_index_locks_table", _by_rule(findings))

    def test_add_index_concurrently_is_safe(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_index",
                "from django.db import migrations, models\n"
                "class Migration(migrations.Migration):\n"
                "    atomic = False\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.AddIndexConcurrently(model_name='order',\n"
                "        index=models.Index(fields=['status']))]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertNotIn("add_index_locks_table", _by_rule(findings))


# ---------------------------------------------------------------------------
# Rule 5: AlterField type change
# ---------------------------------------------------------------------------


class AlterFieldTest(unittest.TestCase):
    def test_char_field_length_change_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_shrink",
                "from django.db import migrations, models\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.AlterField(model_name='order',\n"
                "        name='code', field=models.CharField(max_length=8))]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertIn("alter_field_char_length", _by_rule(findings))

    def test_int_widening_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_bigint",
                "from django.db import migrations, models\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.AlterField(model_name='order',\n"
                "        name='qty', field=models.BigIntegerField())]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertIn("alter_field_int_type", _by_rule(findings))

    def test_alter_field_bool_default_is_not_flagged(self) -> None:
        """Changing only the default on a Boolean/other field is not a type
        change we flag under rule 5."""
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_default",
                "from django.db import migrations, models\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [migrations.AlterField(model_name='order',\n"
                "        name='active', field=models.BooleanField(default=True))]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            rules = _by_rule(findings)
            self.assertNotIn("alter_field_char_length", rules)
            self.assertNotIn("alter_field_int_type", rules)


# ---------------------------------------------------------------------------
# Rule 6: RunSQL without reverse_sql
# ---------------------------------------------------------------------------


class RunSQLTest(unittest.TestCase):
    def test_positive_no_reverse_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n"
                "    operations = [migrations.RunSQL(sql='UPDATE orders SET x=1')]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertIn("runsql_no_reverse", _by_rule(findings))

    def test_negative_with_reverse_sql_kwarg(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n"
                "    operations = [migrations.RunSQL(\n"
                "        sql='UPDATE orders SET x=1',\n"
                "        reverse_sql='UPDATE orders SET x=0')]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertNotIn("runsql_no_reverse", _by_rule(findings))

    def test_negative_with_reverse_positional(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n"
                "    operations = [migrations.RunSQL('UP', 'DOWN')]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertNotIn("runsql_no_reverse", _by_rule(findings))


# ---------------------------------------------------------------------------
# Rule 7: AddField unique=True
# ---------------------------------------------------------------------------


class AddFieldUniqueTest(unittest.TestCase):
    def test_positive_unique_no_default_high_confidence(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "users"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_unique_email",
                "from django.db import migrations, models\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('users', '0001_initial')]\n"
                "    operations = [migrations.AddField(model_name='user',\n"
                "        name='email',\n"
                "        field=models.EmailField(unique=True, default=''))]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            rules = _by_rule(findings)
            self.assertIn("add_field_unique_no_row_default", rules)
            f = rules["add_field_unique_no_row_default"][0]
            self.assertEqual(f.confidence, "high")
            self.assertEqual(f.severity, "critical")

    def test_confidence_medium_with_callable_default(self) -> None:
        """A callable default (uuid.uuid4) produces unique values per row →
        confidence medium (still flag as reviewer should verify)."""
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "users"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_unique_token",
                "from django.db import migrations, models\n"
                "import uuid\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('users', '0001_initial')]\n"
                "    operations = [migrations.AddField(model_name='user',\n"
                "        name='token',\n"
                "        field=models.UUIDField(unique=True, default=uuid.uuid4))]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            rules = _by_rule(findings)
            self.assertIn("add_field_unique_no_row_default", rules)
            f = rules["add_field_unique_no_row_default"][0]
            self.assertEqual(f.confidence, "medium")
            self.assertEqual(f.severity, "warning")

    def test_negative_non_unique_no_flag(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "users"
            _write(
                app, "0001_initial",
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = []\n    operations = []\n",
            )
            _write(
                app, "0002_add_name",
                "from django.db import migrations, models\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('users', '0001_initial')]\n"
                "    operations = [migrations.AddField(model_name='user',\n"
                "        name='name', field=models.CharField(max_length=50,\n"
                "        default=''))]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertNotIn(
                "add_field_unique_no_row_default", _by_rule(findings)
            )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class EdgeCaseTest(unittest.TestCase):
    def test_empty_migrations_folder(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            (app / "migrations").mkdir(parents=True)
            (app / "migrations" / "__init__.py").write_text("", encoding="utf-8")
            self.assertEqual(
                analyze_migration_risks(tmp, current_schema=_empty_schema()),
                [],
            )

    def test_no_migrations_folder_at_all(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(
                analyze_migration_risks(tmp, current_schema=_empty_schema()),
                [],
            )

    def test_malformed_migration_file_is_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(app, "0001_initial",
                   "from django.db import migrations\n"
                   "class Migration(migrations.Migration):\n"
                   "    dependencies = []\n    operations = []\n")
            # Malformed follow-up: unbalanced parens, syntax error.
            _write(app, "0002_broken",
                   "from django.db import migrations, models\n\n"
                   "class Migration(migrations.Migration:\n"
                   "    operations = [ [ [ [ \n")
            # Should not crash; good migration below the broken one still parses.
            _write(app, "0003_add",
                   "from django.db import migrations, models\n"
                   "class Migration(migrations.Migration):\n"
                   "    dependencies = [('orders', '0001_initial')]\n"
                   "    operations = [migrations.AddField(model_name='order',\n"
                   "        name='status', field=models.CharField(max_length=20))]\n")
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            self.assertIn(
                "add_field_not_null_no_default", _by_rule(findings)
            )

    def test_multiple_risks_in_one_migration(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(app, "0001_initial",
                   "from django.db import migrations\n"
                   "class Migration(migrations.Migration):\n"
                   "    dependencies = []\n    operations = []\n")
            _write(
                app, "0002_multi",
                "from django.db import migrations, models\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [\n"
                "        migrations.AddField(model_name='order', name='code',\n"
                "            field=models.CharField(max_length=20)),\n"
                "        migrations.RenameField(model_name='order',\n"
                "            old_name='ts', new_name='created_at'),\n"
                "        migrations.RunSQL(sql='UPDATE orders SET x=1'),\n"
                "        migrations.AddIndex(model_name='order',\n"
                "            index=models.Index(fields=['code'])),\n"
                "    ]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            rules = _by_rule(findings)
            self.assertIn("add_field_not_null_no_default", rules)
            self.assertIn("rename_field_rolling_deploy", rules)
            self.assertIn("runsql_no_reverse", rules)
            self.assertIn("add_index_locks_table", rules)

    def test_confidence_differentiation_high_vs_medium(self) -> None:
        """One migration file, two AddField ops — one hits rule 1 (high),
        the other hits rule 7 with a callable default (medium)."""
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "users"
            _write(app, "0001_initial",
                   "from django.db import migrations\n"
                   "class Migration(migrations.Migration):\n"
                   "    dependencies = []\n    operations = []\n")
            _write(
                app, "0002_two_flavors",
                "from django.db import migrations, models\n"
                "import uuid\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('users', '0001_initial')]\n"
                "    operations = [\n"
                "        migrations.AddField(model_name='user', name='role',\n"
                "            field=models.CharField(max_length=20)),\n"
                "        migrations.AddField(model_name='user', name='token',\n"
                "            field=models.UUIDField(unique=True,\n"
                "                default=uuid.uuid4)),\n"
                "    ]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            confidences = {(f.rule, f.confidence) for f in findings}
            self.assertIn(("add_field_not_null_no_default", "high"), confidences)
            self.assertIn(
                ("add_field_unique_no_row_default", "medium"), confidences
            )

    def test_sort_order_critical_before_warning_before_info(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "orders"
            _write(app, "0001_initial",
                   "from django.db import migrations\n"
                   "class Migration(migrations.Migration):\n"
                   "    dependencies = []\n    operations = []\n")
            _write(
                app, "0002_mixed",
                "from django.db import migrations, models\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('orders', '0001_initial')]\n"
                "    operations = [\n"
                "        migrations.RunSQL(sql='SELECT 1'),\n"  # warning
                "        migrations.AddField(model_name='order', name='code',\n"
                "            field=models.CharField(max_length=20)),\n"  # critical
                "    ]\n",
            )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            severities = [f.severity for f in findings]
            # No 'info' present here — just verify critical precedes warning.
            self.assertEqual(severities[0], "critical")
            self.assertIn("warning", severities)
            self.assertLess(
                severities.index("critical"),
                severities.index("warning"),
            )

    def test_skips_venv_and_node_modules(self) -> None:
        with TemporaryDirectory() as tmp:
            # A "real" app + a poisoned copy inside .venv → poisoned must be
            # ignored so we don't flag risks from vendored third-party
            # migrations the user doesn't own.
            for prefix in ("", ".venv/site-packages/"):
                app = Path(tmp) / prefix / "otherapp"
                _write(
                    app, "0001_initial",
                    "from django.db import migrations\n"
                    "class Migration(migrations.Migration):\n"
                    "    dependencies = []\n    operations = []\n",
                )
                _write(
                    app, "0002_add",
                    "from django.db import migrations, models\n"
                    "class Migration(migrations.Migration):\n"
                    "    dependencies = [('otherapp', '0001_initial')]\n"
                    "    operations = [migrations.AddField(model_name='thing',\n"
                    "        name='x', field=models.IntegerField())]\n",
                )
            findings = analyze_migration_risks(tmp, current_schema=_empty_schema())
            # Exactly one hit — the one under the top-level app, not the
            # vendored duplicate under .venv/.
            hits = [
                f for f in findings
                if f.rule == "add_field_not_null_no_default"
            ]
            self.assertEqual(len(hits), 1)
            self.assertNotIn(".venv", hits[0].file_path.replace("\\", "/"))

    def test_direct_analyzer_instance_returns_empty_on_syntax_error(self) -> None:
        """Direct API: MigrationRiskAnalyzer should swallow SyntaxError."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.py"
            path.write_text("class Migration( : ohno\n", encoding="utf-8")
            analyzer = MigrationRiskAnalyzer(
                file_path=path,
                app="broken",
                migration_name="broken",
                migration_index=1,
            )
            self.assertEqual(analyzer.analyze(), [])


if __name__ == "__main__":
    unittest.main()
