"""Tests for static schema-drift detection (django_orm_lens/drift.py).

The replay has to be right in both directions, and the *blocking* decision has
to stay narrow: only "code expects a column that will not exist" fails a
build. Extra columns are noise far more often than bugs, and a static analyzer
cannot see mixin-injected fields — blocking on those would train people to
pass --exit-zero permanently, which costs more than the check is worth.

Run: python -m unittest discover cli/tests -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from django_orm_lens.drift import (
    DriftReport,
    ModelDrift,
    detect_drift,
    format_drift,
    replay_app,
)

HEADER = "from django.db import migrations, models\n\n\n"


def _migration(body: str, deps: str = "[]") -> str:
    return (
        f"{HEADER}class Migration(migrations.Migration):\n"
        f"    dependencies = {deps}\n"
        f"    operations = [\n{body}    ]\n"
    )


class ReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.migrations = self.root / "blog" / "migrations"
        self.migrations.mkdir(parents=True)

    def _write(self, name: str, body: str) -> None:
        (self.migrations / name).write_text(_migration(body), encoding="utf-8")

    def test_create_model_seeds_the_field_set(self) -> None:
        self._write(
            "0001_initial.py",
            '        migrations.CreateModel(name="Post", fields=[\n'
            '            ("id", models.AutoField(primary_key=True)),\n'
            '            ("title", models.CharField(max_length=10)),\n'
            "        ]),\n",
        )
        state, replayed = replay_app(self.migrations)
        self.assertEqual(replayed, 1)
        # `id` is implicit and must not count as drift either way.
        self.assertEqual(state, {"post": {"title"}})

    def test_add_and_remove_field(self) -> None:
        self._write(
            "0001_initial.py",
            '        migrations.CreateModel(name="Post", fields=[("title", None)]),\n',
        )
        self._write(
            "0002_x.py",
            '        migrations.AddField(model_name="post", name="slug",'
            " field=models.CharField(max_length=1)),\n"
            '        migrations.RemoveField(model_name="post", name="title"),\n',
        )
        state, _ = replay_app(self.migrations)
        self.assertEqual(state, {"post": {"slug"}})

    def test_rename_field_moves_the_name(self) -> None:
        self._write(
            "0001_initial.py",
            '        migrations.CreateModel(name="Post", fields=[("title", None)]),\n',
        )
        self._write(
            "0002_x.py",
            '        migrations.RenameField(model_name="post",'
            ' old_name="title", new_name="headline"),\n',
        )
        state, _ = replay_app(self.migrations)
        self.assertEqual(state, {"post": {"headline"}})

    def test_rename_model_carries_the_fields(self) -> None:
        self._write(
            "0001_initial.py",
            '        migrations.CreateModel(name="Post", fields=[("title", None)]),\n',
        )
        self._write(
            "0002_x.py",
            '        migrations.RenameModel(old_name="Post", new_name="Article"),\n',
        )
        state, _ = replay_app(self.migrations)
        self.assertEqual(state, {"article": {"title"}})

    def test_delete_model_drops_it(self) -> None:
        self._write(
            "0001_initial.py",
            '        migrations.CreateModel(name="Post", fields=[("title", None)]),\n',
        )
        self._write("0002_x.py", '        migrations.DeleteModel(name="Post"),\n')
        self.assertEqual(replay_app(self.migrations)[0], {})

    def test_alter_field_changes_nothing_structural(self) -> None:
        self._write(
            "0001_initial.py",
            '        migrations.CreateModel(name="Post", fields=[("title", None)]),\n',
        )
        self._write(
            "0002_x.py",
            '        migrations.AlterField(model_name="post", name="title",'
            " field=models.TextField()),\n",
        )
        self.assertEqual(replay_app(self.migrations)[0], {"post": {"title"}})

    def test_migrations_apply_in_numeric_order(self) -> None:
        # 0010 must land after 0002, which string sorting would get wrong.
        self._write(
            "0001_initial.py",
            '        migrations.CreateModel(name="Post", fields=[("title", None)]),\n',
        )
        self._write(
            "0002_add.py",
            '        migrations.AddField(model_name="post", name="slug",'
            " field=None),\n",
        )
        self._write(
            "0010_drop.py",
            '        migrations.RemoveField(model_name="post", name="slug"),\n',
        )
        self.assertEqual(replay_app(self.migrations)[0], {"post": {"title"}})

    def test_unparseable_migration_is_skipped_not_fatal(self) -> None:
        self._write(
            "0001_initial.py",
            '        migrations.CreateModel(name="Post", fields=[("title", None)]),\n',
        )
        (self.migrations / "0002_broken.py").write_text("def (((", encoding="utf-8")
        state, replayed = replay_app(self.migrations)
        # One bad file must not blank out the app's state.
        self.assertEqual(state, {"post": {"title"}})
        self.assertEqual(replayed, 1)


class DetectDriftTest(unittest.TestCase):
    def setUp(self) -> None:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        migrations = self.root / "blog" / "migrations"
        migrations.mkdir(parents=True)
        (migrations / "0001_initial.py").write_text(
            _migration(
                '        migrations.CreateModel(name="Post", fields=[\n'
                '            ("id", None), ("title", None),\n'
                "        ]),\n"
            ),
            encoding="utf-8",
        )

    def _detect(self, declared: dict) -> DriftReport:
        return detect_drift(self.root, declared=declared)

    def test_matching_schema_reports_no_drift(self) -> None:
        report = self._detect({"blog": {"post": {"id", "title"}}})
        self.assertEqual(report.drifted, [])
        self.assertEqual(report.blocking_count, 0)
        self.assertIn("no drift", format_drift(report))

    def test_declared_but_unmigrated_field_blocks(self) -> None:
        report = self._detect({"blog": {"post": {"title", "slug"}}})
        self.assertEqual(len(report.drifted), 1)
        d = report.drifted[0]
        self.assertEqual(d.missing_in_migrations, ["slug"])
        self.assertTrue(d.is_blocking)
        self.assertIn("declared but never migrated", format_drift(report))

    def test_migrated_but_undeclared_field_does_not_block(self) -> None:
        report = self._detect({"blog": {"post": set()}})
        d = report.drifted[0]
        self.assertEqual(d.missing_in_models, ["title"])
        self.assertFalse(d.is_blocking)
        self.assertEqual(report.blocking_count, 0)

    def test_model_with_no_migration_blocks(self) -> None:
        report = self._detect({"blog": {"post": {"title"}, "tag": {"name"}}})
        tag = next(d for d in report.drifted if d.model == "tag")
        self.assertTrue(tag.only_in_models)
        self.assertTrue(tag.is_blocking)

    def test_model_only_in_migrations_does_not_block(self) -> None:
        report = self._detect({"blog": {}})
        d = report.drifted[0]
        self.assertTrue(d.only_in_migrations)
        self.assertFalse(d.is_blocking)

    def test_implicit_id_is_never_drift(self) -> None:
        # Declared without `id`, migrated with it — Django adds it either way.
        self.assertEqual(self._detect({"blog": {"post": {"title"}}}).drifted, [])

    def test_blocking_entries_sort_first(self) -> None:
        report = self._detect({"blog": {"post": set(), "tag": {"name"}}})
        self.assertTrue(report.drifted[0].is_blocking)

    def test_json_shape(self) -> None:
        payload = self._detect({"blog": {"post": {"title", "slug"}}}).to_dict()
        self.assertEqual(payload["summary"]["blocking"], 1)
        self.assertEqual(payload["drifted"][0]["missingInMigrations"], ["slug"])
        self.assertTrue(payload["drifted"][0]["blocking"])


class BlockingPolicyTest(unittest.TestCase):
    """The narrow blocking rule is a deliberate contract, so pin it."""

    def test_only_the_dangerous_direction_blocks(self) -> None:
        self.assertTrue(ModelDrift("a", "m", missing_in_migrations=["x"]).is_blocking)
        self.assertTrue(ModelDrift("a", "m", only_in_models=True).is_blocking)
        self.assertFalse(ModelDrift("a", "m", missing_in_models=["x"]).is_blocking)
        self.assertFalse(ModelDrift("a", "m", only_in_migrations=True).is_blocking)


if __name__ == "__main__":
    unittest.main()
