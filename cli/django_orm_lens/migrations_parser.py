"""Static Django migration DAG parser — pure AST, no Django boot, no DB.

Standout MCP capability: agents debugging migration conflicts can inspect the
per-app dependency graph without importing user code or running
``manage.py showmigrations``. Every field is extracted from a plain
``ast.parse`` of ``<app>/migrations/*.py``.

Returned shape (see :func:`describe_migration_dependency`):
``{app_label, migrations[{name, dependencies, operations}], roots, leaves,
cross_app_deps, [error]}``.

Semantics:
* ``roots``  — migrations with no dependency on the *same* app
* ``leaves`` — migrations no other migration in this app depends on (DAG tips)
* ``cross_app_deps`` — dedup'd list of ``[app_label, migration_name]`` pairs
  pointing at OTHER apps (flags risky cross-app coupling)

If the app has no ``migrations/`` folder anywhere in the workspace, a
structured ``error`` key is returned rather than raising — matches the tool
conventions used by ``describe_model`` / ``cascade_preview``.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MIGRATION_FILENAME_RE = re.compile(r"^\d{4}_.+\.py$")


def _find_migrations_dirs(root: str, app_label: str) -> List[Path]:
    """Walk ``root`` and return every ``<app_label>/migrations`` folder found.

    A workspace may contain the same app label in multiple locations
    (mono-repos, vendored copies). We union them so the caller sees every
    migration file matching the label.
    """
    matches: List[Path] = []
    root_path = Path(root)
    for dirpath, dirnames, _filenames in os.walk(root_path):
        # skip hidden / virtualenv-ish trees for perf and correctness
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in ("node_modules", "venv", ".venv", "env")
        ]
        if os.path.basename(dirpath) == "migrations":
            parent = os.path.basename(os.path.dirname(dirpath))
            if parent == app_label:
                matches.append(Path(dirpath))
    return matches


def _iter_migration_files(migrations_dir: Path) -> List[Path]:
    files: List[Path] = []
    try:
        for entry in migrations_dir.iterdir():
            if entry.is_file() and MIGRATION_FILENAME_RE.match(entry.name):
                files.append(entry)
    except OSError:
        return []
    files.sort(key=lambda p: p.name)
    return files


def _literal_or_none(node: ast.AST) -> Any:
    """Best-effort literal_eval; returns ``None`` if the node isn't a literal."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def _extract_operation_names(operations_node: ast.AST) -> List[str]:
    """From ``operations = [...]`` return the class name of each element.

    Handles the two common Django conventions:
    * ``migrations.AddField(...)`` — ``Attribute`` on a ``Call``
    * ``AddField(...)`` (bare import) — ``Name`` on a ``Call``

    Anything more exotic (variable reference, unpacked list, computed) is
    silently dropped — this is a static best-effort extractor.
    """
    names: List[str] = []
    if not isinstance(operations_node, (ast.List, ast.Tuple)):
        return names
    for elt in operations_node.elts:
        if not isinstance(elt, ast.Call):
            continue
        func = elt.func
        if isinstance(func, ast.Attribute):
            names.append(func.attr)
        elif isinstance(func, ast.Name):
            names.append(func.id)
    return names


def _extract_dependency_pairs(deps_node: ast.AST) -> List[List[str]]:
    """Extract ``[(app, name), ...]`` from a ``dependencies = [...]`` node.

    Returns a list of ``[app, name]`` pairs (list not tuple, so it serialises
    cleanly to JSON via the MCP boundary).
    """
    pairs: List[List[str]] = []
    if not isinstance(deps_node, (ast.List, ast.Tuple)):
        return pairs
    for elt in deps_node.elts:
        value = _literal_or_none(elt)
        if (
            isinstance(value, (tuple, list))
            and len(value) == 2
            and all(isinstance(v, str) for v in value)
        ):
            pairs.append([value[0], value[1]])
    return pairs


def _parse_migration_file(path: Path) -> Optional[Dict[str, Any]]:
    """Parse one migration file. Returns dict or ``None`` on unreadable/invalid."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return None

    name = path.stem  # e.g. "0042_add_user_email"
    dependencies: List[List[str]] = []
    operations: List[str] = []

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name != "Migration":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            if "dependencies" in targets:
                dependencies = _extract_dependency_pairs(stmt.value)
            elif "operations" in targets:
                operations = _extract_operation_names(stmt.value)
        break  # only the first class named Migration counts

    return {
        "name": name,
        "dependencies": dependencies,
        "operations": operations,
    }


def _compute_roots_leaves_cross(
    migrations: List[Dict[str, Any]], app_label: str
) -> Tuple[List[str], List[str], List[List[str]]]:
    names = {m["name"] for m in migrations}
    roots: List[str] = []
    depended_on_within_app: set = set()
    cross_seen: set = set()
    cross_app_deps: List[List[str]] = []

    for m in migrations:
        in_app_deps = [
            dep for dep in m["dependencies"] if dep[0] == app_label
        ]
        if not in_app_deps:
            roots.append(m["name"])
        for dep in in_app_deps:
            if dep[1] in names:
                depended_on_within_app.add(dep[1])
        for dep in m["dependencies"]:
            if dep[0] != app_label:
                key = (dep[0], dep[1])
                if key not in cross_seen:
                    cross_seen.add(key)
                    cross_app_deps.append([dep[0], dep[1]])

    leaves = [m["name"] for m in migrations if m["name"] not in depended_on_within_app]
    return roots, leaves, cross_app_deps


def describe_migration_dependency(app_label: str, root: str) -> Dict[str, Any]:
    """Return the migration DAG for a Django app, extracted via pure AST parse.

    :param app_label: the Django app name (folder name that contains ``migrations/``)
    :param root: workspace root to scan
    :returns: dict per module docstring. On missing folder, includes ``error``.
    """
    dirs = _find_migrations_dirs(root, app_label)
    if not dirs:
        return {
            "app_label": app_label,
            "migrations": [],
            "error": "no migrations folder found",
        }

    seen_names: set = set()
    migrations: List[Dict[str, Any]] = []
    for migrations_dir in dirs:
        for py in _iter_migration_files(migrations_dir):
            parsed = _parse_migration_file(py)
            if parsed is None:
                continue
            if parsed["name"] in seen_names:
                continue
            seen_names.add(parsed["name"])
            migrations.append(parsed)

    migrations.sort(key=lambda m: m["name"])
    roots, leaves, cross_app_deps = _compute_roots_leaves_cross(migrations, app_label)

    return {
        "app_label": app_label,
        "migrations": migrations,
        "roots": roots,
        "leaves": leaves,
        "cross_app_deps": cross_app_deps,
    }
