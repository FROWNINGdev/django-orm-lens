"""Regression tests for scan_workspace against different workspace layouts.

Two shapes matter for the "user opens a Django folder in the editor" flow:

* **App-as-root** — the user opens the Django app folder itself (``hello/``
  containing ``models.py``, ``admin.py``, ``migrations/``, ...) as the
  workspace root. This is the common single-app repo layout that hit the
  v0.3.7 regression: extension came up with "No Django models found".
* **Project-as-root** — the user opens the parent Django project directory,
  with one or more app folders one level down.

Both must return the same three models. If the walker ever regresses to
skipping depth-0 ``models.py``, the ``AppAsRoot`` test fails immediately.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from orm_synapse.parser import scan_workspace

MODELS_SOURCE = """from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=100)


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
    tags = models.ManyToManyField('Tag')


class Tag(models.Model):
    label = models.CharField(max_length=50)
"""


def _write_hello_app(app_dir: Path) -> None:
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "models.py").write_text(MODELS_SOURCE, encoding="utf-8")
    for name in ("__init__.py", "admin.py", "apps.py", "views.py", "urls.py", "tests.py"):
        (app_dir / name).write_text("", encoding="utf-8")
    (app_dir / "migrations").mkdir(exist_ok=True)
    (app_dir / "migrations" / "__init__.py").write_text("", encoding="utf-8")


class ScanAppAsRootTest(unittest.TestCase):
    """Workspace root IS the Django app folder — models.py at depth 0."""

    def test_finds_three_models_when_models_py_is_at_root(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "hello"
            _write_hello_app(app)
            idx = scan_workspace(str(app))
            self.assertEqual(len(idx.apps), 1)
            app_out = idx.apps[0]
            self.assertEqual(app_out.name, "hello")
            self.assertEqual(
                sorted(m.name for m in app_out.models),
                ["Author", "Book", "Tag"],
            )

    def test_migrations_folder_at_root_is_excluded(self) -> None:
        """`**/migrations/**` default exclude must not swallow root models.py."""
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "hello"
            _write_hello_app(app)
            # Add a bogus migration models.py — must NOT show up.
            (app / "migrations" / "0001_initial.py").write_text(
                "class Migration:\n    pass\n", encoding="utf-8"
            )
            idx = scan_workspace(str(app))
            self.assertEqual(len(idx.apps), 1)
            self.assertEqual(len(idx.apps[0].models), 3)


class ScanNestedModelsPackageTest(unittest.TestCase):
    """Models live several directories under ``app/models/``, not in ``models.py``."""

    def test_nested_modules_belong_to_the_app_that_owns_models(self) -> None:
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            app = project / "src" / "ai_approval_engine"
            flow = app / "models" / "builders" / "approval_flow.py"
            abstract = app / "models" / "requests" / "abstracts" / "request.py"
            offer = app / "models" / "requests" / "components" / "offer.py"
            helper = app / "models" / "builders" / "utils.py"
            for path in (flow, abstract, offer, helper):
                path.parent.mkdir(parents=True, exist_ok=True)
            (app / "models" / "__init__.py").write_text(
                "from ai_approval_engine.models.builders.approval_flow import *\n",
                encoding="utf-8",
            )
            (app / "views" / "flow.py").parent.mkdir(parents=True, exist_ok=True)
            (app / "views" / "flow.py").write_text(
                "from django.db import models\n\nclass NotAModel(models.Model):\n    x = models.IntegerField()\n",
                encoding="utf-8",
            )
            flow.write_text(
                "from django.db import models\n\n"
                "class ApprovalFlow(models.Model):\n"
                "    name = models.CharField(max_length=255)\n",
                encoding="utf-8",
            )
            abstract.write_text(
                "from django.db import models\n\n"
                "class ApprovalRequest(models.Model):\n"
                "    company_id = models.IntegerField()\n\n"
                "    class Meta:\n"
                "        abstract = True\n",
                encoding="utf-8",
            )
            offer.write_text(
                "from django.db import models\n\n"
                "class OfferRequest(ApprovalRequest):\n"
                "    note = models.CharField(max_length=10)\n",
                encoding="utf-8",
            )
            helper.write_text(
                "class FlowHelper:\n    pass\n",
                encoding="utf-8",
            )

            idx = scan_workspace(str(project))

            self.assertEqual([a.name for a in idx.apps], ["ai_approval_engine"])
            models = {m.name: m for m in idx.apps[0].models}
            self.assertEqual(sorted(models), ["ApprovalFlow", "OfferRequest"])
            self.assertEqual(
                [f.name for f in models["OfferRequest"].all_fields()],
                ["company_id", "note"],
            )
            self.assertTrue(str(idx.apps[0].path).endswith("ai_approval_engine"))

    def test_nested_package_with_the_app_folder_as_root(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "ai_approval_engine"
            flow = app / "models" / "builders" / "approval_flow.py"
            flow.parent.mkdir(parents=True)
            flow.write_text(
                "from django.db import models\n\n"
                "class ApprovalFlow(models.Model):\n"
                "    name = models.CharField(max_length=255)\n",
                encoding="utf-8",
            )
            idx = scan_workspace(str(app))
            self.assertEqual(len(idx.apps), 1)
            self.assertEqual(idx.apps[0].name, "ai_approval_engine")
            self.assertEqual([m.name for m in idx.apps[0].models], ["ApprovalFlow"])


class ScanProjectAsRootTest(unittest.TestCase):
    """Workspace root is the Django project — app folders one level down."""

    def test_finds_three_models_when_app_is_one_level_down(self) -> None:
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            _write_hello_app(project / "hello")
            idx = scan_workspace(str(project))
            self.assertEqual(len(idx.apps), 1)
            self.assertEqual(idx.apps[0].name, "hello")
            self.assertEqual(len(idx.apps[0].models), 3)


if __name__ == "__main__":
    unittest.main()
