"""django-orm-lens -> orm-lens: everything written against the old name still works."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

import orm_lens
from orm_lens import workspace

# The old names ship in the compat distribution (compat/django-orm-lens), which
# CI does not pip-install; put its source on the path instead.
COMPAT = Path(__file__).resolve().parents[2] / "compat" / "django-orm-lens"
if COMPAT.is_dir() and str(COMPAT) not in sys.path:
    sys.path.insert(0, str(COMPAT))
pytest.importorskip("django_orm_lens")


def test_old_top_level_import_is_the_same_api() -> None:
    import django_orm_lens

    assert django_orm_lens.scan_workspace is orm_lens.scan_workspace
    assert django_orm_lens.__version__ == orm_lens.__version__


def test_old_submodule_imports_are_the_same_modules() -> None:
    import django_orm_lens.cli
    import django_orm_lens.query_analyzer
    from django_orm_lens.parser import scan_workspace

    assert django_orm_lens.cli is orm_lens.cli
    assert django_orm_lens.query_analyzer is sys.modules["orm_lens.query_analyzer"]
    assert scan_workspace is orm_lens.scan_workspace
    # The alias must not rewrite the real module's identity.
    assert orm_lens.cli.__spec__ is not None
    assert orm_lens.cli.__spec__.name == "orm_lens.cli"


def test_patching_through_the_old_path_reaches_the_real_module() -> None:
    with mock.patch("django_orm_lens.workspace._env", return_value="") as fake:
        assert workspace._env is fake


def test_python_dash_m_old_name_runs_the_cli() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "django_orm_lens", "--version"],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    assert out.stdout.strip().startswith("orm-lens ")


def test_env_vars_fall_back_to_the_pre_rename_names(tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if "ORM_LENS_" not in k}
    env["DJANGO_ORM_LENS_ROOT"] = str(tmp_path)
    with mock.patch.dict(os.environ, env, clear=True):
        assert workspace.resolve_workspace() == tmp_path.resolve()
        os.environ["ORM_LENS_ROOT"] = str(tmp_path / "missing")
        # The new name wins when both are set.
        assert not isinstance(workspace.resolve_workspace(), Path)
