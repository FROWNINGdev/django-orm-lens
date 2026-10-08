"""Regression test for issue #135 — a model base class outside ``models.py``.

``class Person(MyCustomModel)`` with ``MyCustomModel`` in ``core/base.py``
vanished from the scan: only ``models.py``-style files are read, so the base
had no definition to resolve against. The scanner now follows the subclass's
imports to the base's file.

Fixture: ``test/fixtures/base_outside_models/`` — shared with
``test/base-outside-models.test.js`` so the CLI and the extension are held to
the same answer (see ``test_parity.py``).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from django_orm_lens.parser import scan_workspace

FIXTURE = (
    Path(__file__).resolve().parents[2] / "test" / "fixtures" / "base_outside_models"
)


class BaseOutsideModelsTest(unittest.TestCase):
    def setUp(self) -> None:
        index = scan_workspace(str(FIXTURE))
        self.models = {m.name: m for a in index.apps for m in a.models}

    def inherited(self, name: str) -> list[tuple[str, str | None]]:
        return [(f.name, f.inherited_from) for f in self.models[name].inherited_fields]

    def test_exactly_the_concrete_models(self) -> None:
        self.assertEqual(
            sorted(self.models), ["Archive", "City", "Located", "Note", "Person"]
        )

    def test_base_imported_from_plain_module(self) -> None:
        self.assertEqual(self.inherited("Person"), [("created", "MyCustomModel")])

    def test_base_behind_a_reexport_two_hops_away(self) -> None:
        self.assertEqual(
            self.inherited("Archive"),
            [("created", "MyCustomModel"), ("deleted", "SoftDeletable")],
        )

    def test_base_reached_through_a_module_alias(self) -> None:
        self.assertEqual(self.inherited("Note"), [("created", "MyCustomModel")])

    def test_concrete_base_via_relative_import_is_its_own_model(self) -> None:
        self.assertEqual(
            [f.name for f in self.models["Located"].fields], ["lat", "lng"]
        )
        self.assertEqual(self.models["Located"].app_name, "places")
        # Multi-table inheritance: City gets a pointer, not Located's columns.
        self.assertEqual(self.inherited("City"), [])

    def test_plain_class_in_base_module_does_not_make_a_model(self) -> None:
        self.assertNotIn("Plain", self.models)
        self.assertNotIn("NotAModel", self.models)


if __name__ == "__main__":
    unittest.main()
