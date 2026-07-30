"""Models declared inside a module-level block, as django-oscar does it.

Found by running the CLI over a real django-oscar checkout: 21 of its 22 app
``models.py`` files parsed to **nothing**, because oscar wraps every concrete
model in the swappable-model idiom::

    if not is_model_registered("catalogue", "ProductClass"):

        class ProductClass(AbstractProductClass):
            pass

The class is indented, and the parser anchored on ``^class``. Catalogue,
order, offer, partner, payment, voucher and the rest of the framework were
invisible; the only models reported for the checkout came from its ``tests/``
directory, which is worse than reporting none.

The guard tests matter as much as the fix: widening the match must not start
pulling in ``class Meta`` or classes defined inside functions.
"""

from __future__ import annotations

import unittest

from django_orm_lens.parser import parse_models_file

OSCAR_SHAPE = '''
from oscar.apps.catalogue.abstract_models import *
from oscar.core.loading import is_model_registered

__all__ = ["ProductAttributesContainer"]


if not is_model_registered("catalogue", "ProductClass"):

    class ProductClass(AbstractProductClass):
        pass

    __all__.append("ProductClass")


if not is_model_registered("catalogue", "Category"):

    class Category(AbstractCategory):
        slug = models.SlugField(max_length=255)
        depth = models.PositiveIntegerField()

    __all__.append("Category")
'''


class ConditionalModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.models = parse_models_file("catalogue/models.py", OSCAR_SHAPE)
        self.names = [m.name for m in self.models]

    def test_every_conditional_model_is_found(self) -> None:
        self.assertEqual(self.names, ["ProductClass", "Category"])

    def test_fields_of_an_indented_class_are_parsed(self) -> None:
        category = next(m for m in self.models if m.name == "Category")
        self.assertEqual([f.name for f in category.fields], ["slug", "depth"])

    def test_the_body_stops_at_the_dedent(self) -> None:
        """``__all__.append(...)`` after the class must not be read as a field.

        The body scan used to end only at the next column-0 ``class``; for an
        indented class that would run past its own block.
        """
        product_class = next(m for m in self.models if m.name == "ProductClass")
        self.assertEqual(product_class.fields, [])
        self.assertNotIn("__all__", product_class.meta)


class StillExcludedTest(unittest.TestCase):
    """What the widened match must keep out."""

    def test_meta_is_not_a_model(self) -> None:
        src = (
            "from django.db import models\n"
            "\n"
            "class Post(models.Model):\n"
            "    title = models.CharField(max_length=10)\n"
            "\n"
            "    class Meta:\n"
            "        ordering = ['title']\n"
        )
        self.assertEqual(
            [m.name for m in parse_models_file("blog/models.py", src)], ["Post"]
        )

    def test_a_class_defined_inside_a_function_is_not_a_model(self) -> None:
        src = (
            "from django.db import models\n"
            "\n"
            "def make_model():\n"
            "    class Local(models.Model):\n"
            "        x = models.IntegerField()\n"
            "    return Local\n"
        )
        self.assertEqual(parse_models_file("blog/models.py", src), [])

    def test_a_class_nested_in_another_class_is_not_a_model(self) -> None:
        src = (
            "from django.db import models\n"
            "\n"
            "class Outer(models.Model):\n"
            "    name = models.CharField(max_length=5)\n"
            "\n"
            "    class Inner(models.Model):\n"
            "        y = models.IntegerField()\n"
        )
        self.assertEqual(
            [m.name for m in parse_models_file("a/models.py", src)], ["Outer"]
        )

    def test_a_model_inside_a_method_stays_out(self) -> None:
        """A def nested two levels deep — rejected at the first def outwards."""
        src = (
            "from django.db import models\n"
            "\n"
            "class Service:\n"
            "    def build(self):\n"
            "        class Tmp(models.Model):\n"
            "            z = models.IntegerField()\n"
            "        return Tmp\n"
        )
        self.assertEqual(parse_models_file("a/models.py", src), [])


class OtherBlockStatementsTest(unittest.TestCase):
    def test_try_except_import_guard(self) -> None:
        """The other common conditional-definition shape."""
        src = (
            "from django.db import models\n"
            "\n"
            "try:\n"
            "    from extras import Base\n"
            "\n"
            "    class Widget(Base, models.Model):\n"
            "        sku = models.CharField(max_length=12)\n"
            "except ImportError:\n"
            "    pass\n"
        )
        got = parse_models_file("shop/models.py", src)
        self.assertEqual([m.name for m in got], ["Widget"])
        self.assertEqual([f.name for f in got[0].fields], ["sku"])

    def test_two_levels_of_block_nesting(self) -> None:
        src = (
            "from django.db import models\n"
            "\n"
            "if FEATURE:\n"
            "    if OTHER:\n"
            "        class Deep(models.Model):\n"
            "            a = models.IntegerField()\n"
        )
        self.assertEqual(
            [m.name for m in parse_models_file("a/models.py", src)], ["Deep"]
        )


if __name__ == "__main__":
    unittest.main()
