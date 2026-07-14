"""Cross-language parity test — Python mirror of test/parity.test.js.

Both tests parse the same fixture (test/fixtures/parity_input.py) and assert
the same structural shape. If either parser drifts, one test breaks and the
mismatch surfaces in review before it lands.

Run: python -m unittest discover cli/tests -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

from django_orm_lens.parser import _extract_on_delete, parse_models_file

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "test" / "fixtures" / "parity_input.py"


class ParityFixtureTest(unittest.TestCase):
    def test_model_shape_matches_golden_expectations(self) -> None:
        source = FIXTURE_PATH.read_text(encoding="utf-8")
        models = parse_models_file(str(FIXTURE_PATH), source)

        self.assertEqual(len(models), 4, "four top-level model classes")
        self.assertEqual(
            [m.name for m in models],
            ["Author", "Book", "Tag", "BookTag"],
        )

        for m in models:
            self.assertEqual(m.app_name, "fixtures", f"{m.name}: app_name derived from parent dir")

        author = models[0]
        self.assertEqual(len(author.fields), 1)
        self.assertEqual(author.fields[0].name, "name")
        self.assertEqual(author.fields[0].type, "CharField")
        self.assertFalse(author.fields[0].is_relation)

        book = models[1]
        self.assertEqual(len(book.fields), 4, "title + author + editor + tags")
        self.assertEqual(book.meta, {"ordering": "['title']"})

        author_field = next(f for f in book.fields if f.name == "author")
        self.assertEqual(author_field.type, "ForeignKey")
        self.assertTrue(author_field.is_relation)
        self.assertEqual(author_field.relation_kind, "ForeignKey")
        self.assertEqual(author_field.related_model, "Author")
        self.assertEqual(author_field.on_delete, "CASCADE")
        self.assertEqual(author_field.related_name, "books")

        editor_field = next(f for f in book.fields if f.name == "editor")
        self.assertEqual(editor_field.relation_kind, "OneToOneField")
        self.assertEqual(editor_field.on_delete, "SET_NULL")
        self.assertEqual(editor_field.related_name, "edited_book")

        tags_field = next(f for f in book.fields if f.name == "tags")
        self.assertEqual(tags_field.relation_kind, "ManyToManyField")
        self.assertEqual(tags_field.related_model, "Tag")
        self.assertEqual(tags_field.through_model, "BookTag")

        book_tag = models[3]
        self.assertEqual(len(book_tag.fields), 2)
        self.assertEqual(book_tag.fields[0].name, "book")
        self.assertEqual(book_tag.fields[0].on_delete, "CASCADE")
        self.assertEqual(book_tag.fields[1].name, "tag")


class ExtractOnDeleteTest(unittest.TestCase):
    """Regression tests for _extract_on_delete callable-form fix (py-1.0.10)."""

    def test_bare_identifier_forms(self) -> None:
        self.assertEqual(_extract_on_delete("on_delete=CASCADE"), "CASCADE")
        self.assertEqual(_extract_on_delete("on_delete=models.SET_NULL"), "SET_NULL")
        self.assertEqual(_extract_on_delete("on_delete=PROTECT"), "PROTECT")

    def test_set_callable_form_returns_SET(self) -> None:
        """The SET(default_value) callable form used to be silently dropped."""
        self.assertEqual(
            _extract_on_delete("to='User', on_delete=models.SET(get_default)"),
            "SET",
        )
        self.assertEqual(_extract_on_delete("on_delete=SET(0)"), "SET")

    def test_absent_on_delete_returns_none(self) -> None:
        self.assertIsNone(_extract_on_delete("null=True, blank=True"))


class ParserGuardsTest(unittest.TestCase):
    """Regression tests for parser guards added in ce3bd0e (round 1 audit)."""

    def test_read_balanced_args_no_open_paren_returns_empty(self) -> None:
        """A field-shaped line without ( must not raise ValueError."""
        from django_orm_lens.parser import _read_balanced_args
        self.assertEqual(_read_balanced_args(["    name = CharField"], 0), ("", 0))

    def test_detect_class_indent_clamps_at_32(self) -> None:
        """A crafted deep-indent input must not exceed the ReDoS clamp."""
        from django_orm_lens.parser import _detect_class_indent
        deep = " " * 200 + "x = 1"
        self.assertEqual(_detect_class_indent(["class Foo(Model):", deep], 0), 32)

    def test_detect_class_indent_expands_tabs_to_four(self) -> None:
        """A tab-indented body reports width 4, not raw byte length 1."""
        from django_orm_lens.parser import _detect_class_indent
        self.assertEqual(_detect_class_indent(["class Foo(Model):", "	x = 1"], 0), 4)


if __name__ == "__main__":
    unittest.main()
