"""Regression tests for two field-detection gaps surfaced by targeted fuzz:

1. **Aliased models module.** ``from django.db import models as m`` followed
   by ``class X(m.Model): x = m.CharField(...)`` used to lose every field
   because ``FIELD_RE`` hardcoded the ``models\\.`` prefix and
   ``BARE_FIELD_RE`` had no prefix allowance at all.

2. **Third-party field packages.** Fields declared via a namespaced
   third-party import - ``x = jsonfield.JSONField(default=dict)``,
   ``x = timezonefield.TimeZoneField()`` - also fell through the same
   two-way gap.

Fixed by adding an optional single-identifier prefix on the RHS in
``BARE_FIELD_RE``. Safe against false positives because the type name
is still restricted to Django's known field whitelist
(``BARE_FIELD_TYPES``) - random ``foo.CharField(...)`` calls in
non-Django code won't leak in unless the trailing name is a real
Django field type.
"""

from __future__ import annotations

import unittest

from django_orm_lens.parser import parse_models_file


class AliasedModelsModuleTest(unittest.TestCase):
    def test_all_fields_captured_via_alias(self) -> None:
        src = (
            "from django.db import models as m\n\n"
            "class Order(m.Model):\n"
            "    status = m.CharField(max_length=20)\n"
            "    total = m.DecimalField(max_digits=10, decimal_places=2)\n"
            "    quantity = m.IntegerField(default=1)\n"
        )
        models = parse_models_file("shop/models.py", src)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].name, "Order")
        self.assertEqual(
            [f.name for f in models[0].fields],
            ["status", "total", "quantity"],
        )
        self.assertEqual(models[0].fields[0].type, "CharField")

    def test_mixed_alias_and_plain_and_bare(self) -> None:
        # One model, three import styles interleaved - every field must
        # be captured regardless of prefix.
        src = (
            "from django.db import models as m\n"
            "from django.db.models import IntegerField\n\n"
            "class Row(m.Model):\n"
            "    aliased = m.CharField(max_length=10)\n"
            "    plain = models.TextField()\n"
            "    bare = IntegerField(default=0)\n"
        )
        models = parse_models_file("t/models.py", src)
        self.assertEqual(
            [f.name for f in models[0].fields],
            ["aliased", "plain", "bare"],
        )


class ThirdPartyFieldPackageTest(unittest.TestCase):
    def test_jsonfield_style_package(self) -> None:
        # `django-jsonfield`-style: `x = jsonfield.JSONField(default=dict)`.
        # JSONField is in the standard whitelist, so this must match even
        # under a non-`models.` prefix.
        src = (
            "import jsonfield\n\n"
            "class Config(models.Model):\n"
            "    data = jsonfield.JSONField(default=dict)\n"
        )
        models = parse_models_file("t/models.py", src)
        self.assertEqual([f.name for f in models[0].fields], ["data"])
        self.assertEqual(models[0].fields[0].type, "JSONField")

    def test_plain_bare_import_still_works(self) -> None:
        # Backward-compat: the pre-fix bare form (no prefix at all) must
        # still match - the prefix is truly optional, not required.
        src = (
            "from django.db.models import CharField, IntegerField\n\n"
            "class R(models.Model):\n"
            "    name = CharField(max_length=50)\n"
            "    count = IntegerField(default=0)\n"
        )
        models = parse_models_file("t/models.py", src)
        self.assertEqual(
            [f.name for f in models[0].fields], ["name", "count"]
        )


class TaggableManagerTest(unittest.TestCase):
    def test_default_relation_metadata(self) -> None:
        src = (
            "from django.db import models\n"
            "from taggit.managers import TaggableManager\n\n"
            "class Post(models.Model):\n"
            "    title = models.CharField(max_length=200)\n"
            "    tags = TaggableManager()\n"
        )
        models = parse_models_file("blog/models.py", src)
        tags = models[0].fields[1]
        self.assertEqual(tags.type, "TaggableManager")
        self.assertTrue(tags.is_relation)
        self.assertEqual(tags.relation_kind, "ManyToManyField")
        self.assertEqual(tags.related_model, "taggit.Tag")
        self.assertEqual(tags.through_model, "taggit.TaggedItem")

    def test_explicit_through_overrides_default(self) -> None:
        src = (
            "from django.db import models\n"
            "from taggit.managers import TaggableManager\n\n"
            "class Post(models.Model):\n"
            "    tags = TaggableManager(through=CustomTaggedItem)\n"
        )
        models = parse_models_file("blog/models.py", src)
        tags = models[0].fields[0]
        self.assertEqual(tags.related_model, "taggit.Tag")
        self.assertEqual(tags.through_model, "CustomTaggedItem")


if __name__ == "__main__":
    unittest.main()
