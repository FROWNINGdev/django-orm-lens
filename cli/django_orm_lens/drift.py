"""Schema drift — do the migrations still describe the models?

Django answers this with ``makemigrations --check``, which needs a working
settings module, an importable app registry, and every third-party dependency
installed. On a cold clone, a broken venv, or a CI job that deliberately does
not boot the project, that answer is unavailable exactly when it would be
cheapest to act on.

This module answers it from source. It replays each app's migrations in order
— ``CreateModel``, ``AddField``, ``RemoveField``, ``RenameField``,
``DeleteModel``, ``RenameModel`` — into the set of fields the migrations
believe each model has, then compares that against what ``models.py`` actually
declares.

Two kinds of drift come out, and they fail in opposite directions:

* **A field in models.py with no migration.** Someone edited a model and
  forgot ``makemigrations``. Deploy and the column is missing under a model
  that expects it — an error at runtime, on the first query that touches it.
* **A field in the migrations that no model declares.** The column exists and
  nothing reads it. Usually harmless, occasionally a half-finished removal
  still holding a ``NOT NULL`` constraint.

Being static, this cannot see what Django computes at import time — abstract
bases resolved through metaclasses, fields injected by third-party mixins,
swappable models. Those surface as drift that is not real, which is why the
report separates the two directions and never blocks on the "extra in
migrations" side alone.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .migrations_parser import (
    _build_current_schema,
    _find_all_migration_apps,
    _iter_migration_files,
    _literal_or_none,
    _migration_prefix,
)

# Operations that change which fields a model has. AlterField is absent on
# purpose: it changes a column's type or options, never the field's existence,
# so it cannot produce drift in the sense measured here.
_STRUCTURAL_OPS = frozenset(
    {
        "CreateModel",
        "DeleteModel",
        "RenameModel",
        "AddField",
        "RemoveField",
        "RenameField",
    }
)

# Django adds these itself unless told otherwise, so a migration that omits
# them is not drift.
_IMPLICIT_FIELDS = frozenset({"id"})


@dataclass
class ModelDrift:
    """One model whose migrations and declaration disagree."""

    app: str
    model: str
    missing_in_migrations: list[str] = field(default_factory=list)
    """Declared in models.py, never migrated — the dangerous direction."""
    missing_in_models: list[str] = field(default_factory=list)
    """Migrated, but no longer declared."""
    only_in_models: bool = False
    """The model has no CreateModel anywhere."""
    only_in_migrations: bool = False
    """The migrations create it; models.py does not declare it."""

    @property
    def label(self) -> str:
        return f"{self.app}.{self.model}"

    @property
    def is_blocking(self) -> bool:
        """Only the "code expects a column that will not exist" direction.

        Extra columns are noise far more often than they are bugs, and static
        analysis cannot see mixin-injected fields — failing a build on those
        would train people to pass ``--exit-zero`` forever.
        """
        return bool(self.missing_in_migrations) or self.only_in_models

    def to_dict(self) -> dict[str, Any]:
        return {
            "app": self.app,
            "model": self.model,
            "missingInMigrations": sorted(self.missing_in_migrations),
            "missingInModels": sorted(self.missing_in_models),
            "onlyInModels": self.only_in_models,
            "onlyInMigrations": self.only_in_migrations,
            "blocking": self.is_blocking,
        }


@dataclass
class DriftReport:
    drifted: list[ModelDrift] = field(default_factory=list)
    apps_scanned: int = 0
    migrations_replayed: int = 0

    @property
    def blocking_count(self) -> int:
        return sum(1 for d in self.drifted if d.is_blocking)

    def to_dict(self) -> dict[str, Any]:
        return {
            "drifted": [d.to_dict() for d in self.drifted],
            "summary": {
                "apps": self.apps_scanned,
                "migrations": self.migrations_replayed,
                "drifted": len(self.drifted),
                "blocking": self.blocking_count,
            },
        }


def _op_name(call: ast.Call) -> str | None:
    """``migrations.AddField(...)`` → ``AddField``."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _kwarg(call: ast.Call, name: str) -> Any:
    for kw in call.keywords:
        if kw.arg == name:
            return _literal_or_none(kw.value)
    return None


def _create_model_fields(call: ast.Call) -> list[str]:
    """Field names out of ``CreateModel(fields=[("title", ...), ...])``.

    The second element of each pair is a field *constructor call*, which
    ``ast.literal_eval`` cannot touch — so the names are read positionally
    rather than by evaluating the list.
    """
    names: list[str] = []
    for kw in call.keywords:
        if kw.arg != "fields":
            continue
        if not isinstance(kw.value, (ast.List, ast.Tuple)):
            continue
        for item in kw.value.elts:
            if isinstance(item, (ast.Tuple, ast.List)) and item.elts:
                first = item.elts[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    names.append(first.value)
    return names


def _operations(tree: ast.AST) -> list[ast.Call]:
    """Every call inside a ``Migration.operations = [...]`` list."""
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "operations" not in targets:
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            out.extend(e for e in node.value.elts if isinstance(e, ast.Call))
    return out


def _apply(state: dict[str, set[str]], op: str, call: ast.Call) -> None:
    if op == "CreateModel":
        name = _kwarg(call, "name")
        if isinstance(name, str):
            state[name.lower()] = set(_create_model_fields(call)) - _IMPLICIT_FIELDS
        return
    if op == "DeleteModel":
        name = _kwarg(call, "name")
        if isinstance(name, str):
            state.pop(name.lower(), None)
        return
    if op == "RenameModel":
        old, new = _kwarg(call, "old_name"), _kwarg(call, "new_name")
        if isinstance(old, str) and isinstance(new, str):
            state[new.lower()] = state.pop(old.lower(), set())
        return

    model = _kwarg(call, "model_name")
    if not isinstance(model, str):
        return
    fields = state.setdefault(model.lower(), set())
    if op == "AddField":
        name = _kwarg(call, "name")
        if isinstance(name, str):
            fields.add(name)
    elif op == "RemoveField":
        name = _kwarg(call, "name")
        if isinstance(name, str):
            fields.discard(name)
    elif op == "RenameField":
        old, new = _kwarg(call, "old_name"), _kwarg(call, "new_name")
        if isinstance(old, str) and isinstance(new, str):
            fields.discard(old)
            fields.add(new)


def replay_app(migrations_dir: Path) -> tuple[dict[str, set[str]], int]:
    """Replay one app's migrations into ``{model_lower: {field_names}}``.

    :returns: the state, and how many migration files contributed to it.
    """
    state: dict[str, set[str]] = {}
    files = sorted(
        _iter_migration_files(migrations_dir),
        key=lambda p: (_migration_prefix(p.stem), p.name),
    )
    replayed = 0
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            # A migration we cannot parse is skipped rather than fatal: one
            # bad file must not blank out the whole app's state.
            continue
        replayed += 1
        for call in _operations(tree):
            op = _op_name(call)
            if op in _STRUCTURAL_OPS:
                _apply(state, op, call)
    return state, replayed


def detect_drift(
    project_root: str | Path,
    *,
    declared: dict[str, dict[str, set]] | None = None,
) -> DriftReport:
    """Compare replayed migration state against declared models.

    :param declared: pre-built ``{app: {model_lower: {fields}}}``; mostly for
        tests. Built from the workspace parser when omitted.
    """
    root = str(Path(project_root).resolve())
    if declared is None:
        declared = _build_current_schema(root)

    report = DriftReport()
    seen_apps: set[str] = set()

    for app_label, migrations_dir in _find_all_migration_apps(root):
        migrated, replayed = replay_app(migrations_dir)
        report.migrations_replayed += replayed
        seen_apps.add(app_label)
        declared_app = declared.get(app_label, {})

        for model, migrated_fields in migrated.items():
            declared_fields = declared_app.get(model)
            if declared_fields is None:
                report.drifted.append(
                    ModelDrift(app=app_label, model=model, only_in_migrations=True)
                )
                continue
            declared_set = set(declared_fields) - _IMPLICIT_FIELDS
            missing_in_migrations = sorted(declared_set - migrated_fields)
            missing_in_models = sorted(migrated_fields - declared_set)
            if missing_in_migrations or missing_in_models:
                report.drifted.append(
                    ModelDrift(
                        app=app_label,
                        model=model,
                        missing_in_migrations=missing_in_migrations,
                        missing_in_models=missing_in_models,
                    )
                )

        for model in declared_app:
            if model not in migrated:
                report.drifted.append(
                    ModelDrift(app=app_label, model=model, only_in_models=True)
                )

    report.apps_scanned = len(seen_apps)
    report.drifted.sort(key=lambda d: (not d.is_blocking, d.label))
    return report


def format_drift(report: DriftReport) -> str:
    """Human-readable text. JSON is serialised by the caller."""
    if not report.drifted:
        return (
            f"no drift — {report.migrations_replayed} migration(s) across "
            f"{report.apps_scanned} app(s) match the declared models."
        )
    out: list[str] = []
    for d in report.drifted:
        mark = "!!" if d.is_blocking else " ~"
        if d.only_in_models:
            out.append(f"{mark} {d.label}: declared, but no migration creates it")
            out.append("     run makemigrations, or the table will not exist")
            continue
        if d.only_in_migrations:
            out.append(
                f"{mark} {d.label}: migrated, but models.py does not declare it"
            )
            out.append("     stale table, or the model lives outside the parsed tree")
            continue
        out.append(f"{mark} {d.label}:")
        if d.missing_in_migrations:
            out.append(
                "     declared but never migrated: "
                + ", ".join(d.missing_in_migrations)
            )
            out.append("       the column will be missing at runtime")
        if d.missing_in_models:
            out.append(
                "     migrated but no longer declared: "
                + ", ".join(d.missing_in_models)
            )
    out.append("")
    out.append(
        f"summary: {len(report.drifted)} model(s) drifted, "
        f"{report.blocking_count} blocking, "
        f"{report.migrations_replayed} migration(s) replayed"
    )
    return "\n".join(out)
