"""Regression: tab-indented model bodies must parse.

Editors that default to tabs (or projects that use PEP-8 exceptions with
tabs) produced empty models - every field silently dropped. Root cause:
``FIELD_RE`` uses ``\\s{indent}`` as its column prefix and
``_detect_class_indent`` expands tabs to width 4, but a single ``\\t``
character is only one match for ``\\s``, not four. Fixed by pre-expanding
tabs to spaces in the line buffer before regex matching.
"""

from __future__ import annotations

import unittest

from django_orm_lens.parser import parse_models_file


class TabIndentationTest(unittest.TestCase):
    def test_pure_tab_indented_body(self) -> None:
        src = (
            "class Post(models.Model):\n"
            "\ttitle = models.CharField(max_length=100)\n"
            "\tauthor = models.CharField(max_length=100)\n"
            "\tbody = models.TextField()\n"
        )
        models = parse_models_file("blog/models.py", src)
        self.assertEqual(len(models), 1)
        self.assertEqual(
            [f.name for f in models[0].fields],
            ["title", "author", "body"],
        )

    def test_mixed_tab_then_space(self) -> None:
        # Editors that mid-migrate to tabs sometimes end up with a tab
        # followed by a space; that used to fail equally silently.
        src = (
            "class M(models.Model):\n"
            "\t x = models.CharField(max_length=5)\n"
        )
        models = parse_models_file("t/models.py", src)
        self.assertEqual([f.name for f in models[0].fields], ["x"])

    def test_space_indented_still_works(self) -> None:
        # Backward-compat guard.
        src = (
            "class M(models.Model):\n"
            "    x = models.CharField(max_length=5)\n"
        )
        models = parse_models_file("t/models.py", src)
        self.assertEqual([f.name for f in models[0].fields], ["x"])


if __name__ == "__main__":
    unittest.main()
