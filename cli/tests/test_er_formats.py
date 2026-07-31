"""Tests for the DBML / D2 / PlantUML / Graphviz DOT ER-diagram emitters.

The community-standard export formats must draw the *same graph* the
Mermaid builder draws: identical relation resolution (including
``settings.AUTH_USER_MODEL``), identical in-workspace filtering, and a
faithful primary-key story (explicit ``primary_key=True`` wins, implicit
Django ``id`` is synthesized otherwise). Absolute machine paths must never
leak into shareable diagram text.
"""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from django_orm_lens.cli import _build_mermaid, main
from django_orm_lens.er_formats import build_d2, build_dbml, build_dot, build_plantuml
from django_orm_lens.parser import DEFAULT_EXCLUDES, scan_workspace

FIXTURES = Path(__file__).parent / "fixtures"
MINIAPP = FIXTURES / "miniapp"


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        exit_code = main(argv)
    return exit_code, out.getvalue(), err.getvalue()


class MiniappAllFormatsTest(unittest.TestCase):
    """Integration over the real miniapp fixture (orders + users apps)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = scan_workspace(str(MINIAPP), DEFAULT_EXCLUDES)

    def test_dbml_tables_refs_and_on_delete(self) -> None:
        dbml = build_dbml(self.index)
        self.assertIn("Table orders.Order {", dbml)
        self.assertIn("Table users.User {", dbml)
        # Implicit Django pk synthesized so refs point at a declared column.
        self.assertIn("id AutoField [pk]", dbml)
        # FK ref carries the on_delete policy as a DBML ref setting.
        self.assertIn("Ref: orders.Order.user > users.User.id [delete: cascade]", dbml)

    def test_dbml_never_leaks_absolute_paths(self) -> None:
        dbml = build_dbml(self.index)
        self.assertNotIn("C:/", dbml)
        self.assertNotIn("C:\\", dbml)
        self.assertIn("orders/models.py", dbml)

    def test_d2_sql_tables_and_edges(self) -> None:
        d2 = build_d2(self.index)
        self.assertIn("orders.Order: {", d2)
        self.assertIn("shape: sql_table", d2)
        self.assertIn("id: AutoField {constraint: primary_key}", d2)
        self.assertIn('orders.Order.user -> users.User.id: "ForeignKey · CASCADE"', d2)

    def test_plantuml_entities_and_crows_feet(self) -> None:
        puml = build_plantuml(self.index)
        self.assertTrue(puml.startswith("@startuml"))
        self.assertTrue(puml.rstrip().endswith("@enduml"))
        self.assertIn('entity "orders.Order" as orders_Order {', puml)
        self.assertIn("orders_Order }o--|| users_User : user / CASCADE", puml)

    def test_dot_clusters_tables_and_edges(self) -> None:
        dot = build_dot(self.index)
        self.assertTrue(dot.startswith("digraph django_orm_lens {"))
        self.assertIn('subgraph "cluster_orders" {', dot)
        self.assertIn('"orders.Order" [label=<<TABLE', dot)
        self.assertIn(
            '"orders.Order" -> "users.User" '
            '[label="user → id / ForeignKey / CASCADE", dir="both", '
            'arrowtail="crow", arrowhead="tee"];',
            dot,
        )

    def test_dot_never_leaks_absolute_paths(self) -> None:
        dot = build_dot(self.index)
        self.assertNotIn("C:/", dot)
        self.assertNotIn("C:\\", dot)
        self.assertNotIn(str(MINIAPP.resolve()), dot)

    def test_same_edge_set_as_mermaid(self) -> None:
        """Every format must draw the same number of relations."""
        _, mermaid_out, _ = _run(["er", "--path", str(MINIAPP)])
        mermaid_edges = [
            line
            for line in mermaid_out.splitlines()
            if "--" in line and ":" in line
        ]
        dbml_refs = [
            line
            for line in build_dbml(self.index).splitlines()
            if line.startswith("Ref: ")
        ]
        dot_edges = [
            line
            for line in build_dot(self.index).splitlines()
            if " -> " in line
        ]
        self.assertEqual(len(mermaid_edges), len(dbml_refs))
        self.assertEqual(len(mermaid_edges), len(dot_edges))
        self.assertGreater(len(dbml_refs), 0)


class SyntheticSchemaTest(unittest.TestCase):
    """Explicit pk, self-FK, M2M-through, and AUTH_USER_MODEL resolution."""

    def _index_for(self, models_py: str):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = Path(tmp.name) / "blog"
        app.mkdir()
        (app / "__init__.py").write_text("", encoding="utf-8")
        (app / "models.py").write_text(models_py, encoding="utf-8")
        return scan_workspace(tmp.name, DEFAULT_EXCLUDES)

    def test_explicit_primary_key_respected(self) -> None:
        idx = self._index_for(
            "from django.db import models\n"
            "class Token(models.Model):\n"
            "    jti = models.CharField(max_length=64, primary_key=True)\n"
            "    note = models.TextField()\n"
        )
        dbml = build_dbml(idx)
        self.assertIn("jti CharField [pk]", dbml)
        self.assertNotIn("id AutoField [pk]", dbml)
        puml = build_plantuml(idx)
        self.assertIn("* jti : CharField", puml)
        dot = build_dot(idx)
        self.assertIn("<B>jti</B></TD><TD>CharField · PK", dot)
        self.assertNotIn("<B>id</B></TD><TD>AutoField · PK", dot)

    def test_self_fk_and_m2m_through(self) -> None:
        idx = self._index_for(
            "from django.db import models\n"
            "class Category(models.Model):\n"
            "    parent = models.ForeignKey(\n"
            "        'self', on_delete=models.SET_NULL, null=True)\n"
            "class Post(models.Model):\n"
            "    tags = models.ManyToManyField(\n"
            "        'Category', through='Tagging')\n"
            "class Tagging(models.Model):\n"
            "    post = models.ForeignKey(Post, on_delete=models.CASCADE)\n"
            "    category = models.ForeignKey(\n"
            "        Category, on_delete=models.CASCADE)\n"
        )
        dbml = build_dbml(idx)
        self.assertIn(
            "Ref: blog.Category.parent > blog.Category.id [delete: set null]",
            dbml,
        )
        self.assertIn("Ref: blog.Post.tags <> blog.Category.id", dbml)
        d2 = build_d2(idx)
        self.assertIn("through Tagging", d2)

    def test_auth_user_model_resolves_like_mermaid(self) -> None:
        idx = self._index_for(
            "from django.conf import settings\n"
            "from django.db import models\n"
            "from django.contrib.auth.models import AbstractUser\n"
            "class Member(AbstractUser):\n"
            "    pass\n"
            "class Note(models.Model):\n"
            "    author = models.ForeignKey(\n"
            "        settings.AUTH_USER_MODEL, on_delete=models.CASCADE)\n"
        )
        dbml = build_dbml(idx)
        self.assertIn("Ref: blog.Note.author > blog.Member.id", dbml)

    def test_out_of_workspace_targets_skipped(self) -> None:
        idx = self._index_for(
            "from django.db import models\n"
            "class Vote(models.Model):\n"
            "    poll = models.ForeignKey(\n"
            "        'polls.Poll', on_delete=models.CASCADE)\n"
        )
        for text in (build_dbml(idx), build_d2(idx), build_plantuml(idx), build_dot(idx)):
            self.assertNotIn("polls.Poll", text)

    def test_taggable_manager_external_target_skipped(self) -> None:
        idx = self._index_for(
            "from django.db import models\n"
            "from taggit.managers import TaggableManager\n"
            "class Post(models.Model):\n"
            "    tags = TaggableManager()\n"
        )
        outputs = (
            _build_mermaid(idx),
            build_dbml(idx),
            build_d2(idx),
            build_plantuml(idx),
            build_dot(idx),
        )
        for text in outputs:
            self.assertNotIn("taggit.Tag", text)

    def test_fk_ref_targets_explicit_pk_column(self) -> None:
        """A ref must point at the column that exists on the target table —
        the declared PK, not a hardcoded ``id``. Also covers spaced
        ``primary_key = True`` (hand-written, non-black style)."""
        idx = self._index_for(
            "from django.db import models\n"
            "class Product(models.Model):\n"
            "    sku = models.CharField(max_length=64, primary_key = True)\n"
            "class Order(models.Model):\n"
            "    product = models.ForeignKey(\n"
            "        Product, on_delete=models.PROTECT)\n"
        )
        dbml = build_dbml(idx)
        # Spaced kwarg still detected → no fabricated id row in Product.
        self.assertIn("Table blog.Product {\n  sku CharField [pk]", dbml)
        self.assertIn(
            "Ref: blog.Order.product > blog.Product.sku [delete: restrict]",
            dbml,
        )
        d2 = build_d2(idx)
        self.assertIn("blog.Order.product -> blog.Product.sku", d2)
        self.assertNotIn("blog.Product.id", d2)
        dot = build_dot(idx)
        self.assertIn("product → sku / ForeignKey / PROTECT", dot)


class CliWiringTest(unittest.TestCase):
    def test_er_format_flags(self) -> None:
        for fmt, marker in (
            ("mermaid", "erDiagram"),
            ("dbml", "Table orders.Order {"),
            ("d2", "shape: sql_table"),
            ("plantuml", "@startuml"),
            ("dot", "digraph django_orm_lens"),
        ):
            code, out, _ = _run(["er", "--path", str(MINIAPP), "--format", fmt])
            self.assertEqual(code, 0, f"{fmt} exited {code}")
            self.assertIn(marker, out, f"{fmt} output missing {marker!r}")

    def test_er_output_file(self) -> None:
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "schema.dbml"
            code, _, err = _run(
                ["er", "--path", str(MINIAPP), "--format", "dbml", "-o", str(target)]
            )
            self.assertEqual(code, 0)
            self.assertIn("Wrote", err)
            self.assertIn("Table orders.Order {", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
