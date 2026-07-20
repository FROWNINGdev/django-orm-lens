"""Regression: leading BOM (U+FEFF) must be stripped before parsing.

Windows editors - Notepad, older Sublime, VS Code with certain UTF-8
encoding settings - save files with a byte-order mark. Without this
fix the first line becomes "﻿class Foo..." and CLASS_RE fails
to match. Result: zero models parsed for the whole file, silent.
"""

from __future__ import annotations

import unittest

from django_orm_lens.parser import parse_models_file

BOM = "﻿"


class BomPrefixTest(unittest.TestCase):
    def test_bom_prefixed_file_parses(self) -> None:
        src = (
            BOM
            + "class Article(models.Model):\n"
            "    title = models.CharField(max_length=100)\n"
            "    body = models.TextField()\n"
        )
        models = parse_models_file("blog/models.py", src)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].name, "Article")
        self.assertEqual(
            [f.name for f in models[0].fields], ["title", "body"]
        )

    def test_no_bom_still_works(self) -> None:
        src = "class A(models.Model):\n    x = models.CharField(max_length=5)\n"
        models = parse_models_file("t/models.py", src)
        self.assertEqual([f.name for f in models[0].fields], ["x"])


if __name__ == "__main__":
    unittest.main()
