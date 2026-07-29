"""Regression tests for #58 and #60, both reported by @sevdog.

* #58 — ``drift`` treated fields declared on an abstract base as missing from
  the child that inherits them, so every django-guardian permission model
  reported four columns as "migrated but no longer declared".
* #60 — ``suggest-index`` proposed indexes Django had already created: the
  primary key (under either the ``pk`` alias or its real name), ``db_index``,
  ``unique``, foreign keys, ``unique_together`` and ``UniqueConstraint``.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from django_orm_lens.drift import detect_drift
from django_orm_lens.parser import parse_models_file, scan_workspace
from django_orm_lens.query_analyzer import suggest_indexes

# Shaped after django-guardian: a two-level abstract chain whose fields land
# on each concrete permission model's own table.
GUARDIAN_LIKE = '''
from django.db import models


class BaseObjectPermission(models.Model):
    permission = models.ForeignKey("auth.Permission", on_delete=models.CASCADE)

    class Meta:
        abstract = True


class BaseGenericObjectPermission(BaseObjectPermission):
    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.CASCADE)
    object_pk = models.CharField(max_length=255)

    class Meta:
        abstract = True


class UserObjectPermissionBase(BaseGenericObjectPermission):
    user = models.ForeignKey("auth.User", on_delete=models.CASCADE)

    class Meta:
        abstract = True


class UserObjectPermission(UserObjectPermissionBase):
    class Meta:
        unique_together = ["user", "permission", "object_pk"]
'''


class AbstractFieldInheritanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.models = parse_models_file("guardian/models.py", GUARDIAN_LIKE)
        self.concrete = next(
            m for m in self.models if m.name == "UserObjectPermission"
        )

    def test_only_the_concrete_model_survives(self) -> None:
        self.assertEqual([m.name for m in self.models], ["UserObjectPermission"])

    def test_declares_nothing_of_its_own(self) -> None:
        # The whole point of the bug: its class body is empty but its table
        # is not.
        self.assertEqual(self.concrete.fields, [])

    def test_inherits_the_whole_abstract_chain(self) -> None:
        self.assertEqual(
            [f.name for f in self.concrete.inherited_fields],
            ["permission", "content_type", "object_pk", "user"],
        )

    def test_all_fields_is_parent_first(self) -> None:
        self.assertEqual(
            [f.name for f in self.concrete.all_fields()],
            ["permission", "content_type", "object_pk", "user"],
        )

    def test_records_which_base_each_field_came_from(self) -> None:
        origins = {f.name: f.inherited_from for f in self.concrete.inherited_fields}
        self.assertEqual(origins["permission"], "BaseObjectPermission")
        self.assertEqual(origins["content_type"], "BaseGenericObjectPermission")
        self.assertEqual(origins["user"], "UserObjectPermissionBase")

    def test_relation_metadata_survives_the_copy(self) -> None:
        user = next(
            f for f in self.concrete.inherited_fields if f.name == "user"
        )
        self.assertTrue(user.is_relation)
        self.assertEqual(user.relation_kind, "ForeignKey")


OVERRIDE_SOURCE = '''
from django.db import models


class Stamped(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=10)

    class Meta:
        abstract = True


class Doc(Stamped):
    note = models.TextField()
'''


class OverrideAndConcreteInheritanceTest(unittest.TestCase):
    def test_child_declaration_shadows_the_inherited_one(self) -> None:
        models_ = parse_models_file("docs/models.py", OVERRIDE_SOURCE)
        doc = next(m for m in models_ if m.name == "Doc")
        self.assertEqual([f.name for f in doc.inherited_fields], ["created"])
        # ``note`` is declared by the child, so it must appear once, as the
        # child's own TextField rather than the base's CharField.
        notes = [f for f in doc.all_fields() if f.name == "note"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].type, "TextField")

    def test_concrete_parent_does_not_donate_fields(self) -> None:
        """Multi-table inheritance keeps the parent's columns on its own table.

        Copying them onto the child would invent columns no migration creates
        — the exact false positive #58 is about, in the other direction.
        """
        source = (
            "from django.db import models\n"
            "\n"
            "class Place(models.Model):\n"
            "    address = models.CharField(max_length=80)\n"
            "\n"
            "class Restaurant(Place):\n"
            "    serves_pizza = models.BooleanField(default=False)\n"
        )
        models_ = parse_models_file("food/models.py", source)
        restaurant = next(m for m in models_ if m.name == "Restaurant")
        self.assertEqual(restaurant.inherited_fields, [])


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class DriftWithAbstractBasesTest(unittest.TestCase):
    """#58 end to end: migrations that create inherited columns are not drift."""

    def _workspace(self, root: Path) -> None:
        _write(root / "guardian" / "models.py", GUARDIAN_LIKE)
        _write(root / "guardian" / "migrations" / "__init__.py", "")
        _write(
            root / "guardian" / "migrations" / "0001_initial.py",
            "from django.db import migrations, models\n"
            "\n"
            "class Migration(migrations.Migration):\n"
            "    operations = [\n"
            "        migrations.CreateModel(\n"
            "            name='UserObjectPermission',\n"
            "            fields=[\n"
            "                ('id', models.AutoField(primary_key=True)),\n"
            "                ('object_pk', models.CharField(max_length=255)),\n"
            "                ('content_type', models.ForeignKey(to='contenttypes.ContentType', on_delete=models.CASCADE)),\n"
            "                ('permission', models.ForeignKey(to='auth.Permission', on_delete=models.CASCADE)),\n"
            "                ('user', models.ForeignKey(to='auth.User', on_delete=models.CASCADE)),\n"
            "            ],\n"
            "        ),\n"
            "    ]\n",
        )

    def test_inherited_columns_are_not_reported_as_drift(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._workspace(root)
            report = detect_drift(str(root))
            self.assertEqual(
                report.to_dict()["drifted"],
                [],
                "abstract-base columns must count as declared",
            )

    def test_a_genuinely_missing_column_still_blocks(self) -> None:
        """The fix must not blunt the check it is loosening."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._workspace(root)
            # Declare one more field than the migration creates.
            (root / "guardian" / "models.py").write_text(
                GUARDIAN_LIKE.replace(
                    "class Meta:\n        unique_together",
                    "extra = models.IntegerField(default=0)\n\n"
                    "    class Meta:\n        unique_together",
                ),
                encoding="utf-8",
            )
            report = detect_drift(str(root))
            drifted = report.to_dict()["drifted"]
            self.assertEqual(len(drifted), 1)
            self.assertEqual(drifted[0]["missingInMigrations"], ["extra"])
            self.assertTrue(drifted[0]["blocking"])


INDEXED_MODELS = '''
from django.db import models


class AModel(models.Model):
    field = models.IntegerField()


class SimpleModel(models.Model):
    unique_field = models.IntegerField(unique=True)
    foreign_key = models.ForeignKey(AModel, on_delete=models.CASCADE, db_index=True)
    other_field = models.IntegerField()
    plain = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("foreign_key", "other_field"), name="uc"),
        ]
'''


class SuggestIndexAlreadyIndexedTest(unittest.TestCase):
    """#60: never propose an index the model already has."""

    def _run(self, calls: str) -> dict:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "shop" / "models.py", INDEXED_MODELS)
            _write(root / "shop" / "__init__.py", "")
            _write(root / "views.py", calls)
            return suggest_indexes("shop", "SimpleModel", str(root))

    def test_primary_key_lookups_propose_nothing(self) -> None:
        result = self._run(
            "from shop.models import SimpleModel\n"
            "def a():\n"
            "    return SimpleModel.objects.filter(pk=1)\n"
            "def b():\n"
            "    return SimpleModel.objects.filter(id=2)\n"
        )
        self.assertEqual(result["proposed_indexes"], [])
        # Both spellings are the same lookup, so they land on one row of two.
        singles = {
            u["field"]: u["sites"]
            for u in result["filter_usages"]
            if not u.get("composite")
        }
        self.assertEqual(singles, {"id": 2})

    def test_unique_and_db_index_and_fk_propose_nothing(self) -> None:
        result = self._run(
            "from shop.models import SimpleModel\n"
            "def a():\n"
            "    SimpleModel.objects.filter(unique_field=1)\n"
            "    SimpleModel.objects.filter(unique_field=2)\n"
            "    SimpleModel.objects.filter(foreign_key=3)\n"
            "    SimpleModel.objects.filter(foreign_key=4)\n"
        )
        self.assertEqual(result["proposed_indexes"], [])
        self.assertIn("unique_field", result["already_indexed"])
        self.assertIn("foreign_key", result["already_indexed"])

    def test_unique_constraint_covers_its_column_group(self) -> None:
        result = self._run(
            "from shop.models import SimpleModel\n"
            "def a():\n"
            "    SimpleModel.objects.filter(foreign_key=1, other_field=2)\n"
            "def b():\n"
            "    SimpleModel.objects.filter(foreign_key=3, other_field=4)\n"
        )
        proposed = [p["fields"] for p in result["proposed_indexes"]]
        # The constraint's own column group is covered, and so is its leading
        # column — that is what the unique index answers.
        self.assertNotIn(["foreign_key", "other_field"], proposed)
        self.assertNotIn(["foreign_key"], proposed)
        # ``other_field`` is NOT covered: a B-tree on (foreign_key,
        # other_field) cannot serve a lookup on the trailing column alone.
        # Suppressing it here would be a different bug from the one #60
        # reports.
        self.assertEqual(proposed, [["other_field"]])

    def test_an_unindexed_hot_field_is_still_proposed(self) -> None:
        """The fix must not silence the tool's actual job."""
        result = self._run(
            "from shop.models import SimpleModel\n"
            "def a():\n"
            "    SimpleModel.objects.filter(plain=1)\n"
            "def b():\n"
            "    SimpleModel.objects.filter(plain=2)\n"
        )
        self.assertEqual(
            [p["fields"] for p in result["proposed_indexes"]], [["plain"]]
        )


class MetaMultilineValueTest(unittest.TestCase):
    """The parser used to truncate a multi-line ``Meta`` entry to ``[``.

    That is why ``Meta.constraints`` and any list-per-line ``Meta.indexes``
    were invisible to the index analyzer.
    """

    def test_constraints_block_is_joined(self) -> None:
        models_ = parse_models_file("shop/models.py", INDEXED_MODELS)
        simple = next(m for m in models_ if m.name == "SimpleModel")
        self.assertIn("UniqueConstraint", simple.meta["constraints"])
        self.assertIn("foreign_key", simple.meta["constraints"])

    def test_single_line_values_are_unchanged(self) -> None:
        source = (
            "from django.db import models\n"
            "\n"
            "class Thing(models.Model):\n"
            "    name = models.CharField(max_length=10)\n"
            "\n"
            "    class Meta:\n"
            "        ordering = ['-name']\n"
            "        verbose_name = 'thing'\n"
        )
        thing = parse_models_file("shop/models.py", source)[0]
        self.assertEqual(thing.meta["ordering"], "['-name']")
        self.assertEqual(thing.meta["verbose_name"], "'thing'")


class WorkspaceInheritanceTest(unittest.TestCase):
    def test_abstract_base_in_another_file_still_donates(self) -> None:
        """Cross-file resolution already worked for *recognition* (#20).

        Field inheritance has to reach across files the same way, or the fix
        only works for projects that keep their bases in one module.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "common" / "models.py",
                "from django.db import models\n"
                "\n"
                "class Stamped(models.Model):\n"
                "    created = models.DateTimeField(auto_now_add=True)\n"
                "\n"
                "    class Meta:\n"
                "        abstract = True\n",
            )
            _write(
                root / "blog" / "models.py",
                "from common.models import Stamped\n"
                "from django.db import models\n"
                "\n"
                "class Post(Stamped):\n"
                "    title = models.CharField(max_length=100)\n",
            )
            index = scan_workspace(str(root))
            post = next(
                m
                for app in index.apps
                for m in app.models
                if m.name == "Post"
            )
            self.assertEqual(
                [f.name for f in post.all_fields()], ["created", "title"]
            )


if __name__ == "__main__":
    unittest.main()
