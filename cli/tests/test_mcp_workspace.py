"""Unit tests for :mod:`django_orm_lens.workspace`.

These pin the exact behaviour of the professional workspace-resolution fix
shipped in py-1.3.0. The pre-1.3.0 code silently dropped the
``workspace_root`` argument (never declared on tool signatures) and fell back
to ``cwd``, so agents saw ``[]`` with no error. Every test here corresponds
to a failure mode we want to keep surfaced rather than swallowed.

Groupings:
    * ``HardenPathTest`` — one path in, one clean verdict out (unit).
    * ``ResolveWorkspaceTest`` — priority chain across arg, env, cwd.
    * ``AllowlistTest`` — ``DJANGO_ORM_LENS_ALLOWED_ROOTS`` containment.
    * ``CacheTest`` — TTL + mtime salt + LRU cap.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from collections.abc import Iterable
from pathlib import Path

from django_orm_lens.workspace import (
    _CACHE_MAX,
    _INDEX_CACHE,
    WorkspaceError,
    clear_cache,
    get_index,
    harden_path,
    resolve_workspace,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MODELS_SOURCE = """from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=100)


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
"""


def _write_django_project(root: Path, *, with_manage: bool = True) -> None:
    """Write a minimal Django-shaped tree under ``root``.

    ``manage.py`` is optional so we can also exercise the models.py fallback.
    """
    root.mkdir(parents=True, exist_ok=True)
    if with_manage:
        (root / "manage.py").write_text(
            "#!/usr/bin/env python\n# fixture manage.py\n", encoding="utf-8"
        )
    app = root / "myapp"
    app.mkdir(exist_ok=True)
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "models.py").write_text(_MODELS_SOURCE, encoding="utf-8")


def _env_snapshot(names: Iterable[str]) -> dict:
    return {n: os.environ.get(n) for n in names}


def _env_restore(snapshot: dict) -> None:
    for n, v in snapshot.items():
        if v is None:
            os.environ.pop(n, None)
        else:
            os.environ[n] = v


# ---------------------------------------------------------------------------
# harden_path
# ---------------------------------------------------------------------------


class HardenPathTest(unittest.TestCase):
    """One raw input in, one clean verdict out. No priority chain here."""

    def setUp(self) -> None:
        self._env = _env_snapshot(
            ("DJANGO_ORM_LENS_ROOT", "DJANGO_ORM_LENS_ALLOWED_ROOTS")
        )
        os.environ.pop("DJANGO_ORM_LENS_ROOT", None)
        os.environ.pop("DJANGO_ORM_LENS_ALLOWED_ROOTS", None)
        self.tmp = Path(tempfile.mkdtemp(prefix="djol-harden-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(_env_restore, self._env)

    def test_empty_returns_workspace_empty(self) -> None:
        result = harden_path("")
        self.assertIsInstance(result, WorkspaceError)
        self.assertEqual(result.code, "WORKSPACE_EMPTY")
        self.assertIn("workspace_root", result.hint)

    def test_missing_directory_returns_not_found(self) -> None:
        missing = str(self.tmp / "does-not-exist")
        result = harden_path(missing)
        self.assertIsInstance(result, WorkspaceError)
        self.assertEqual(result.code, "WORKSPACE_NOT_FOUND")

    def test_file_not_directory_returns_not_a_directory(self) -> None:
        f = self.tmp / "manage.py"
        f.write_text("", encoding="utf-8")
        result = harden_path(str(f))
        self.assertIsInstance(result, WorkspaceError)
        self.assertEqual(result.code, "WORKSPACE_NOT_A_DIRECTORY")

    def test_valid_django_project_returns_resolved_path(self) -> None:
        _write_django_project(self.tmp)
        result = harden_path(str(self.tmp))
        self.assertIsInstance(result, Path)
        # Must be absolute + normalized (resolve() collapsed any traversal).
        self.assertTrue(result.is_absolute())
        self.assertEqual(result, self.tmp.resolve())

    def test_models_py_fallback_without_manage_py(self) -> None:
        _write_django_project(self.tmp, with_manage=False)
        result = harden_path(str(self.tmp))
        self.assertIsInstance(result, Path)

    def test_missing_django_marker_returns_not_django(self) -> None:
        # An empty directory with no marker.
        result = harden_path(str(self.tmp))
        self.assertIsInstance(result, WorkspaceError)
        self.assertEqual(result.code, "WORKSPACE_NOT_DJANGO")
        self.assertIn("manage.py", result.hint)

    def test_pyproject_django_dep_counts_as_marker(self) -> None:
        # Modern docker-first Django apps ship pyproject.toml + poetry, no manage.py.
        (self.tmp / "pyproject.toml").write_text(
            "[tool.poetry.dependencies]\ndjango = \"^5.1\"\n", encoding="utf-8"
        )
        result = harden_path(str(self.tmp))
        self.assertIsInstance(result, Path)

    def test_traversal_is_collapsed_before_validation(self) -> None:
        # Feed the resolver a path with ".." — resolve() must normalize before we
        # apply any allowlist check. This is the classic path-traversal defense.
        _write_django_project(self.tmp)
        weird = str(self.tmp / "myapp" / "..")
        result = harden_path(weird)
        self.assertIsInstance(result, Path)
        # Resolved path must equal the parent, not contain literal "..".
        self.assertEqual(result, self.tmp.resolve())
        self.assertNotIn("..", str(result))

    def test_expanduser_is_applied(self) -> None:
        # ~ should be expanded even if the home dir itself isn't a Django project.
        result = harden_path("~")
        # Either resolved to a Path or rejected with NOT_DJANGO / NOT_FOUND —
        # never a raw "~" leaking through.
        if isinstance(result, WorkspaceError):
            self.assertNotIn("~", result.path)
        else:
            self.assertNotIn("~", str(result))


# ---------------------------------------------------------------------------
# Windows-reserved names
# ---------------------------------------------------------------------------


class WindowsReservedTest(unittest.TestCase):
    """Reserved-name paths are rejected on every OS — paths flow between
    machines. Test exercises the helper directly with synthetic input; no
    real Windows device is touched."""

    def test_component_matching_reserved_name_is_rejected(self) -> None:
        from django_orm_lens.workspace import _has_windows_reserved

        self.assertTrue(_has_windows_reserved(Path("/tmp/CON/foo")))
        self.assertTrue(_has_windows_reserved(Path("/tmp/COM1/foo")))
        self.assertTrue(_has_windows_reserved(Path("/tmp/prn.txt")))
        self.assertFalse(_has_windows_reserved(Path("/tmp/console/foo")))
        self.assertFalse(_has_windows_reserved(Path("/tmp/comment/foo")))


# ---------------------------------------------------------------------------
# resolve_workspace priority chain
# ---------------------------------------------------------------------------


class ResolveWorkspaceTest(unittest.TestCase):
    """Priority: explicit arg > env var > cwd. A failure at a chosen step is
    surfaced, not silently swallowed — that is the whole point of the fix."""

    def setUp(self) -> None:
        self._env = _env_snapshot(
            ("DJANGO_ORM_LENS_ROOT", "DJANGO_ORM_LENS_ALLOWED_ROOTS")
        )
        os.environ.pop("DJANGO_ORM_LENS_ROOT", None)
        os.environ.pop("DJANGO_ORM_LENS_ALLOWED_ROOTS", None)
        self.tmp = Path(tempfile.mkdtemp(prefix="djol-resolve-"))
        _write_django_project(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(_env_restore, self._env)

    def test_explicit_argument_wins(self) -> None:
        os.environ["DJANGO_ORM_LENS_ROOT"] = str(self.tmp / "does-not-exist")
        result = resolve_workspace(str(self.tmp))
        self.assertIsInstance(result, Path)
        self.assertEqual(result, self.tmp.resolve())

    def test_env_var_used_when_no_argument(self) -> None:
        os.environ["DJANGO_ORM_LENS_ROOT"] = str(self.tmp)
        result = resolve_workspace()
        self.assertIsInstance(result, Path)
        self.assertEqual(result, self.tmp.resolve())

    def test_falls_back_to_cwd_when_nothing_set(self) -> None:
        prior = os.getcwd()
        try:
            os.chdir(str(self.tmp))
            result = resolve_workspace()
        finally:
            os.chdir(prior)
        self.assertIsInstance(result, Path)
        self.assertEqual(result, self.tmp.resolve())

    def test_explicit_failure_is_surfaced_not_silenced(self) -> None:
        # The pre-1.3.0 bug: explicit arg silently dropped, fell to cwd.
        # Post-fix: an explicit arg that fails validation surfaces an error
        # so the agent knows it needs to pass a different value.
        result = resolve_workspace(str(self.tmp / "no-such-subdir"))
        self.assertIsInstance(result, WorkspaceError)
        self.assertEqual(result.code, "WORKSPACE_NOT_FOUND")

    def test_env_failure_is_surfaced_not_silenced(self) -> None:
        os.environ["DJANGO_ORM_LENS_ROOT"] = str(self.tmp / "no-such-subdir")
        result = resolve_workspace()
        self.assertIsInstance(result, WorkspaceError)
        self.assertEqual(result.code, "WORKSPACE_NOT_FOUND")


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------


class AllowlistTest(unittest.TestCase):
    """``DJANGO_ORM_LENS_ALLOWED_ROOTS`` — opt-in sandboxing for shared hosts."""

    def setUp(self) -> None:
        self._env = _env_snapshot(
            ("DJANGO_ORM_LENS_ROOT", "DJANGO_ORM_LENS_ALLOWED_ROOTS")
        )
        os.environ.pop("DJANGO_ORM_LENS_ROOT", None)
        os.environ.pop("DJANGO_ORM_LENS_ALLOWED_ROOTS", None)
        self.tmp = Path(tempfile.mkdtemp(prefix="djol-allow-"))
        self.inside = self.tmp / "projects" / "app"
        self.outside = self.tmp / "other" / "app"
        _write_django_project(self.inside)
        _write_django_project(self.outside)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(_env_restore, self._env)

    def test_path_within_allowlist_passes(self) -> None:
        os.environ["DJANGO_ORM_LENS_ALLOWED_ROOTS"] = str(self.tmp / "projects")
        result = harden_path(str(self.inside))
        self.assertIsInstance(result, Path)

    def test_path_outside_allowlist_rejected(self) -> None:
        os.environ["DJANGO_ORM_LENS_ALLOWED_ROOTS"] = str(self.tmp / "projects")
        result = harden_path(str(self.outside))
        self.assertIsInstance(result, WorkspaceError)
        self.assertEqual(result.code, "WORKSPACE_NOT_ALLOWED")

    def test_empty_allowlist_env_is_unrestricted(self) -> None:
        os.environ["DJANGO_ORM_LENS_ALLOWED_ROOTS"] = ""
        result = harden_path(str(self.outside))
        self.assertIsInstance(result, Path)

    def test_multiple_allowlist_entries(self) -> None:
        sep = ";" if os.name == "nt" else ":"
        os.environ["DJANGO_ORM_LENS_ALLOWED_ROOTS"] = (
            f"{self.tmp / 'projects'}{sep}{self.tmp / 'other'}"
        )
        self.assertIsInstance(harden_path(str(self.inside)), Path)
        self.assertIsInstance(harden_path(str(self.outside)), Path)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class CacheTest(unittest.TestCase):
    """The compound (resolved_path, manage.py mtime) key + LRU cap."""

    def setUp(self) -> None:
        self._env = _env_snapshot(
            ("DJANGO_ORM_LENS_ROOT", "DJANGO_ORM_LENS_ALLOWED_ROOTS")
        )
        os.environ.pop("DJANGO_ORM_LENS_ROOT", None)
        os.environ.pop("DJANGO_ORM_LENS_ALLOWED_ROOTS", None)
        self.tmp = Path(tempfile.mkdtemp(prefix="djol-cache-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(_env_restore, self._env)
        clear_cache()
        self.addCleanup(clear_cache)

    def test_hits_cache_on_second_call(self) -> None:
        _write_django_project(self.tmp)
        root = harden_path(str(self.tmp))
        assert isinstance(root, Path)
        idx1 = get_index(root)
        idx2 = get_index(root)
        self.assertIs(
            idx1,
            idx2,
            "same resolved root + same mtime -> identical cached object",
        )

    def test_manage_py_mtime_change_invalidates(self) -> None:
        _write_django_project(self.tmp)
        root = harden_path(str(self.tmp))
        assert isinstance(root, Path)
        idx1 = get_index(root)
        # Sleep past 1s so int(mtime) is guaranteed to differ, then touch.
        time.sleep(1.1)
        (self.tmp / "manage.py").write_text("# touched\n", encoding="utf-8")
        idx2 = get_index(root)
        self.assertIsNot(
            idx1,
            idx2,
            "editing manage.py must invalidate the cache without waiting for TTL",
        )

    def test_lru_cap_enforced(self) -> None:
        for i in range(_CACHE_MAX + 2):
            sub = self.tmp / f"proj-{i}"
            _write_django_project(sub)
            r = harden_path(str(sub))
            assert isinstance(r, Path)
            get_index(r)
        self.assertLessEqual(
            len(_INDEX_CACHE),
            _CACHE_MAX,
            f"cache grew past cap: {len(_INDEX_CACHE)} > {_CACHE_MAX}",
        )

    def test_clear_cache_empties(self) -> None:
        _write_django_project(self.tmp)
        root = harden_path(str(self.tmp))
        assert isinstance(root, Path)
        get_index(root)
        self.assertGreater(len(_INDEX_CACHE), 0)
        clear_cache()
        self.assertEqual(len(_INDEX_CACHE), 0)


if __name__ == "__main__":
    unittest.main()
