"""Regression test for issue #25 (jsabater):

Fields annotated with PEP-526 type hints — the modern Django Ninja / typed
Django style — used to disappear from the parsed model because the field
regex expected ``name = models.X(`` with no annotation between the name
and ``=``. When user code writes:

    jti: CharField[str] = models.CharField(max_length=32, unique=True)

the pattern failed silently: no field parsed, sidebar tree empty, ER
diagram empty entity. Fixed by allowing an optional ``: <type>`` group
between the field name and the ``=`` in both ``FIELD_RE`` and
``BARE_FIELD_RE`` (and ``META_ITEM_RE`` for consistency).
"""

from __future__ import annotations

import unittest

from django_orm_lens.parser import parse_models_file

SAMPLE = '''
from django.db import models
from django.db.models import CharField, IntegerField


class RevokedToken(models.Model):
    """A revoked JWT, keyed by its jti claim (the token denylist)."""

    # Exact snippet from the bug report — models.-prefixed with generic type hint.
    jti: CharField[str] = models.CharField(max_length=32, unique=True)

    # Bare import form + generic type hint.
    revoked_count: IntegerField[int] = IntegerField(default=0)

    # Simple annotation (no generic).
    label: str = models.CharField(max_length=64)

    # Backwards-compatible untyped form still works.
    note = models.TextField(blank=True)
'''


class Pep526TypeAnnotationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.models = parse_models_file("auth/models.py", SAMPLE)
        self.assertEqual(len(self.models), 1, "RevokedToken class parsed")
        self.token = self.models[0]

    def test_all_four_fields_present(self) -> None:
        names = [f.name for f in self.token.fields]
        # The bug: type-hinted fields vanished, only untyped `note` survived.
        self.assertEqual(names, ["jti", "revoked_count", "label", "note"])

    def test_type_hinted_field_type_extracted(self) -> None:
        # The field type comes from `models.CharField(...)`, not the annotation.
        jti = next(f for f in self.token.fields if f.name == "jti")
        self.assertEqual(jti.type, "CharField")

    def test_bare_import_form_with_annotation(self) -> None:
        rc = next(f for f in self.token.fields if f.name == "revoked_count")
        self.assertEqual(rc.type, "IntegerField")

    def test_simple_annotation(self) -> None:
        label = next(f for f in self.token.fields if f.name == "label")
        self.assertEqual(label.type, "CharField")

    def test_untyped_form_still_works(self) -> None:
        note = next(f for f in self.token.fields if f.name == "note")
        self.assertEqual(note.type, "TextField")


META_SAMPLE = '''
from django.db import models


class Item(models.Model):
    # Type-annotated field followed by Meta with type-annotated attribute.
    title: str = models.CharField(max_length=100)

    class Meta:
        ordering: list[str] = ["title"]
'''


class Pep526MetaAnnotationTest(unittest.TestCase):
    def test_meta_item_with_annotation(self) -> None:
        models = parse_models_file("shop/models.py", META_SAMPLE)
        item = models[0]
        # The field itself must still be visible.
        self.assertEqual([f.name for f in item.fields], ["title"])
        # And the Meta annotation must not confuse the Meta reader.
        self.assertEqual(item.meta.get("ordering"), '["title"]')


if __name__ == "__main__":
    unittest.main()
