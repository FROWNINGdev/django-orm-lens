"""Tests for the Python impact analyzer (cli/django_orm_lens/impact.py).

Mirrors the intent of the TypeScript impact-analysis tests — the two
implementations must classify the same line the same way, so these cases are
deliberately written against the same inputs.

Run: python -m unittest discover cli/tests -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from django_orm_lens.impact import (
    ImpactFinding,
    classify_line,
    detect_layer,
    group_by_layer,
    scan_file_text,
    scan_impact,
    sort_key,
)


class DetectLayerTest(unittest.TestCase):
    def test_recognises_each_django_layer(self) -> None:
        cases = {
            "blog/models.py": "models",
            "blog/models/post.py": "models",
            "blog/serializers.py": "serializers",
            "blog/forms.py": "forms",
            "blog/admin.py": "admin",
            "blog/views.py": "views",
            "blog/viewsets.py": "views",
            "blog/urls.py": "urls",
            "blog/templates/blog/post.html": "templates",
            "blog/jinja2/post.html": "templates",
            "blog/tests.py": "tests",
            "blog/tests/test_post.py": "tests",
            "blog/test_post.py": "tests",
            "blog/migrations/0002_add_author.py": "migrations",
            "scripts/backfill.py": "other",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(detect_layer(path), expected)

    def test_windows_separators_are_normalised(self) -> None:
        self.assertEqual(detect_layer(r"C:\proj\blog\admin.py"), "admin")

    def test_tests_beat_models_for_a_test_named_models(self) -> None:
        # A file under tests/ that happens to be called models.py is a test —
        # layer detection is ordered, and tests are checked first.
        self.assertEqual(detect_layer("blog/tests/models.py"), "tests")


class ClassifyLineTest(unittest.TestCase):
    def test_comment_and_docstring_lines_are_ignored(self) -> None:
        self.assertIsNone(classify_line("views", "# author is gone", "author"))
        self.assertIsNone(classify_line("views", '"""author docs"""', "author"))

    def test_line_without_the_needle_is_ignored(self) -> None:
        self.assertIsNone(classify_line("views", "qs = Post.objects.all()", "author"))

    def test_orm_string_reference_is_certain(self) -> None:
        got = classify_line("views", 'qs.order_by("-author")', "author")
        self.assertEqual(got, ("certain", "ORM string reference"))

    def test_orm_kwarg_reference_is_certain(self) -> None:
        got = classify_line("views", "Post.objects.filter(author__id=1)", "author")
        self.assertEqual(got, ("certain", "ORM keyword-arg reference"))

    def test_fields_tuple_is_certain(self) -> None:
        got = classify_line("serializers", "    fields = ['author', 'title']", "author")
        self.assertEqual(
            got,
            ("certain", "declared in fields/list_display/search_fields tuple"),
        )

    def test_template_variable_is_likely(self) -> None:
        got = classify_line("templates", "<p>{{ post.author }}</p>", "author")
        self.assertEqual(got, ("likely", "template variable"))

    def test_attribute_access_in_a_known_layer_is_likely(self) -> None:
        got = classify_line("views", "name = post.author.name", "author")
        self.assertEqual(got, ("likely", "views attribute access"))

    def test_attribute_access_outside_known_layers_is_possibly(self) -> None:
        got = classify_line("other", "name = post.author.name", "author")
        self.assertEqual(got, ("possibly", "attribute access, layer unclear"))

    def test_bare_identifier_falls_back_to_possibly(self) -> None:
        got = classify_line("views", "author = resolve()", "author")
        self.assertEqual(got, ("possibly", "bare identifier match"))

    def test_lookup_suffix_counts_as_a_reference(self) -> None:
        # `author__id` has no word boundary between `r` and `_`, so a plain
        # \b...\b probe alone would miss it.
        self.assertIsNotNone(
            classify_line("views", "Post.objects.filter(author__id=1)", "author")
        )

    def test_needle_with_regex_metacharacters_is_escaped(self) -> None:
        # Must not raise, and must not match an unrelated line.
        self.assertIsNone(classify_line("views", "unrelated line", "a.b"))


class ScanFileTextTest(unittest.TestCase):
    def test_reports_line_and_column_zero_based(self) -> None:
        text = "import os\nqs = Post.objects.filter(author__id=1)\n"
        found = scan_file_text("blog/views.py", text, "author")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].line, 1)
        self.assertEqual(found[0].column, text.splitlines()[1].index("author"))
        self.assertEqual(found[0].layer, "views")
        self.assertEqual(found[0].confidence, "certain")

    def test_snippet_is_trimmed_and_capped(self) -> None:
        text = "    " + "x" * 400 + " author\n"
        found = scan_file_text("blog/views.py", text, "author")
        self.assertEqual(len(found), 1)
        self.assertLessEqual(len(found[0].snippet), 200)
        self.assertFalse(found[0].snippet.startswith(" "))

    def test_handles_crlf_line_endings(self) -> None:
        text = "import os\r\nqs = Post.objects.filter(author=1)\r\n"
        found = scan_file_text("blog/views.py", text, "author")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].line, 1)

    def test_no_matches_returns_empty(self) -> None:
        self.assertEqual(scan_file_text("blog/views.py", "x = 1\n", "author"), [])


class SortAndGroupTest(unittest.TestCase):
    def _f(
        self, layer: str, confidence: str, path: str = "a.py", line: int = 0
    ) -> ImpactFinding:
        return ImpactFinding(
            layer=layer,
            confidence=confidence,
            file_path=path,
            line=line,
            column=0,
            snippet="",
            reason="",
        )

    def test_models_sort_before_templates(self) -> None:
        items = [self._f("templates", "certain"), self._f("models", "possibly")]
        items.sort(key=sort_key)
        self.assertEqual(items[0].layer, "models")

    def test_certain_sorts_before_possibly_within_a_layer(self) -> None:
        items = [self._f("views", "possibly"), self._f("views", "certain")]
        items.sort(key=sort_key)
        self.assertEqual(items[0].confidence, "certain")

    def test_group_by_layer_preserves_canonical_order(self) -> None:
        grouped = group_by_layer(
            [self._f("templates", "likely"), self._f("models", "certain")]
        )
        self.assertEqual(list(grouped), ["models", "templates"])


class ScanImpactTest(unittest.TestCase):
    def test_walks_a_workspace_and_skips_the_definition_site(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "blog").mkdir()
            models = root / "blog" / "models.py"
            models.write_text(
                "class Post(models.Model):\n"
                "    author = models.ForeignKey('User')\n",
                encoding="utf-8",
            )
            (root / "blog" / "views.py").write_text(
                "qs = Post.objects.filter(author__id=1)\n", encoding="utf-8"
            )

            everything = scan_impact(root, "author")
            self.assertEqual({f.layer for f in everything}, {"models", "views"})

            without_definition = scan_impact(root, "author", skip_files=[str(models)])
            self.assertEqual({f.layer for f in without_definition}, {"views"})

    def test_scans_templates_and_migrations_but_skips_vendored_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "blog" / "templates" / "blog").mkdir(parents=True)
            (root / "blog" / "templates" / "blog" / "post.html").write_text(
                "<p>{{ post.author }}</p>\n", encoding="utf-8"
            )
            (root / "blog" / "migrations").mkdir(parents=True)
            (root / "blog" / "migrations" / "0002_x.py").write_text(
                "field = 'author'\n", encoding="utf-8"
            )
            (root / "node_modules" / "pkg").mkdir(parents=True)
            (root / "node_modules" / "pkg" / "views.py").write_text(
                "post.author\n", encoding="utf-8"
            )
            (root / ".venv" / "lib").mkdir(parents=True)
            (root / ".venv" / "lib" / "views.py").write_text(
                "post.author\n", encoding="utf-8"
            )

            found = scan_impact(root, "author")
            layers = {f.layer for f in found}
            # migrations are deliberately in scope for impact analysis, unlike
            # every other analyzer in the package.
            self.assertIn("templates", layers)
            self.assertIn("migrations", layers)
            paths = {f.file_path for f in found}
            self.assertFalse(any("node_modules" in p for p in paths))
            self.assertFalse(any(".venv" in p for p in paths))

    def test_undecodable_bytes_do_not_abort_the_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "blog").mkdir()
            (root / "blog" / "views.py").write_bytes(b"\xff\xfe post.author\n")
            scan_impact(root, "author")  # must not raise


if __name__ == "__main__":
    unittest.main()
