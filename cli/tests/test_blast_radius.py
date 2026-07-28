"""Tests for the blast-radius composer (cli/django_orm_lens/blast_radius.py).

Runs against tests/fixtures/blast_radius — a two-migration app whose second
migration drops a field that models.py, views.py, serializers.py and a
template all still reference.

Run: python -m unittest discover cli/tests -v
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from django_orm_lens.blast_radius import (
    COMMENT_MARKER,
    DESTRUCTIVE_OPERATIONS,
    analyze_blast_radius,
    format_markdown,
    format_text,
)
from django_orm_lens.ci_formats import blast_radius_github
from django_orm_lens.impact import layer_of
from django_orm_lens.parser import scan_workspace

FIXTURE = Path(__file__).parent / "fixtures" / "blast_radius"


class BlastRadiusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = analyze_blast_radius(FIXTURE)

    def test_destructive_operation_becomes_a_target(self) -> None:
        self.assertEqual(len(self.report.targets), 1)
        target = self.report.targets[0]
        self.assertEqual(target.field, "author")
        self.assertIn("RemoveField", target.operations)
        self.assertEqual(target.worst_severity, "critical")

    def test_target_label_reads_app_model_field(self) -> None:
        self.assertEqual(self.report.targets[0].label, "blog.post.author")

    def test_impact_finds_the_code_that_still_reads_the_field(self) -> None:
        layers = {f.layer for f in self.report.targets[0].impact}
        self.assertIn("views", layers)
        self.assertIn("serializers", layers)
        self.assertIn("templates", layers)

    def test_certain_references_are_counted(self) -> None:
        counts = self.report.targets[0].impact_counts()
        # `filter(author__id=...)` and `fields = [... "author"]` are both
        # unambiguous ORM references.
        self.assertGreaterEqual(counts["certain"], 2)

    def test_critical_count_drives_the_exit_code(self) -> None:
        self.assertGreaterEqual(self.report.critical_count, 1)

    def test_add_field_is_never_a_target(self) -> None:
        # Adding a column cannot orphan a reader, so it belongs in the
        # unscanned bucket rather than getting a reference scan.
        self.assertNotIn("AddField", DESTRUCTIVE_OPERATIONS)

    def test_only_migrations_filter_narrows_the_scan(self) -> None:
        nothing = analyze_blast_radius(
            FIXTURE, only_migrations=["blog/migrations/9999_nonexistent.py"]
        )
        self.assertEqual(nothing.targets, [])
        self.assertEqual(nothing.unscanned_risks, [])

        target_file = str(FIXTURE / "blog" / "migrations" / "0002_drop_author.py")
        narrowed = analyze_blast_radius(FIXTURE, only_migrations=[target_file])
        self.assertEqual(len(narrowed.targets), 1)

    def test_cascade_is_absent_without_an_index(self) -> None:
        self.assertIsNone(self.report.targets[0].cascade)

    def test_index_enables_cascade_only_for_model_level_operations(self) -> None:
        index = scan_workspace(str(FIXTURE))
        with_index = analyze_blast_radius(FIXTURE, index=index)
        # This fixture's only target is field-level, so cascade stays None
        # even when the index is available.
        self.assertIsNone(with_index.targets[0].cascade)


class RenderingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = analyze_blast_radius(FIXTURE)

    def test_text_output_names_target_rule_and_reference_count(self) -> None:
        out = format_text(self.report, FIXTURE)
        self.assertIn("blog.post.author", out)
        self.assertIn("remove_field_still_referenced", out)
        self.assertIn("still referenced in", out)
        self.assertIn("summary:", out)

    def test_text_paths_are_repo_relative(self) -> None:
        out = format_text(self.report, FIXTURE)
        self.assertIn("blog/migrations/0002_drop_author.py", out)
        self.assertNotIn(str(FIXTURE), out)

    def test_markdown_is_a_postable_pr_comment(self) -> None:
        out = format_markdown(self.report, FIXTURE)
        self.assertIn("### Django ORM Lens — blast radius", out)
        self.assertIn("<details>", out)
        self.assertIn("| Layer | Confidence | Location | Code |", out)

    def test_markdown_starts_with_the_upsert_marker(self) -> None:
        # CI finds its own previous comment by this exact first line; if it
        # moves or changes, the bot starts posting a new comment per push.
        for report in (self.report, analyze_blast_radius(FIXTURE, risks=[])):
            out = format_markdown(report, FIXTURE)
            self.assertEqual(out.splitlines()[0], COMMENT_MARKER)
            self.assertEqual(out.count(COMMENT_MARKER), 1)

    def test_markdown_escapes_pipes_so_the_table_survives(self) -> None:
        out = format_markdown(self.report, FIXTURE)
        for line in out.splitlines():
            if line.startswith("| ") and "`" in line:
                # 5 pipes = 4 columns; an unescaped pipe inside a snippet
                # would push the count higher and break the table.
                self.assertEqual(line.count("|") - line.count("\\|"), 5)

    def test_github_annotations_point_at_the_migration_line(self) -> None:
        out = blast_radius_github(self.report, str(FIXTURE))
        self.assertIn("::error", out)
        self.assertIn("file=blog/migrations/0002_drop_author.py", out)
        self.assertIn("certain reference(s)", out)

    def test_empty_report_says_so_in_both_renderers(self) -> None:
        empty = analyze_blast_radius(FIXTURE, risks=[])
        self.assertIn("nothing to review", format_text(empty, FIXTURE))
        self.assertIn("Nothing to review", format_markdown(empty, FIXTURE))

    def test_json_shape_is_serialisable(self) -> None:
        payload = json.loads(json.dumps(self.report.to_dict()))
        self.assertEqual(payload["summary"]["targets"], 1)
        self.assertIn("byLayer", payload["targets"][0]["impact"])


class LayerOfTest(unittest.TestCase):
    """Regression: classification must run on the repo-relative path.

    A project checked out under a directory called ``tests`` — which is
    exactly what happens to these fixtures — used to have every one of its
    files classified as the ``tests`` layer.
    """

    def test_workspace_relative_classification(self) -> None:
        root = Path("/home/dev/tests/shop").resolve()
        self.assertEqual(layer_of(root, root / "blog" / "views.py"), "views")
        self.assertEqual(
            layer_of(root, root / "blog" / "serializers.py"), "serializers"
        )

    def test_a_real_tests_dir_inside_the_project_still_wins(self) -> None:
        root = Path("/home/dev/shop").resolve()
        self.assertEqual(
            layer_of(root, root / "blog" / "tests" / "test_views.py"), "tests"
        )

    def test_fixture_files_classify_by_their_project_role(self) -> None:
        # The fixture lives under cli/tests/, so this is the live regression.
        self.assertEqual(layer_of(FIXTURE, FIXTURE / "blog" / "views.py"), "views")


if __name__ == "__main__":
    unittest.main()
