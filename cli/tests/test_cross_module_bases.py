"""Regression test for issue #20 — bases resolved only within a single file.

Fixture: ``tests/fixtures/cross_module/`` — a ``common`` app defining an
abstract ``TimeStampedModel`` and an ``app`` app whose ``Article`` model
inherits it. Before the fix, ``scan_workspace`` resolved transitive model
inheritance per parsed file, so a base class defined in a *different*
scanned file never entered ``is_model_name`` and any model inheriting it
was silently dropped — ``Article`` never appeared in the output.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from django_orm_lens.parser import scan_workspace

FIXTURE = Path(__file__).parent / "fixtures" / "cross_module"


class CrossModuleBaseResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.index = scan_workspace(str(FIXTURE))
        self.all_models = [m.name for a in self.index.apps for m in a.models]

    def test_model_with_cross_module_base_is_present(self) -> None:
        # BUG #20 — Article(TimeStampedModel) where TimeStampedModel is
        # defined in a different file (common/models.py); must not be
        # silently dropped.
        self.assertIn("Article", self.all_models)

    def test_cross_module_abstract_base_itself_dropped(self) -> None:
        self.assertNotIn("TimeStampedModel", self.all_models)


if __name__ == "__main__":
    unittest.main()
