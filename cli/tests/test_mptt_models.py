"""Regression tests for issue #49 — django-mptt models were skipped entirely.

Two independent gaps, both of which had to be closed for a single
``class Category(MPTTModel)`` to become visible:

1. **The class was never recognised as a model.** ``_looks_like_model``
   decides from base-class names, and ``MPTTModel`` matched none of them —
   not ``models.Model``, not ``Abstract[A-Z]``, not ``*Mixin``. The class was
   dropped before any field was read, so it was absent from the sidebar, the
   ER diagram, and every analyzer.

2. **Its relation fields would have been dropped anyway.** ``TreeForeignKey``
   and friends are thin subclasses of Django's relation fields, but the parser
   matches type names against a literal whitelist. Fixing only (1) would have
   produced a model with a ``name`` field and no edges — arguably worse than
   not showing it at all, because it looks complete.

The fix is deliberately additive and import-free: no ``django-mptt`` dependency,
so the parser keeps working against a project whose venv is broken.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from django_orm_lens.parser import parse_models_file, scan_workspace

FIXTURE = Path(__file__).parent / "fixtures" / "mptt"
FIXTURE_MODELS = FIXTURE / "catalog" / "models.py"


class MPTTModelDetectionTest(unittest.TestCase):
    def test_mptt_base_is_recognised_as_a_model(self) -> None:
        src = (
            "from mptt.models import MPTTModel\n"
            "from django.db import models\n\n"
            "class Category(MPTTModel):\n"
            "    name = models.CharField(max_length=50)\n"
        )
        models_ = parse_models_file("catalog/models.py", src)
        self.assertEqual(len(models_), 1)
        self.assertEqual(models_[0].name, "Category")
        self.assertEqual([f.name for f in models_[0].fields], ["name"])

    def test_dotted_mptt_base_is_recognised(self) -> None:
        # `class Category(mptt.models.MPTTModel)` — detection keys off the
        # trailing segment, same as it does for `models.Model`.
        src = (
            "import mptt.models\n\n"
            "class Category(mptt.models.MPTTModel):\n"
            "    name = models.CharField(max_length=50)\n"
        )
        models_ = parse_models_file("catalog/models.py", src)
        self.assertEqual(len(models_), 1)


class TreeFieldRelationTest(unittest.TestCase):
    def test_tree_foreign_key_self_edge(self) -> None:
        """The acceptance case from the issue: a self-referential TreeForeignKey."""
        src = (
            "from mptt.models import MPTTModel\n"
            "from mptt.fields import TreeForeignKey\n"
            "from django.db import models\n\n"
            "class Category(MPTTModel):\n"
            "    name = models.CharField(max_length=50)\n"
            "    parent = TreeForeignKey('self', on_delete=models.CASCADE,\n"
            "                            null=True, related_name='children')\n"
        )
        parent = parse_models_file("catalog/models.py", src)[0].fields[1]
        self.assertEqual(parent.type, "TreeForeignKey")
        self.assertTrue(parent.is_relation)
        # Reported as the Django field it subclasses, so every downstream
        # consumer (ER renderer, blast radius, MCP) needs no mptt knowledge.
        self.assertEqual(parent.relation_kind, "ForeignKey")
        self.assertEqual(parent.related_model, "self")
        self.assertEqual(parent.on_delete, "CASCADE")
        self.assertEqual(parent.related_name, "children")

    def test_tree_one_to_one_and_many_to_many(self) -> None:
        src = (
            "from mptt.models import MPTTModel\n"
            "from mptt.fields import TreeManyToManyField, TreeOneToOneField\n\n"
            "class Genre(MPTTModel):\n"
            "    canonical = TreeOneToOneField('Category', on_delete=models.PROTECT)\n"
            "    tags = TreeManyToManyField('Category', related_name='genres')\n"
        )
        fields = parse_models_file("catalog/models.py", src)[0].fields
        self.assertEqual(
            [(f.type, f.relation_kind) for f in fields],
            [
                ("TreeOneToOneField", "OneToOneField"),
                ("TreeManyToManyField", "ManyToManyField"),
            ],
        )
        self.assertEqual(fields[0].on_delete, "PROTECT")
        self.assertEqual(fields[1].related_name, "genres")

    def test_plain_django_relations_are_untouched(self) -> None:
        # Guard against the alias map swallowing the ordinary case.
        src = (
            "from django.db import models\n\n"
            "class Order(models.Model):\n"
            "    buyer = models.ForeignKey('User', on_delete=models.CASCADE)\n"
        )
        buyer = parse_models_file("shop/models.py", src)[0].fields[0]
        self.assertEqual(buyer.type, "ForeignKey")
        self.assertEqual(buyer.relation_kind, "ForeignKey")


class MPTTFixtureScanTest(unittest.TestCase):
    """End-to-end over the vendored fixture, not hand-built source strings."""

    def test_fixture_parses_both_models_with_every_field(self) -> None:
        models_ = parse_models_file(
            str(FIXTURE_MODELS), FIXTURE_MODELS.read_text(encoding="utf-8")
        )
        by_name = {m.name: m for m in models_}
        self.assertEqual(sorted(by_name), ["Category", "Genre"])
        self.assertEqual(
            [f.name for f in by_name["Category"].fields], ["name", "parent"]
        )
        self.assertEqual(
            [f.name for f in by_name["Genre"].fields],
            ["title", "parent", "canonical", "tags"],
        )

    def test_mptt_meta_is_not_read_as_class_meta(self) -> None:
        models_ = parse_models_file(
            str(FIXTURE_MODELS), FIXTURE_MODELS.read_text(encoding="utf-8")
        )
        category = next(m for m in models_ if m.name == "Category")
        # `class Meta` contributes verbose_name_plural; `class MPTTMeta` must
        # contribute nothing, or its attributes would leak into model Meta.
        self.assertEqual(category.meta.get("verbose_name_plural"), "'categories'")
        self.assertNotIn("order_insertion_by", category.meta)

    def test_scan_workspace_finds_the_app(self) -> None:
        result = scan_workspace(str(FIXTURE))
        found = {m.name for app in result.apps for m in app.models}
        self.assertEqual(found, {"Category", "Genre"})


if __name__ == "__main__":
    unittest.main()
