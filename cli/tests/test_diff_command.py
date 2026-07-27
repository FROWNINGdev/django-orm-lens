"""Tests for the ``diff`` subcommand and its underlying diff module."""

from __future__ import annotations

import json
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django_orm_lens.cli import main
from django_orm_lens.diff import diff_schemas, format_diff
from django_orm_lens.parser import scan_workspace

# --- Hand-written fixture schemas ------------------------------------------

def _schema(*models: dict) -> dict:
    """Build a WorkspaceIndex-shaped dict from a flat list of model dicts."""
    apps: dict = {}
    for m in models:
        app = m["appName"]
        apps.setdefault(app, []).append(m)
    return {
        "apps": [
            {"name": name, "path": f"{name}/", "models": ms}
            for name, ms in apps.items()
        ],
        "scannedAt": 0,
    }


def _scalar(name: str, type_: str = "CharField", args: str = "max_length=100") -> dict:
    return {
        "name": name,
        "type": type_,
        "args": args,
        "isRelation": False,
        "lineNumber": 1,
    }


def _relation(
    name: str,
    kind: str = "ForeignKey",
    target: str = "Author",
    on_delete: str = "CASCADE",
    related_name: str = None,
) -> dict:
    f = {
        "name": name,
        "type": kind,
        "args": f"{target}, on_delete=models.{on_delete}",
        "isRelation": True,
        "lineNumber": 1,
        "relatedModel": target,
        "relationKind": kind,
        "onDelete": on_delete,
    }
    if related_name is not None:
        f["relatedName"] = related_name
    return f


def _model(app: str, name: str, fields: list) -> dict:
    return {
        "name": name,
        "appName": app,
        "filePath": f"{app}/models.py",
        "lineNumber": 1,
        "baseClasses": ["models.Model"],
        "fields": fields,
        "meta": {},
    }


# --- diff_schemas() unit tests ---------------------------------------------


class DiffSchemasTest(unittest.TestCase):
    def test_no_changes_yields_empty_result(self) -> None:
        old = _schema(_model("blog", "Post", [_scalar("title")]))
        new = _schema(_model("blog", "Post", [_scalar("title")]))
        r = diff_schemas(old, new)
        self.assertTrue(r.is_empty())

    def test_added_and_removed_models(self) -> None:
        old = _schema(_model("blog", "Post", [_scalar("title")]))
        new = _schema(_model("blog", "Comment", [_scalar("body")]))
        r = diff_schemas(old, new)
        self.assertEqual(r.added_models, ["blog.Comment"])
        self.assertEqual(r.removed_models, ["blog.Post"])

    def test_added_and_removed_fields(self) -> None:
        old = _schema(_model("blog", "Post", [_scalar("title")]))
        new = _schema(
            _model("blog", "Post", [_scalar("title"), _scalar("slug", "SlugField", "")])
        )
        r = diff_schemas(old, new)
        self.assertEqual([f.name for f in r.added_fields], ["slug"])
        self.assertEqual(r.added_fields[0].model, "blog.Post")
        self.assertEqual(r.added_fields[0].type, "SlugField")
        self.assertEqual(r.removed_fields, [])

        r2 = diff_schemas(new, old)
        self.assertEqual([f.name for f in r2.removed_fields], ["slug"])
        self.assertEqual(r2.added_fields, [])

    def test_changed_field_constraints(self) -> None:
        old = _schema(
            _model("blog", "Post", [_scalar("title", "CharField", "max_length=100")])
        )
        new = _schema(
            _model("blog", "Post", [_scalar("title", "CharField", "max_length=200")])
        )
        r = diff_schemas(old, new)
        self.assertEqual(len(r.changed_fields), 1)
        c = r.changed_fields[0]
        self.assertEqual(c.model, "blog.Post")
        self.assertEqual(c.name, "title")
        self.assertIn("args", c.changes)
        self.assertEqual(c.changes["args"]["old"], "max_length=100")
        self.assertEqual(c.changes["args"]["new"], "max_length=200")

    def test_changed_field_type(self) -> None:
        old = _schema(_model("blog", "Post", [_scalar("body", "CharField", "")]))
        new = _schema(_model("blog", "Post", [_scalar("body", "TextField", "")]))
        r = diff_schemas(old, new)
        self.assertEqual(len(r.changed_fields), 1)
        self.assertIn("type", r.changed_fields[0].changes)

    def test_added_and_removed_relations(self) -> None:
        old = _schema(_model("blog", "Post", [_scalar("title")]))
        new = _schema(
            _model("blog", "Post", [_scalar("title"), _relation("author")])
        )
        r = diff_schemas(old, new)
        self.assertEqual(len(r.added_relations), 1)
        rel = r.added_relations[0]
        self.assertEqual(rel.name, "author")
        self.assertEqual(rel.kind, "ForeignKey")
        self.assertEqual(rel.target, "Author")

        r2 = diff_schemas(new, old)
        self.assertEqual(len(r2.removed_relations), 1)
        self.assertEqual(r2.removed_relations[0].name, "author")

    def test_changed_relation_on_delete(self) -> None:
        old = _schema(
            _model("blog", "Post", [_relation("author", on_delete="CASCADE")])
        )
        new = _schema(
            _model("blog", "Post", [_relation("author", on_delete="SET_NULL")])
        )
        r = diff_schemas(old, new)
        self.assertEqual(len(r.changed_relations), 1)
        c = r.changed_relations[0]
        self.assertEqual(c.name, "author")
        self.assertIn("onDelete", c.changes)
        self.assertEqual(c.changes["onDelete"]["old"], "CASCADE")
        self.assertEqual(c.changes["onDelete"]["new"], "SET_NULL")

    def test_mixed_changes_across_multiple_models(self) -> None:
        old = _schema(
            _model("blog", "Post", [_scalar("title"), _relation("author")]),
            _model("blog", "Draft", [_scalar("body", "TextField", "")]),
        )
        new = _schema(
            _model(
                "blog",
                "Post",
                [
                    _scalar("title", "CharField", "max_length=250"),
                    _relation("author", on_delete="SET_NULL"),
                    _scalar("slug", "SlugField", ""),
                ],
            ),
            _model("blog", "Comment", [_scalar("body", "TextField", "")]),
        )
        r = diff_schemas(old, new)
        self.assertEqual(r.added_models, ["blog.Comment"])
        self.assertEqual(r.removed_models, ["blog.Draft"])
        self.assertEqual([f.name for f in r.added_fields], ["slug"])
        self.assertEqual(len(r.changed_fields), 1)
        self.assertEqual(len(r.changed_relations), 1)
        self.assertFalse(r.is_empty())

    def test_line_number_change_is_not_a_diff(self) -> None:
        old_field = _scalar("title")
        new_field = _scalar("title")
        new_field["lineNumber"] = 42
        r = diff_schemas(
            _schema(_model("blog", "Post", [old_field])),
            _schema(_model("blog", "Post", [new_field])),
        )
        self.assertTrue(r.is_empty())

    def test_empty_apps_key_is_forgiving(self) -> None:
        # Diffing against `{}` should surface as "everything removed".
        old = _schema(_model("blog", "Post", [_scalar("title")]))
        r = diff_schemas(old, {})
        self.assertEqual(r.removed_models, ["blog.Post"])
        self.assertEqual(r.added_models, [])


# --- format_diff() unit tests ----------------------------------------------


class FormatDiffTest(unittest.TestCase):
    def test_empty_result_text(self) -> None:
        old = _schema(_model("blog", "Post", [_scalar("title")]))
        r = diff_schemas(old, old)
        self.assertEqual(format_diff(r, "text"), "No schema changes.")

    def test_text_output_contains_expected_markers(self) -> None:
        old = _schema(_model("blog", "Post", [_scalar("title")]))
        new = _schema(
            _model(
                "blog",
                "Post",
                [_scalar("title", "CharField", "max_length=250"), _relation("author")],
            )
        )
        text = format_diff(diff_schemas(old, new), "text")
        self.assertIn("Added relations:", text)
        self.assertIn("+ blog.Post.author -> Author (ForeignKey)", text)
        self.assertIn("Changed fields:", text)
        self.assertIn("~ blog.Post.title", text)

    def test_json_format_has_expected_top_level_keys(self) -> None:
        old = _schema(_model("blog", "Post", [_scalar("title")]))
        new = _schema(_model("blog", "Comment", [_scalar("body")]))
        payload = json.loads(format_diff(diff_schemas(old, new), "json"))
        for key in (
            "addedModels",
            "removedModels",
            "addedFields",
            "removedFields",
            "changedFields",
            "addedRelations",
            "removedRelations",
            "changedRelations",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["addedModels"], ["blog.Comment"])
        self.assertEqual(payload["removedModels"], ["blog.Post"])

    def test_unknown_format_raises(self) -> None:
        r = diff_schemas({}, {})
        with self.assertRaises(ValueError):
            format_diff(r, "xml")


# --- CLI integration tests -------------------------------------------------


class DiffCommandCLITest(unittest.TestCase):
    def _write(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_no_diff_exits_zero(self) -> None:
        schema = _schema(_model("blog", "Post", [_scalar("title")]))
        with TemporaryDirectory() as tmp:
            old_p = Path(tmp) / "before.json"
            new_p = Path(tmp) / "after.json"
            self._write(old_p, schema)
            self._write(new_p, schema)
            with patch("sys.stdout", new=StringIO()) as stdout:
                code = main(["diff", str(old_p), str(new_p)])
            self.assertEqual(code, 0)
            self.assertIn("No schema changes.", stdout.getvalue())

    def test_diff_exits_one(self) -> None:
        old = _schema(_model("blog", "Post", [_scalar("title")]))
        new = _schema(_model("blog", "Comment", [_scalar("body")]))
        with TemporaryDirectory() as tmp:
            old_p = Path(tmp) / "before.json"
            new_p = Path(tmp) / "after.json"
            self._write(old_p, old)
            self._write(new_p, new)
            with patch("sys.stdout", new=StringIO()) as stdout:
                code = main(["diff", str(old_p), str(new_p)])
            self.assertEqual(code, 1)
            out = stdout.getvalue()
            self.assertIn("Added models:", out)
            self.assertIn("+ blog.Comment", out)
            self.assertIn("Removed models:", out)
            self.assertIn("- blog.Post", out)

    def test_exit_zero_flag_forces_zero(self) -> None:
        old = _schema(_model("blog", "Post", [_scalar("title")]))
        new = _schema(_model("blog", "Comment", [_scalar("body")]))
        with TemporaryDirectory() as tmp:
            old_p = Path(tmp) / "before.json"
            new_p = Path(tmp) / "after.json"
            self._write(old_p, old)
            self._write(new_p, new)
            with patch("sys.stdout", new=StringIO()):
                code = main(["diff", str(old_p), str(new_p), "--exit-zero"])
            self.assertEqual(code, 0)

    def test_json_format_output_is_valid_json(self) -> None:
        old = _schema(_model("blog", "Post", [_scalar("title")]))
        new = _schema(
            _model("blog", "Post", [_scalar("title", "CharField", "max_length=250")])
        )
        with TemporaryDirectory() as tmp:
            old_p = Path(tmp) / "before.json"
            new_p = Path(tmp) / "after.json"
            self._write(old_p, old)
            self._write(new_p, new)
            with patch("sys.stdout", new=StringIO()) as stdout:
                code = main(["diff", str(old_p), str(new_p), "--format", "json"])
            self.assertEqual(code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(len(payload["changedFields"]), 1)
            self.assertEqual(payload["changedFields"][0]["model"], "blog.Post")

    def test_missing_file_reports_error(self) -> None:
        with TemporaryDirectory() as tmp:
            new_p = Path(tmp) / "after.json"
            self._write(new_p, _schema())
            with patch("sys.stdout", new=StringIO()), patch(
                "sys.stderr", new=StringIO()
            ) as stderr:
                code = main(["diff", str(Path(tmp) / "nope.json"), str(new_p)])
            self.assertEqual(code, 2)
            self.assertIn("not found", stderr.getvalue())

    def test_invalid_json_reports_error(self) -> None:
        with TemporaryDirectory() as tmp:
            old_p = Path(tmp) / "bad.json"
            new_p = Path(tmp) / "after.json"
            old_p.write_text("not json {{{", encoding="utf-8")
            self._write(new_p, _schema())
            with patch("sys.stdout", new=StringIO()), patch(
                "sys.stderr", new=StringIO()
            ) as stderr:
                code = main(["diff", str(old_p), str(new_p)])
            self.assertEqual(code, 2)
            self.assertIn("not valid JSON", stderr.getvalue())


# --- Golden-fixture integration test ---------------------------------------


class DiffGoldenFixtureTest(unittest.TestCase):
    """Diff two similar golden fixtures — real parser output, not hand-written.

    Picking two projects that both exist under ``tests/fixtures/golden/``
    exercises the diff on realistic schema shapes. The specific delta
    values aren't asserted (upstream projects can change) — just that the
    parser output round-trips through ``to_dict()`` cleanly and produces
    a non-empty diff, since the two projects are unrelated.
    """

    def test_diff_between_two_golden_projects(self) -> None:
        golden = Path(__file__).parent / "fixtures" / "golden"
        # Pick any two distinct projects; they will differ substantially.
        projects = sorted(
            p.name for p in golden.iterdir() if p.is_dir() and p.name != "__pycache__"
        )
        self.assertGreaterEqual(
            len(projects), 2, "golden fixtures should contain at least two projects"
        )
        old_index = scan_workspace(str(golden / projects[0]))
        new_index = scan_workspace(str(golden / projects[1]))

        old_dump = old_index.to_dict()
        new_dump = new_index.to_dict()

        # Round-trip through JSON to prove the diff works on serialised input,
        # which is the real usage pattern.
        old_schema = json.loads(json.dumps(old_dump))
        new_schema = json.loads(json.dumps(new_dump))

        result = diff_schemas(old_schema, new_schema)
        # Two unrelated projects — the diff must not be empty.
        self.assertFalse(result.is_empty())
        # And a subset of the older project's models must show up as removed.
        old_keys = {
            f"{app['name']}.{m['name']}"
            for app in old_dump["apps"]
            for m in app["models"]
        }
        self.assertTrue(set(result.removed_models).issubset(old_keys))

        # JSON formatter must produce parseable JSON on real input.
        payload = json.loads(format_diff(result, "json"))
        self.assertIn("addedModels", payload)


if __name__ == "__main__":
    unittest.main()
