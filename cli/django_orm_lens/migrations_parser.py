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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MIGRATION_FILENAME_RE = re.compile(r"^\d{4}_.+\.py$")
_MIGRATION_PREFIX_RE = re.compile(r"^(\d+)_")

# Skip patterns for filesystem walk (mirrors parser.py conventions).
_SKIP_DIRS = frozenset(
    {".git", "node_modules", "venv", ".venv", "env", "__pycache__", ".tox"}
)

# Operation types we recognize during risk analysis.
_KNOWN_OP_TYPES = frozenset(
    {
        "AddField",
        "RemoveField",
        "AlterField",
        "RenameField",
        "RenameModel",
        "DeleteModel",
        "CreateModel",
        "AddIndex",
        "AddIndexConcurrently",
        "RemoveIndex",
        "RunSQL",
        "RunPython",
        "AlterUniqueTogether",
        "AlterIndexTogether",
    }
)


def _find_migrations_dirs(root: str, app_label: str) -> list[Path]:
    """Walk ``root`` and return every ``<app_label>/migrations`` folder found.

    A workspace may contain the same app label in multiple locations
    (mono-repos, vendored copies). We union them so the caller sees every
    migration file matching the label.
    """
    matches: list[Path] = []
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


def _iter_migration_files(migrations_dir: Path) -> list[Path]:
    files: list[Path] = []
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


def _extract_operation_names(operations_node: ast.AST) -> list[str]:
    """From ``operations = [...]`` return the class name of each element.

    Handles the two common Django conventions:
    * ``migrations.AddField(...)`` — ``Attribute`` on a ``Call``
    * ``AddField(...)`` (bare import) — ``Name`` on a ``Call``

    Anything more exotic (variable reference, unpacked list, computed) is
    silently dropped — this is a static best-effort extractor.
    """
    names: list[str] = []
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


def _extract_dependency_pairs(deps_node: ast.AST) -> list[list[str]]:
    """Extract ``[(app, name), ...]`` from a ``dependencies = [...]`` node.

    Returns a list of ``[app, name]`` pairs (list not tuple, so it serialises
    cleanly to JSON via the MCP boundary).
    """
    pairs: list[list[str]] = []
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


def _parse_migration_file(path: Path) -> dict[str, Any] | None:
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
    dependencies: list[list[str]] = []
    operations: list[str] = []
    replaces: list[list[str]] = []

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
            elif "replaces" in targets:
                replaces = _extract_dependency_pairs(stmt.value)
        break  # only the first class named Migration counts

    out: dict[str, Any] = {
        "name": name,
        "dependencies": dependencies,
        "operations": operations,
    }
    if replaces:
        out["replaces"] = replaces
    return out


def _collapse_squashed(
    migrations: list[dict[str, Any]], app_label: str | None
) -> list[dict[str, Any]]:
    """Model Django's loader: a squashed migration stands in for its replaces.

    When both a squashed migration and the migrations it ``replaces`` are on
    disk, Django drops the replaced nodes from the graph and points every
    dependency on them at the squash. Counting leaves without doing the same
    calls the last replaced migration a second leaf and reports a conflict
    that Django never raises.
    """
    replaced_by: dict[str, str] = {}
    for m in migrations:
        for dep in m.get("replaces", []):
            if dep[0] == app_label:
                replaced_by[dep[1]] = m["name"]
    if not replaced_by:
        return migrations

    def resolve(name: str) -> str:
        seen: set = set()
        while name in replaced_by and name not in seen:
            seen.add(name)
            name = replaced_by[name]
        return name

    out: list[dict[str, Any]] = []
    for m in migrations:
        if m["name"] in replaced_by:
            continue
        deps: list[list[str]] = []
        for dep in m["dependencies"]:
            if dep[0] == app_label and dep[1] in replaced_by:
                target = resolve(dep[1])
                if target == m["name"]:
                    continue  # the squash depending on what it replaces
                dep = [dep[0], target]
            if dep not in deps:
                deps.append(dep)
        out.append({**m, "dependencies": deps})
    return out


def _compute_roots_leaves_cross(
    migrations: list[dict[str, Any]], app_label: str
) -> tuple[list[str], list[str], list[list[str]]]:
    names = {m["name"] for m in migrations}
    roots: list[str] = []
    depended_on_within_app: set = set()
    cross_seen: set = set()
    cross_app_deps: list[list[str]] = []

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


def describe_migration_dependency(app_label: str, root: str) -> dict[str, Any]:
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
    migrations: list[dict[str, Any]] = []
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
    roots, leaves, cross_app_deps = _compute_roots_leaves_cross(
        _collapse_squashed(migrations, app_label), app_label
    )

    return {
        "app_label": app_label,
        "migrations": migrations,
        "roots": roots,
        "leaves": leaves,
        "cross_app_deps": cross_app_deps,
    }


# ---------------------------------------------------------------------------
# Migration risk analysis
# ---------------------------------------------------------------------------

Severity = str  # "critical" | "warning" | "info"
Confidence = str  # "high" | "medium" | "low"


@dataclass
class MigrationRisk:
    """A single flagged risk in a migration file.

    Attributes are camelCase-friendly on serialization to match the shape
    used by other analyzers in this package.
    """

    file_path: str
    line_number: int
    app: str
    migration: str
    operation: str
    model: str | None
    field: str | None
    rule: str
    description: str
    mitigation: str
    confidence: Confidence
    severity: Severity
    old_name: str | None = None
    """For RenameField / RenameModel: the name before the rename, which is
    what code that has not been updated still uses."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "filePath": self.file_path,
            "lineNumber": self.line_number,
            "app": self.app,
            "migration": self.migration,
            "operation": self.operation,
            "model": self.model,
            "field": self.field,
            "rule": self.rule,
            "description": self.description,
            "mitigation": self.mitigation,
            "confidence": self.confidence,
            "severity": self.severity,
        }


def _get_kwarg(call: ast.Call, name: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _kwarg_literal(call: ast.Call, name: str) -> Any:
    node = _get_kwarg(call, name)
    if node is None:
        return None
    return _literal_or_none(node)


def _has_kwarg(call: ast.Call, name: str) -> bool:
    return _get_kwarg(call, name) is not None


def _call_op_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _field_call(node: ast.AST | None) -> ast.Call | None:
    """Return the underlying field constructor Call node, if any.

    ``AddField(field=models.CharField(max_length=10))`` — we want the
    ``models.CharField(...)`` Call.
    """
    if isinstance(node, ast.Call):
        return node
    return None


def _field_type(call: ast.Call) -> str | None:
    """Return the constructor name of a field call (e.g. ``CharField``)."""
    return _call_op_name(call)


# Field classes that add no column to the model's own table: a join table
# (M2M and its third-party twins) or nothing at all (GenericRelation).
_NO_COLUMN_FIELDS = frozenset(
    {
        "ManyToManyField",
        "TaggableManager",
        "GenericRelation",
        "ParentalManyToManyField",
        "SortedManyToManyField",
        "TreeManyToManyField",
    }
)

# Fields Django fills with "" (b"" for BinaryField) when they are blank=True
# and get no explicit default: BaseDatabaseSchemaEditor._effective_default
# does that for every field with empty_strings_allowed. Numeric, date, bool,
# UUID and FK fields do not allow empty strings and are not here.
_EMPTY_STRING_FIELDS = frozenset(
    {
        "CharField",
        "TextField",
        "SlugField",
        "EmailField",
        "URLField",
        "FileField",
        "ImageField",
        "FilePathField",
        "BinaryField",
        "CICharField",
        "CIEmailField",
        "CITextField",
    }
)

_AUTO_NOW_FIELDS = frozenset({"DateField", "DateTimeField", "TimeField"})

_STRING_FIELD_SUFFIXES = ("CharField", "TextField", "SlugField", "EmailField", "URLField")


def _is_string_field(field_call: ast.Call, field_type: str) -> bool:
    """A field that stores text, including project subclasses of one.

    Migrations reference custom fields by their own class name
    (``utilities.fields.ColorField``, ``LowercaseSlugField``), which no list
    can know in advance. Two signals stand in: a name ending in a text field's
    name, or a ``max_length`` argument, which only CharField and its
    subclasses take among the fields that reach a migration.
    """
    return (
        field_type in _EMPTY_STRING_FIELDS
        or field_type.endswith(_STRING_FIELD_SUFFIXES)
        or _has_kwarg(field_call, "max_length")
    )


def _has_effective_default(field_call: ast.Call, field_type: str) -> bool:
    """True when Django fills existing rows without an explicit ``default=``.

    Mirrors ``BaseDatabaseSchemaEditor._effective_default`` and the other
    ways a column gets a value on ADD COLUMN:

    * ``db_default=`` (Django 5.0+) is a database-side default;
    * ``blank=True`` on a field that allows empty strings gets ``""``;
    * ``auto_now`` / ``auto_now_add`` date fields get the current time;
    * ``GeneratedField`` is computed by the database.
    """
    if _has_kwarg(field_call, "db_default") or field_type == "GeneratedField":
        return True
    if _kwarg_literal(field_call, "blank") is True and _is_string_field(field_call, field_type):
        return True
    return field_type in _AUTO_NOW_FIELDS and (
        _kwarg_literal(field_call, "auto_now") is True
        or _kwarg_literal(field_call, "auto_now_add") is True
    )


def _migration_prefix(name: str) -> int:
    """Return the numeric prefix of a migration filename stem, or -1."""
    m = _MIGRATION_PREFIX_RE.match(name)
    if not m:
        return -1
    try:
        return int(m.group(1))
    except ValueError:
        return -1


def _find_all_migration_apps(project_root: str) -> list[tuple[str, Path]]:
    """Walk ``project_root`` and yield ``(app_label, migrations_dir)`` pairs.

    Skips hidden, virtualenv-ish, and vendored trees.
    """
    out: list[tuple[str, Path]] = []
    root_path = Path(project_root)
    for dirpath, dirnames, _filenames in os.walk(root_path):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in _SKIP_DIRS
        ]
        if os.path.basename(dirpath) == "migrations":
            parent = os.path.basename(os.path.dirname(dirpath))
            if parent and parent not in _SKIP_DIRS:
                out.append((parent, Path(dirpath)))
    return out


def _build_current_schema(project_root: str) -> dict[str, dict[str, set]]:
    """Return ``{app_name: {model_name_lower: {field_names}}}`` from parser.

    Failures are swallowed — cross-reference rule is best-effort.
    """
    try:
        from .parser import scan_workspace  # local import to avoid cycles
    except ImportError:
        return {}
    schema: dict[str, dict[str, set]] = {}
    try:
        index = scan_workspace(project_root)
    except (OSError, ValueError, SyntaxError):
        # Narrow to error classes scan_workspace realistically raises: OSError
        # for missing/unreadable files, ValueError/SyntaxError from the parser.
        # Anything else (MemoryError, RecursionError, KeyboardInterrupt) must
        # propagate — swallowing them hides bugs and abuse patterns.
        return schema
    for app in index.apps:
        app_map = schema.setdefault(app.name, {})
        for model in app.models:
            # all_fields(), not fields: an abstract base's columns live on the
            # concrete child's table, so a migration that creates them is not
            # drift. Reported as #58 against django-guardian, where four such
            # fields read as "migrated but no longer declared".
            app_map[model.name.lower()] = {f.name for f in model.all_fields()}
    return schema


class MigrationRiskAnalyzer:
    """AST-walk one migration file and emit :class:`MigrationRisk` findings.

    Stateless per call — construct with the enclosing context (app label,
    migration index within its app, current schema) and call
    :meth:`analyze`. The analyzer does not import Django, does not execute
    the migration; it only inspects the ``operations = [...]`` list of the
    ``Migration`` class via ``ast``.
    """

    def __init__(
        self,
        file_path: Path,
        app: str,
        migration_name: str,
        migration_index: int,
        current_schema: dict[str, dict[str, set]] | None = None,
    ) -> None:
        self.file_path = file_path
        self.app = app
        self.migration_name = migration_name
        # 0 == first migration in the app (0001_initial). Any value > 0 is
        # our heuristic that the table is already populated in production.
        self.migration_index = migration_index
        self.current_schema = current_schema or {}
        self.findings: list[MigrationRisk] = []
        # Tables this migration creates itself: still empty when a later
        # operation in the same file alters them (makemigrations splits FKs
        # out of CreateModel into AddField exactly like that).
        self.created_models: set[str] = set()
        # A squashed migration (``replaces = [...]``) only ever runs on a fresh
        # database. Where the replaced migrations are applied, Django marks it
        # applied without running it, so it never touches populated tables.
        self.is_squashed = False
        # (line, model, field-or-None) for every operation that brings a field
        # or a whole model (back) into existence. A RemoveField followed by an
        # AddField or a RenameField onto the same name, or a DeleteModel
        # followed by a CreateModel, leaves the name in place; the
        # still-referenced rules check this list, in this file and later ones.
        self.introduced: list[tuple[int, str, str | None]] = []
        # A data operation earlier in the file that may empty or backfill the
        # table before a NOT NULL column arrives.
        self.data_op_before = False
        self.module_strings: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------
    def analyze(self) -> list[MigrationRisk]:
        try:
            source = self.file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        try:
            tree = ast.parse(source, filename=str(self.file_path))
        except SyntaxError:
            return []

        # Module-level string constants, so RunSQL(SOME_SQL) can be read.
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.module_strings[t.id] = node.value.value

        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name != "Migration":
                continue
            assigns = [stmt for stmt in node.body if isinstance(stmt, ast.Assign)]
            # `replaces` can sit before or after `operations`; read it first.
            for stmt in assigns:
                targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                if "replaces" in targets and isinstance(stmt.value, (ast.List, ast.Tuple)):
                    self.is_squashed = bool(stmt.value.elts)
            for stmt in assigns:
                targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                if "operations" not in targets:
                    continue
                self._walk_operations(stmt.value)
            break  # only first Migration class
        return self.findings

    # ------------------------------------------------------------------
    # Operation dispatch
    # ------------------------------------------------------------------
    def _walk_operations(self, ops_node: ast.AST) -> None:
        if not isinstance(ops_node, (ast.List, ast.Tuple)):
            return
        for elt in ops_node.elts:
            if not isinstance(elt, ast.Call):
                continue
            op = _call_op_name(elt)
            if op is None or op not in _KNOWN_OP_TYPES:
                continue
            if op == "CreateModel":
                created = _kwarg_literal(elt, "name")
                if created is None and elt.args:
                    created = _literal_or_none(elt.args[0])
                if isinstance(created, str):
                    self.created_models.add(created.lower())
            handler = getattr(self, f"_check_{op}", None)
            self._record_introduction(op, elt)
            if op == "RunPython" or (op == "RunSQL" and self._sql_changes_rows(elt)):
                # Read only by operations later in the list; this element's own
                # handler does not look at it.
                self.data_op_before = True
            if handler is not None:
                try:
                    handler(elt)
                except (AttributeError, TypeError, ValueError, KeyError, IndexError):
                    # Narrow to error classes a malformed AST-node walk might
                    # realistically raise. Never let a single malformed op sink
                    # the run — but propagate MemoryError, KeyboardInterrupt,
                    # SystemExit, or any unexpected class so real bugs surface.
                    continue

    # ------------------------------------------------------------------
    # Helpers to record findings
    # ------------------------------------------------------------------
    def _add(
        self,
        call: ast.Call,
        operation: str,
        rule: str,
        description: str,
        mitigation: str,
        confidence: Confidence,
        severity: Severity,
        model: str | None = None,
        field: str | None = None,
        old_name: str | None = None,
    ) -> None:
        self.findings.append(
            MigrationRisk(
                file_path=str(self.file_path),
                line_number=getattr(call, "lineno", 0),
                app=self.app,
                migration=self.migration_name,
                operation=operation,
                model=model,
                field=field,
                rule=rule,
                description=description,
                mitigation=mitigation,
                confidence=confidence,
                severity=severity,
                old_name=old_name,
            )
        )

    def _record_introduction(self, op: str, call: ast.Call) -> None:
        line = getattr(call, "lineno", 0)
        if op == "AddField":
            model, name = _kwarg_literal(call, "model_name"), _kwarg_literal(call, "name")
        elif op == "RenameField":
            model, name = _kwarg_literal(call, "model_name"), _kwarg_literal(call, "new_name")
        elif op == "CreateModel":
            model, name = _kwarg_literal(call, "name"), None
            if model is None and call.args:
                model = _literal_or_none(call.args[0])
        elif op == "RenameModel":
            model, name = _kwarg_literal(call, "new_name"), None
        else:
            return
        if isinstance(model, str):
            self.introduced.append((line, model.lower(), name if isinstance(name, str) else None))

    def _sql_changes_rows(self, call: ast.Call) -> bool:
        """RunSQL whose forward SQL deletes, truncates or updates rows."""
        node = _get_kwarg(call, "sql") or (call.args[0] if call.args else None)
        parts = node.elts if isinstance(node, (ast.List, ast.Tuple)) else [node]
        for part in parts:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                sql = part.value
            elif isinstance(part, ast.Name):
                sql = self.module_strings.get(part.id, "")
            else:
                continue
            if re.search(r"\b(DELETE|TRUNCATE|UPDATE)\b", sql, re.I):
                return True
        return False

    def _table_likely_non_empty(self, model: Any = None) -> bool:
        """Heuristic: anything after 0001_initial → assume the table has rows.

        Except a table this same migration created, and anything in a
        squashed migration, which only runs on a fresh database.
        """
        if self.is_squashed:
            return False
        if isinstance(model, str) and model.lower() in self.created_models:
            return False
        return self.migration_index > 0

    def _model_field_names(self, model_lower: str) -> set | None:
        app_schema = self.current_schema.get(self.app)
        if not app_schema:
            return None
        return app_schema.get(model_lower)

    # ------------------------------------------------------------------
    # Rule 1 + 7: AddField risks
    # ------------------------------------------------------------------
    def _check_AddField(self, call: ast.Call) -> None:
        model = _kwarg_literal(call, "model_name")
        name = _kwarg_literal(call, "name")
        field_node = _get_kwarg(call, "field")
        field_call = _field_call(field_node)
        if field_call is None:
            return

        null_val = _kwarg_literal(field_call, "null")
        has_default = _has_kwarg(field_call, "default")
        unique_val = _kwarg_literal(field_call, "unique")
        field_type = _field_type(field_call) or "Field"
        if field_type in _NO_COLUMN_FIELDS:
            # M2M and generic relations add a join table or nothing at all,
            # never a column on this table.
            return
        populated = self._table_likely_non_empty(model)

        # Rule 1: NOT NULL with no default on a populated table.
        # ``null=True`` explicit means nullable → no risk.
        # No null kwarg means default False (NOT NULL) → risk if no default and
        # the table already exists.
        is_not_null = null_val is False or null_val is None
        if (
            is_not_null
            and not has_default
            and not _has_effective_default(field_call, field_type)
            and populated
            and field_type not in ("AutoField", "BigAutoField", "SmallAutoField")
        ):
            description = (
                f"Adds NOT NULL column '{name}' to '{model}' without a "
                f"default; existing rows will raise IntegrityError."
            )
            nn_confidence, nn_severity = "high", "critical"
            if self.data_op_before:
                # A RunPython, or a RunSQL that deletes or updates rows, runs
                # first. It may empty or backfill the table; say so instead of
                # calling it certain.
                description += (
                    " A data operation runs earlier in this migration; if it "
                    "empties the table, this is safe."
                )
                nn_confidence, nn_severity = "medium", "warning"
            self._add(
                call,
                "AddField",
                rule="add_field_not_null_no_default",
                description=description,
                mitigation=(
                    "Add null=True first, backfill via RunPython, then a "
                    "third migration to set null=False. Or provide default=."
                ),
                confidence=nn_confidence,
                severity=nn_severity,
                model=model,
                field=name,
            )

        # Rule 7: unique=True on a populated table without a per-row default.
        # A nullable column with no default (or default=None) fills existing
        # rows with NULL, and NULLs never collide in a unique constraint, so
        # that form is safe.
        default_node = _get_kwarg(field_call, "default")
        default_is_none = (
            isinstance(default_node, ast.Constant) and default_node.value is None
        )
        nulls_fill_rows = null_val is True and (not has_default or default_is_none)
        if unique_val is True and populated and not nulls_fill_rows:
            default_node = _get_kwarg(field_call, "default")
            # A callable default (e.g. ``default=uuid.uuid4``) can produce
            # unique values per row → medium. Anything else (literal or
            # missing) will fail on duplicates → high.
            default_is_callable = isinstance(default_node, (ast.Name, ast.Attribute))
            if default_is_callable:
                confidence: Confidence = "medium"
                severity: Severity = "warning"
                desc = (
                    f"Adds UNIQUE column '{name}' to '{model}' with a callable "
                    f"default; verify it produces unique values per row."
                )
            else:
                confidence = "high"
                severity = "critical"
                desc = (
                    f"Adds UNIQUE column '{name}' to '{model}' without a "
                    f"per-row default; existing duplicates will fail the "
                    f"constraint."
                )
            self._add(
                call,
                "AddField",
                rule="add_field_unique_no_row_default",
                description=desc,
                mitigation=(
                    "Add the column nullable first, populate unique values "
                    "via data migration, then apply the unique constraint."
                ),
                confidence=confidence,
                severity=severity,
                model=model,
                field=name,
            )

    # ------------------------------------------------------------------
    # Rule 2a: RemoveField still referenced in current models.py
    # ------------------------------------------------------------------
    def _check_RemoveField(self, call: ast.Call) -> None:
        model = _kwarg_literal(call, "model_name")
        name = _kwarg_literal(call, "name")
        model_lower = (model or "").lower()
        fields = self._model_field_names(model_lower)
        if fields is not None and name in fields:
            self._add(
                call,
                "RemoveField",
                rule="remove_field_still_referenced",
                description=(
                    f"Removes field '{name}' from '{model}' but a field with "
                    f"the same name still exists in the current models.py."
                ),
                mitigation=(
                    "Confirm no code path still reads/writes the field. "
                    "Deploy the code change first, then run this migration."
                ),
                confidence="high",
                severity="critical",
                model=model,
                field=name,
            )
        else:
            # Schema unknown or field genuinely gone. Still info-flag it so
            # reviewers see removed columns at a glance.
            if fields is None:
                self._add(
                    call,
                    "RemoveField",
                    rule="remove_field_unverified",
                    description=(
                        f"Removes field '{name}' from '{model}'. Could not "
                        f"cross-reference current models.py."
                    ),
                    mitigation=(
                        "Manually confirm no code paths still access "
                        f"'{model}.{name}'."
                    ),
                    confidence="low",
                    severity="info",
                    model=model,
                    field=name,
                )
            else:
                # The normal post-``makemigrations`` state. Emitting a risk
                # here is also what makes blast_radius scan for code that
                # still reads the dropped column.
                self._add(
                    call,
                    "RemoveField",
                    rule="remove_field",
                    description=(
                        f"Removes field '{name}' from '{model}'; it is no "
                        f"longer in the current models.py."
                    ),
                    mitigation=(
                        "Confirm no queries, serializers or templates still "
                        f"reference '{model}.{name}'."
                    ),
                    confidence="high",
                    severity="info",
                    model=model,
                    field=name,
                )

    # ------------------------------------------------------------------
    # Rule 2b: DeleteModel still referenced
    # ------------------------------------------------------------------
    def _check_DeleteModel(self, call: ast.Call) -> None:
        model = _kwarg_literal(call, "name")
        model_lower = (model or "").lower()
        fields = self._model_field_names(model_lower)
        if fields is not None:
            self._add(
                call,
                "DeleteModel",
                rule="delete_model_still_referenced",
                description=(
                    f"Deletes model '{model}' but a class with the same name "
                    f"is still defined in models.py."
                ),
                mitigation=(
                    "Remove the model class from models.py in a prior "
                    "deploy, or drop this operation."
                ),
                confidence="high",
                severity="critical",
                model=model,
            )
        else:
            self._add(
                call,
                "DeleteModel",
                rule="delete_model_unverified",
                description=(
                    f"Deletes model '{model}'. Could not cross-reference "
                    f"current models.py."
                ),
                mitigation=(
                    f"Manually confirm no code paths still import/query "
                    f"'{model}'."
                ),
                confidence="low",
                severity="info",
                model=model,
            )

    # ------------------------------------------------------------------
    # Rule 3: Renames break rolling deploys
    # ------------------------------------------------------------------
    def _check_RenameField(self, call: ast.Call) -> None:
        model = _kwarg_literal(call, "model_name")
        old = _kwarg_literal(call, "old_name")
        new = _kwarg_literal(call, "new_name")
        self._add(
            call,
            "RenameField",
            rule="rename_field_rolling_deploy",
            description=(
                f"Renames '{model}.{old}' -> '{new}'. Old app instances "
                f"during a rolling deploy will query the old column and fail."
            ),
            mitigation=(
                "Use a 3-step migration: add new column, dual-write and "
                "backfill, then drop the old column after all instances "
                "have restarted."
            ),
            confidence="medium",
            severity="warning",
            model=model,
            field=new or old,
            old_name=old,
        )

    def _check_RenameModel(self, call: ast.Call) -> None:
        old = _kwarg_literal(call, "old_name")
        new = _kwarg_literal(call, "new_name")
        self._add(
            call,
            "RenameModel",
            rule="rename_model_rolling_deploy",
            description=(
                f"Renames model '{old}' -> '{new}'. Old app instances during "
                f"a rolling deploy will query the old table and fail."
            ),
            mitigation=(
                "Use db_table on the new model to keep the same table name, "
                "or stage rename via new model + data copy + old model drop."
            ),
            confidence="medium",
            severity="warning",
            model=new or old,
            old_name=old,
        )

    # ------------------------------------------------------------------
    # Rule 4: AddIndex without CONCURRENTLY
    # ------------------------------------------------------------------
    def _check_AddIndex(self, call: ast.Call) -> None:
        model = _kwarg_literal(call, "model_name")
        if not self._table_likely_non_empty(model):
            return
        self._add(
            call,
            "AddIndex",
            rule="add_index_locks_table",
            description=(
                f"AddIndex on '{model}' takes a SHARE lock on Postgres for "
                f"the index build and, in an atomic migration, until the "
                f"enclosing transaction commits, blocking writes while reads continue."
            ),
            mitigation=(
                "Use AddIndexConcurrently (Django 3.0+) inside a non-atomic "
                "migration, or wrap CREATE INDEX CONCURRENTLY in RunSQL with "
                "SET LOCAL lock_timeout to bail early."
            ),
            confidence="medium",
            severity="warning",
            model=model,
        )

    # ------------------------------------------------------------------
    # Rule 5: AlterField type change
    # ------------------------------------------------------------------
    def _check_AlterField(self, call: ast.Call) -> None:
        model = _kwarg_literal(call, "model_name")
        name = _kwarg_literal(call, "name")
        field_node = _get_kwarg(call, "field")
        field_call = _field_call(field_node)
        if field_call is None:
            return
        field_type = _field_type(field_call) or ""
        max_len = _kwarg_literal(field_call, "max_length")

        # Narrowing a CharField is always high-confidence lossy.
        if field_type == "CharField" and isinstance(max_len, int):
            self._add(
                call,
                "AlterField",
                rule="alter_field_char_length",
                description=(
                    f"Alters '{model}.{name}' to CharField(max_length="
                    f"{max_len}); if this narrows the column, rows longer "
                    f"than {max_len} chars will fail; either way Postgres "
                    f"may rewrite the table under an ACCESS EXCLUSIVE lock."
                ),
                mitigation=(
                    "Verify no existing row exceeds the new length. Use "
                    "ALTER TABLE ... ALTER COLUMN ... TYPE with USING and "
                    "run out of hours if the table is large."
                ),
                confidence="medium",
                severity="warning",
                model=model,
                field=name,
            )
            return

        # Numeric widening / narrowing across integer types.
        int_widths = {
            "SmallIntegerField": 16,
            "IntegerField": 32,
            "BigIntegerField": 64,
            "PositiveSmallIntegerField": 16,
            "PositiveIntegerField": 32,
            "PositiveBigIntegerField": 64,
        }
        if field_type in int_widths:
            self._add(
                call,
                "AlterField",
                rule="alter_field_int_type",
                description=(
                    f"Alters '{model}.{name}' to {field_type}. A column "
                    f"type change on Postgres < 12 rewrites the whole table "
                    f"under an ACCESS EXCLUSIVE lock."
                ),
                mitigation=(
                    "On PG12+ widening is metadata-only; narrowing still "
                    "rewrites. Stage via new column + backfill + swap for "
                    "large tables."
                ),
                confidence="medium",
                severity="warning",
                model=model,
                field=name,
            )

    # ------------------------------------------------------------------
    # Rule 6: RunSQL without reverse_sql
    # ------------------------------------------------------------------
    def _check_RunSQL(self, call: ast.Call) -> None:
        # positional args: (sql, reverse_sql=None, ...)
        reverse_node = _get_kwarg(call, "reverse_sql")
        has_reverse_positional = len(call.args) >= 2
        if reverse_node is None and not has_reverse_positional:
            self._add(
                call,
                "RunSQL",
                rule="runsql_no_reverse",
                description=(
                    "RunSQL without reverse_sql cannot be rolled back; "
                    "migrate zero-back will fail."
                ),
                mitigation=(
                    "Pass reverse_sql=... (or migrations.RunSQL.noop if the "
                    "operation is genuinely irreversible) so the migration "
                    "is reversible in CI/rollback."
                ),
                confidence="medium",
                severity="warning",
            )

    # ------------------------------------------------------------------
    # Rule: RunPython without reverse_code
    # ------------------------------------------------------------------
    def _check_RunPython(self, call: ast.Call) -> None:
        # Signature: RunPython(code, reverse_code=None, ...). A data
        # migration without a reverse makes ``migrate <app> zero`` /
        # rollback deploys fail at exactly the wrong moment.
        reverse_node = _get_kwarg(call, "reverse_code")
        has_reverse_positional = len(call.args) >= 2
        if reverse_node is None and not has_reverse_positional:
            self._add(
                call,
                "RunPython",
                rule="runpython_no_reverse",
                description=(
                    "RunPython without reverse_code cannot be rolled back; "
                    "migrating backwards past this data migration will fail."
                ),
                mitigation=(
                    "Pass reverse_code=migrations.RunPython.noop when the "
                    "forward step is safe to leave in place, or a real "
                    "inverse function when it is not."
                ),
                confidence="medium",
                severity="warning",
            )

    # ------------------------------------------------------------------
    # Rule: AlterUniqueTogether on a populated table
    # ------------------------------------------------------------------
    def _check_AlterUniqueTogether(self, call: ast.Call) -> None:
        if not self._table_likely_non_empty(_kwarg_literal(call, "name")):
            return
        # Removing the constraint is safe. Django's MigrationWriter emits the
        # cleared form as ``unique_together=set()`` (a Call node), hand-written
        # migrations use ``[]`` / ``()`` / ``{}`` literals — accept all four.
        ut_node = _get_kwarg(call, "unique_together")
        if isinstance(ut_node, (ast.Set, ast.List, ast.Tuple)) and not ut_node.elts:
            return
        if (
            isinstance(ut_node, ast.Call)
            and isinstance(ut_node.func, ast.Name)
            and ut_node.func.id == "set"
            and not ut_node.args
            and not ut_node.keywords
        ):
            return
        model = _kwarg_literal(call, "name")
        self._add(
            call,
            "AlterUniqueTogether",
            rule="alter_unique_together_lock",
            description=(
                f"AlterUniqueTogether on '{model}' builds and validates a "
                f"unique index under an ACCESS EXCLUSIVE lock; existing "
                f"duplicate rows make the migration fail mid-deploy."
            ),
            mitigation=(
                "Deduplicate rows first, then prefer "
                "AddConstraint(UniqueConstraint) — on Postgres create the "
                "unique index CONCURRENTLY (RunSQL + SeparateDatabaseAndState) "
                "for large tables. unique_together is soft-deprecated in "
                "favour of UniqueConstraint."
            ),
            confidence="medium",
            severity="warning",
            model=model,
        )

    # ------------------------------------------------------------------
    # Rule: AlterIndexTogether is removed in Django 5.1
    # ------------------------------------------------------------------
    def _check_AlterIndexTogether(self, call: ast.Call) -> None:
        model = _kwarg_literal(call, "name")
        self._add(
            call,
            "AlterIndexTogether",
            rule="alter_index_together_deprecated",
            description=(
                f"AlterIndexTogether on '{model}' uses index_together, "
                f"deprecated since Django 4.2 and removed in 5.1 — this "
                f"migration will not run on modern Django."
            ),
            mitigation=(
                "Squash or rewrite the operation as Meta.indexes with "
                "AddIndex / RenameIndex (see the Django 4.2 release notes "
                "migration path)."
            ),
            confidence="high",
            severity="info",
            model=model,
        )

    # ------------------------------------------------------------------
    # No-op stubs so dispatch never AttributeErrors on known ops.
    # CreateModel introduces a brand-new (empty) table, and
    # AddIndexConcurrently / RemoveIndex are the *safe* variants — none of
    # them warrants a finding.
    # ------------------------------------------------------------------
    def _check_CreateModel(self, call: ast.Call) -> None:
        return

    def _check_AddIndexConcurrently(self, call: ast.Call) -> None:
        return

    def _check_RemoveIndex(self, call: ast.Call) -> None:
        return


def _reintroduced_later(
    idx: int,
    finding: MigrationRisk,
    introduced: list[tuple[int, int, str, str | None]],
) -> bool:
    """True when a still-referenced finding is undone later in the history.

    ``remove_field_still_referenced`` / ``delete_model_still_referenced``
    compare a historical RemoveField / DeleteModel against today's models.py.
    The name is legitimately still there when a later operation brought it
    back: an AddField or a RenameField onto the same name, or a CreateModel
    of the same model, in the same file or any later migration of the app.
    """
    if finding.rule not in ("remove_field_still_referenced", "delete_model_still_referenced"):
        return False
    model = (finding.model or "").lower()
    here = (idx, finding.line_number)
    for i2, line2, m2, f2 in introduced:
        if (i2, line2) <= here or m2 != model:
            continue
        if finding.rule == "delete_model_still_referenced" and f2 is None:
            return True
        if finding.rule == "remove_field_still_referenced" and f2 in (None, finding.field):
            return True
    return False


def analyze_migration_risks(
    project_root: str,
    current_schema: dict[str, dict[str, set]] | None = None,
) -> list[MigrationRisk]:
    """Walk every ``<app>/migrations/*.py`` under ``project_root`` and return
    all flagged risks.

    :param project_root: workspace root to scan.
    :param current_schema: optional pre-built schema
        ``{app: {model_lower: {field_names}}}``. When ``None``, we call
        :func:`_build_current_schema` which invokes ``scan_workspace`` from
        :mod:`.parser`. Pass an empty dict to explicitly skip cross-reference
        rules.
    :returns: sorted list of :class:`MigrationRisk`.
    """
    if current_schema is None:
        current_schema = _build_current_schema(project_root)

    findings: list[MigrationRisk] = []
    apps = _find_all_migration_apps(project_root)

    # Group by app so we know each migration's numeric index within its app.
    by_app: dict[str, list[tuple[Path, list[Path]]]] = {}
    for app_label, mig_dir in apps:
        files = _iter_migration_files(mig_dir)
        by_app.setdefault(app_label, []).append((mig_dir, files))

    for app_label, dirs in by_app.items():
        # Flatten + dedupe by filename (mono-repos may vendor the same app).
        seen: set = set()
        ordered_files: list[Path] = []
        for _mig_dir, files in dirs:
            for f in files:
                if f.name in seen:
                    continue
                seen.add(f.name)
                ordered_files.append(f)
        ordered_files.sort(key=lambda p: (_migration_prefix(p.stem), p.name))

        app_findings: list[tuple[int, MigrationRisk]] = []
        # (migration index, line, model, field-or-None) for every operation in
        # the app that brings a name (back) into existence.
        introduced: list[tuple[int, int, str, str | None]] = []
        for idx, path in enumerate(ordered_files):
            analyzer = MigrationRiskAnalyzer(
                file_path=path,
                app=app_label,
                migration_name=path.stem,
                migration_index=idx,
                current_schema=current_schema,
            )
            app_findings.extend((idx, f) for f in analyzer.analyze())
            introduced.extend((idx, line, m, fl) for line, m, fl in analyzer.introduced)
        findings.extend(
            f for idx, f in app_findings if not _reintroduced_later(idx, f, introduced)
        )

        # Graph-level rule, so it lives here rather than in the per-file
        # analyzer: Django refuses to run an app whose migration graph has more
        # than one leaf, with "Conflicting migrations detected; multiple leaf
        # nodes in the migration graph". It happens whenever two branches each
        # add a migration on the same parent and both get merged.
        #
        # Catching it statically is the point: `makemigrations --merge` only
        # reports this once you have a working settings module and database,
        # which is exactly what nobody has on a fresh clone or in a CI job that
        # has not booted Django yet.
        parsed = [m for m in (_parse_migration_file(p) for p in ordered_files) if m]
        if len(parsed) > 1:
            # `app_label` comes from the directory name, but Django lets an app
            # declare `AppConfig.label` different from its package — and the
            # dependency tuples use the *label*. Leafness computed against the
            # wrong label sees no in-app edges at all and calls every migration
            # a leaf, which would report a critical conflict for a perfectly
            # linear history.
            #
            # Recover the real label: whichever label appears in a dependency
            # pointing at a migration file that exists in this directory. If
            # that is ambiguous, or nothing references us, stay silent — a
            # false "your migrations conflict" is worse than a missed one.
            local_names = {m["name"] for m in parsed}
            candidates = {
                dep[0]
                for m in parsed
                for dep in m["dependencies"]
                if dep[1] in local_names
            }
            effective_label = (
                app_label
                if app_label in candidates
                else next(iter(candidates))
                if len(candidates) == 1
                else None
            )
            leaves = (
                _compute_roots_leaves_cross(
                    _collapse_squashed(parsed, effective_label), effective_label
                )[1]
                if effective_label
                else []
            )
            if len(leaves) > 1:
                by_name = {p.stem: p for p in ordered_files}
                others = sorted(leaves)
                for leaf in others:
                    rest = [n for n in others if n != leaf]
                    leaf_path = by_name.get(leaf)
                    findings.append(
                        MigrationRisk(
                            file_path=str(leaf_path) if leaf_path else "",
                            line_number=1,
                            app=app_label,
                            migration=leaf,
                            operation="(migration graph)",
                            model=None,
                            field=None,
                            rule="conflicting_migration_leaves",
                            description=(
                                f"App '{app_label}' has {len(others)} leaf migrations "
                                f"({', '.join(others)}). Django will refuse to migrate "
                                f"this app: 'Conflicting migrations detected; multiple "
                                f"leaf nodes in the migration graph'. This one conflicts "
                                f"with {', '.join(rest)}."
                            ),
                            mitigation=(
                                "Run `python manage.py makemigrations --merge` to "
                                "generate a merge migration that depends on every leaf. "
                                "If the branches touched the same table, review the "
                                "merged result by hand before applying it."
                            ),
                            confidence="high",
                            severity="critical",
                        )
                    )

    # Deterministic order for consumers (formatters, CI diff, tests).
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(
        key=lambda r: (
            severity_order.get(r.severity, 99),
            r.app,
            r.migration,
            r.line_number,
            r.rule,
        )
    )
    return findings
