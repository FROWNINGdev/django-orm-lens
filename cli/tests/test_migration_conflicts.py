"""Graph-level migration conflict detection.

Django refuses to migrate an app whose migration graph has more than one leaf
("Conflicting migrations detected; multiple leaf nodes in the migration
graph"). The negative cases matter as much as the positive one: a merge
migration is exactly what a user writes to *fix* the conflict, so flagging it
would send them in circles.
"""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from django_orm_lens.migrations_parser import analyze_migration_risks

RULE = "conflicting_migration_leaves"


def _project(files: list[tuple[str, str]]) -> str:
    """Build a throwaway app whose migrations have the given dependencies."""
    tmp = TemporaryDirectory()
    _project._keep.append(tmp)  # type: ignore[attr-defined]
    mig = Path(tmp.name) / "shop" / "migrations"
    mig.mkdir(parents=True)
    (mig / "__init__.py").write_text("", encoding="utf-8")
    for name, deps in files:
        (mig / name).write_text(
            textwrap.dedent(
                f"""
                from django.db import migrations


                class Migration(migrations.Migration):
                    dependencies = {deps}
                    operations = []
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
    return tmp.name


_project._keep = []  # type: ignore[attr-defined]


def _conflicts(root: str):
    return [r for r in analyze_migration_risks(root, current_schema={}) if r.rule == RULE]


class MigrationConflictTests(unittest.TestCase):
    def test_two_branches_on_the_same_parent_conflict(self) -> None:
        root = _project(
            [
                ("0001_initial.py", "[]"),
                ("0002_alice.py", "[('shop', '0001_initial')]"),
                ("0002_bob.py", "[('shop', '0001_initial')]"),
            ]
        )
        found = _conflicts(root)
        # One finding per leaf, so every conflicting file is annotated in a PR
        # rather than only whichever one sorted first.
        self.assertEqual(len(found), 2)
        self.assertEqual({r.migration for r in found}, {"0002_alice", "0002_bob"})
        for r in found:
            self.assertEqual(r.severity, "critical")
            self.assertIn("leaf", r.description)
            self.assertIn("--merge", r.mitigation)

    def test_each_finding_names_the_migration_it_conflicts_with(self) -> None:
        root = _project(
            [
                ("0001_initial.py", "[]"),
                ("0002_alice.py", "[('shop', '0001_initial')]"),
                ("0002_bob.py", "[('shop', '0001_initial')]"),
            ]
        )
        by_name = {r.migration: r for r in _conflicts(root)}
        self.assertIn("0002_bob", by_name["0002_alice"].description)
        self.assertIn("0002_alice", by_name["0002_bob"].description)

    def test_linear_history_is_clean(self) -> None:
        root = _project(
            [
                ("0001_initial.py", "[]"),
                ("0002_a.py", "[('shop', '0001_initial')]"),
                ("0003_b.py", "[('shop', '0002_a')]"),
            ]
        )
        self.assertEqual(_conflicts(root), [])

    def test_single_migration_is_clean(self) -> None:
        self.assertEqual(_conflicts(_project([("0001_initial.py", "[]")])), [])

    def test_merge_migration_resolves_the_conflict(self) -> None:
        """The fix must not keep reporting the problem."""
        root = _project(
            [
                ("0001_initial.py", "[]"),
                ("0002_a.py", "[('shop', '0001_initial')]"),
                ("0002_b.py", "[('shop', '0001_initial')]"),
                ("0003_merge.py", "[('shop', '0002_a'), ('shop', '0002_b')]"),
            ]
        )
        self.assertEqual(_conflicts(root), [])

    def test_cross_app_dependency_is_not_a_leaf_of_this_app(self) -> None:
        """Only in-app edges decide leafness; a dependency on another app's
        migration must not make this app look like it has extra roots."""
        root = _project(
            [
                ("0001_initial.py", "[]"),
                ("0002_a.py", "[('other', '0001_initial'), ('shop', '0001_initial')]"),
            ]
        )
        self.assertEqual(_conflicts(root), [])


    def test_app_label_differing_from_directory_name_is_not_a_conflict(self) -> None:
        """Django lets `AppConfig.label` differ from the package directory, and
        dependency tuples carry the *label*. Computing leafness against the
        directory name then finds no in-app edges and calls every migration a
        leaf — which reported a critical conflict for a linear history. Caught
        by two pre-existing CI-format tests whose fixture does exactly this."""
        tmp = TemporaryDirectory()
        _project._keep.append(tmp)  # type: ignore[attr-defined]
        mig = Path(tmp.name) / "checkout_app" / "migrations"
        mig.mkdir(parents=True)
        (mig / "__init__.py").write_text("", encoding="utf-8")
        for name, deps in [
            ("0001_initial.py", "[]"),
            ("0002_next.py", "[('orders', '0001_initial')]"),
        ]:
            (mig / name).write_text(
                textwrap.dedent(
                    f"""
                    from django.db import migrations


                    class Migration(migrations.Migration):
                        dependencies = {deps}
                        operations = []
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
        self.assertEqual(_conflicts(tmp.name), [])


if __name__ == "__main__":
    unittest.main()
