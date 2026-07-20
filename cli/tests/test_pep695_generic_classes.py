"""Regression: PEP-695 generic classes (Python 3.12+) must parse.

Before this fix, ``class Container[T](models.Model):`` failed the
``CLASS_RE`` pattern entirely — the parser walked past it and reported
zero models for the whole file. Users on Python 3.12+ writing modern
typed Django models saw an empty sidebar/ER diagram with no error.

The fix adds an optional ``(?:\\s*\\[[^\\]]*\\])?`` group between the
class name and the opening ``(`` in both ``CLASS_RE`` and
``CLASS_START_RE``. Covers single/multi-param, bounded, variadic, and
paramspec generics — the four common PEP-695 shapes.
"""

from __future__ import annotations

import unittest

from django_orm_lens.parser import parse_models_file


class Pep695GenericClassTest(unittest.TestCase):
    def test_single_param_generic(self) -> None:
        src = (
            "class Container[T](models.Model):\n"
            "    label = models.CharField(max_length=50)\n"
        )
        models = parse_models_file("t.py", src)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].name, "Container")
        self.assertEqual([f.name for f in models[0].fields], ["label"])

    def test_multi_param_generic(self) -> None:
        src = (
            "class Pair[K, V](models.Model):\n"
            "    key = models.CharField(max_length=10)\n"
            "    val = models.CharField(max_length=10)\n"
        )
        models = parse_models_file("t.py", src)
        self.assertEqual(len(models), 1)
        self.assertEqual([f.name for f in models[0].fields], ["key", "val"])

    def test_bounded_generic(self) -> None:
        src = (
            "class Bounded[T: str](models.Model):\n"
            "    x = models.CharField(max_length=5)\n"
        )
        models = parse_models_file("t.py", src)
        self.assertEqual(len(models), 1)

    def test_variadic_and_paramspec(self) -> None:
        src = (
            "class Variadic[*Ts, **P](models.Model):\n"
            "    x = models.CharField(max_length=5)\n"
        )
        models = parse_models_file("t.py", src)
        self.assertEqual(len(models), 1)

    def test_non_generic_still_works(self) -> None:
        # Backward-compat guard — the ``[T]`` group is optional, plain
        # class headers must still parse identically.
        src = (
            "class Plain(models.Model):\n"
            "    x = models.CharField(max_length=5)\n"
        )
        models = parse_models_file("t.py", src)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].name, "Plain")


if __name__ == "__main__":
    unittest.main()
