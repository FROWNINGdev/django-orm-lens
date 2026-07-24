"""Integration tests for :mod:`django_orm_lens.mcp_server`.

These validate the contract that FastMCP will expose to AI agents:

* Every tool in :data:`TOOLS` declares ``workspace_root`` in its handler
  signature (via ``_resolve``) — the historical silent-drop bug is closed.
* Handlers return a structured JSON error envelope when the workspace can't
  be resolved, instead of an empty list.
* Every tool description advertises the ``workspace_root`` parameter so
  agents see it in ``tools/list``.

FastMCP itself (the ``server.tool()`` decorator wiring) is exercised by the
end-to-end round-trip in the release checklist — spawning a subprocess and
speaking JSON-RPC. Here we test the pure-Python contract, which is enough
to catch every regression that the pre-1.3.0 code carried.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from django_orm_lens.mcp_server import (
    TOOLS,
    _resolve,
    _tool_cascade_preview,
    _tool_describe_migration_dependency,
    _tool_describe_model,
    _tool_er_diagram,
    _tool_find_relations,
    _tool_list_apps,
    _tool_list_models,
    _tool_signal_graph,
    _tool_suggest_indexes,
)
from django_orm_lens.workspace import WorkspaceError, clear_cache

_MODELS_SOURCE = """from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=100)


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
"""


def _write_django_project(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manage.py").write_text(
        "#!/usr/bin/env python\n# fixture manage.py\n", encoding="utf-8"
    )
    app = root / "myapp"
    app.mkdir(exist_ok=True)
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "models.py").write_text(_MODELS_SOURCE, encoding="utf-8")


class ToolsRegistryTest(unittest.TestCase):
    """The ``TOOLS`` dict is what feeds ``tools/list`` — schema-level asserts."""

    def test_all_nine_tools_registered(self) -> None:
        expected = {
            "list_apps",
            "list_models",
            "describe_model",
            "find_relations",
            "cascade_preview",
            "er_diagram",
            "describe_migration_dependency",
            "suggest_indexes",
            "signal_graph",
        }
        self.assertEqual(set(TOOLS), expected)

    def test_every_description_advertises_workspace_root(self) -> None:
        # tools/list is where agents read what a tool accepts. If any
        # description forgets workspace_root, we regress to the silent-drop
        # symptom for that tool.
        for name, spec in TOOLS.items():
            with self.subTest(tool=name):
                self.assertIn(
                    "workspace_root",
                    spec["description"],
                    f"{name}: description must mention 'workspace_root'",
                )

    def test_every_handler_is_callable(self) -> None:
        for name, spec in TOOLS.items():
            with self.subTest(tool=name):
                self.assertTrue(callable(spec["handler"]))


class ResolveHelperTest(unittest.TestCase):
    """``_resolve`` is the single entry point every tool uses. It bridges
    the args-dict contract to :func:`workspace.resolve_workspace`. Verify
    the bridge does not lose or corrupt the argument."""

    def setUp(self) -> None:
        self._env = os.environ.get("DJANGO_ORM_LENS_ROOT")
        os.environ.pop("DJANGO_ORM_LENS_ROOT", None)
        self.tmp = Path(tempfile.mkdtemp(prefix="djol-server-"))
        _write_django_project(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        if self._env is not None:
            self.addCleanup(os.environ.__setitem__, "DJANGO_ORM_LENS_ROOT", self._env)
        clear_cache()
        self.addCleanup(clear_cache)

    def test_explicit_arg_reaches_resolve(self) -> None:
        result = _resolve({"workspace_root": str(self.tmp)})
        self.assertIsInstance(result, Path)
        self.assertEqual(result, self.tmp.resolve())

    def test_missing_key_falls_through_to_env_or_cwd(self) -> None:
        os.environ["DJANGO_ORM_LENS_ROOT"] = str(self.tmp)
        result = _resolve({})
        self.assertIsInstance(result, Path)

    def test_empty_string_falls_through(self) -> None:
        os.environ["DJANGO_ORM_LENS_ROOT"] = str(self.tmp)
        result = _resolve({"workspace_root": ""})
        self.assertIsInstance(result, Path)

    def test_none_value_falls_through(self) -> None:
        os.environ["DJANGO_ORM_LENS_ROOT"] = str(self.tmp)
        result = _resolve({"workspace_root": None})
        self.assertIsInstance(result, Path)


class ErrorEnvelopeTest(unittest.TestCase):
    """When workspace resolution fails, every tool must return the JSON
    envelope — never an empty list, never a raw exception."""

    def setUp(self) -> None:
        self._env = os.environ.get("DJANGO_ORM_LENS_ROOT")
        os.environ.pop("DJANGO_ORM_LENS_ROOT", None)
        self.tmp = Path(tempfile.mkdtemp(prefix="djol-envelope-"))
        # Deliberately do NOT write a Django project — every tool must fail.
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        if self._env is not None:
            self.addCleanup(os.environ.__setitem__, "DJANGO_ORM_LENS_ROOT", self._env)
        clear_cache()
        self.addCleanup(clear_cache)

    def _assert_envelope(self, raw: str, expected_code: str = "WORKSPACE_NOT_DJANGO") -> None:
        payload = json.loads(raw)
        self.assertIn("error", payload, f"payload missing 'error' key: {payload}")
        self.assertIn("message", payload)
        self.assertIn("hint", payload)
        self.assertIn("path", payload)
        self.assertEqual(payload["error"], expected_code)

    def test_list_apps_envelope(self) -> None:
        self._assert_envelope(_tool_list_apps({"workspace_root": str(self.tmp)}))

    def test_list_models_envelope(self) -> None:
        self._assert_envelope(_tool_list_models({"workspace_root": str(self.tmp)}))

    def test_describe_model_envelope(self) -> None:
        self._assert_envelope(
            _tool_describe_model(
                {"workspace_root": str(self.tmp), "model": "myapp.Book"}
            )
        )

    def test_find_relations_envelope(self) -> None:
        self._assert_envelope(
            _tool_find_relations(
                {"workspace_root": str(self.tmp), "model": "myapp.Book"}
            )
        )

    def test_cascade_preview_envelope(self) -> None:
        self._assert_envelope(
            _tool_cascade_preview(
                {
                    "workspace_root": str(self.tmp),
                    "app_label": "myapp",
                    "model_name": "Book",
                }
            )
        )

    def test_er_diagram_envelope(self) -> None:
        self._assert_envelope(_tool_er_diagram({"workspace_root": str(self.tmp)}))

    def test_describe_migration_dependency_envelope(self) -> None:
        self._assert_envelope(
            _tool_describe_migration_dependency(
                {"workspace_root": str(self.tmp), "app_label": "myapp"}
            )
        )

    def test_suggest_indexes_envelope(self) -> None:
        self._assert_envelope(
            _tool_suggest_indexes(
                {
                    "workspace_root": str(self.tmp),
                    "app_label": "myapp",
                    "model_name": "Book",
                }
            )
        )

    def test_signal_graph_envelope(self) -> None:
        self._assert_envelope(_tool_signal_graph({"workspace_root": str(self.tmp)}))

    def test_missing_workspace_returns_not_found_envelope(self) -> None:
        raw = _tool_list_apps({"workspace_root": str(self.tmp / "no-such-dir")})
        self._assert_envelope(raw, expected_code="WORKSPACE_NOT_FOUND")


class HappyPathTest(unittest.TestCase):
    """When workspace_root points at a real Django project the tools must
    behave exactly like the pre-1.3.0 successful path — this is the
    equivalence check that guards the behavioural-neutral half of the fix."""

    def setUp(self) -> None:
        self._env = os.environ.get("DJANGO_ORM_LENS_ROOT")
        os.environ.pop("DJANGO_ORM_LENS_ROOT", None)
        self.tmp = Path(tempfile.mkdtemp(prefix="djol-happy-"))
        _write_django_project(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        if self._env is not None:
            self.addCleanup(os.environ.__setitem__, "DJANGO_ORM_LENS_ROOT", self._env)
        clear_cache()
        self.addCleanup(clear_cache)

    def test_list_apps_returns_apps(self) -> None:
        raw = _tool_list_apps({"workspace_root": str(self.tmp)})
        payload = json.loads(raw)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["name"], "myapp")
        self.assertEqual(payload[0]["models"], 2)

    def test_list_models_returns_dotted_names(self) -> None:
        raw = _tool_list_models({"workspace_root": str(self.tmp)})
        self.assertIn("myapp.Author", raw)
        self.assertIn("myapp.Book", raw)

    def test_describe_model_returns_field_detail(self) -> None:
        raw = _tool_describe_model(
            {"workspace_root": str(self.tmp), "model": "myapp.Book"}
        )
        payload = json.loads(raw)
        self.assertEqual(payload["name"], "Book")
        field_names = {f["name"] for f in payload.get("fields", [])}
        self.assertIn("title", field_names)
        self.assertIn("author", field_names)

    def test_env_var_is_still_honoured(self) -> None:
        # Backwards-compat guarantee: the historical env-var-only workflow
        # still works when no explicit arg is passed.
        os.environ["DJANGO_ORM_LENS_ROOT"] = str(self.tmp)
        raw = _tool_list_apps({})
        payload = json.loads(raw)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 1)


class SentinelDataclassTest(unittest.TestCase):
    """The WorkspaceError sentinel is what powers the envelope. Keep the
    dict shape stable so agents can pattern-match on ``error`` field."""

    def test_to_dict_shape(self) -> None:
        err = WorkspaceError(code="X", message="m", hint="h", path="/p")
        payload = err.to_dict()
        self.assertEqual(set(payload), {"error", "message", "hint", "path"})
        self.assertEqual(payload["error"], "X")


if __name__ == "__main__":
    unittest.main()
