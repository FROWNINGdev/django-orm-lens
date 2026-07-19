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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    model: Optional[str]
    field: Optional[str]
    rule: str
    description: str
    mitigation: str
    confidence: Confidence
    severity: Severity

    def to_dict(self) -> Dict[str, Any]:
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


def _get_kwarg(call: ast.Call, name: str) -> Optional[ast.AST]:
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


def _call_op_name(call: ast.Call) -> Optional[str]:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _field_call(node: Optional[ast.AST]) -> Optional[ast.Call]:
    """Return the underlying field constructor Call node, if any.

    ``AddField(field=models.CharField(max_length=10))`` — we want the
    ``models.CharField(...)`` Call.
    """
    if isinstance(node, ast.Call):
        return node
    return None


def _field_type(call: ast.Call) -> Optional[str]:
    """Return the constructor name of a field call (e.g. ``CharField``)."""
    return _call_op_name(call)


def _migration_prefix(name: str) -> int:
    """Return the numeric prefix of a migration filename stem, or -1."""
    m = _MIGRATION_PREFIX_RE.match(name)
    if not m:
        return -1
    try:
        return int(m.group(1))
    except ValueError:
        return -1


def _find_all_migration_apps(project_root: str) -> List[Tuple[str, Path]]:
    """Walk ``project_root`` and yield ``(app_label, migrations_dir)`` pairs.

    Skips hidden, virtualenv-ish, and vendored trees.
    """
    out: List[Tuple[str, Path]] = []
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


def _build_current_schema(project_root: str) -> Dict[str, Dict[str, set]]:
    """Return ``{app_name: {model_name_lower: {field_names}}}`` from parser.

    Failures are swallowed — cross-reference rule is best-effort.
    """
    try:
        from .parser import scan_workspace  # local import to avoid cycles
    except Exception:
        return {}
    schema: Dict[str, Dict[str, set]] = {}
    try:
        index = scan_workspace(project_root)
    except Exception:
        return schema
    for app in index.apps:
        app_map = schema.setdefault(app.name, {})
        for model in app.models:
            app_map[model.name.lower()] = {f.name for f in model.fields}
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
        current_schema: Optional[Dict[str, Dict[str, set]]] = None,
    ) -> None:
        self.file_path = file_path
        self.app = app
        self.migration_name = migration_name
        # 0 == first migration in the app (0001_initial). Any value > 0 is
        # our heuristic that the table is already populated in production.
        self.migration_index = migration_index
        self.current_schema = current_schema or {}
        self.findings: List[MigrationRisk] = []

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------
    def analyze(self) -> List[MigrationRisk]:
        try:
            source = self.file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        try:
            tree = ast.parse(source, filename=str(self.file_path))
        except SyntaxError:
            return []

        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name != "Migration":
                continue
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign):
                    continue
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
            handler = getattr(self, f"_check_{op}", None)
            if handler is not None:
                try:
                    handler(elt)
                except Exception:
                    # Never let a single malformed op sink the run.
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
        model: Optional[str] = None,
        field: Optional[str] = None,
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
            )
        )

    def _table_likely_non_empty(self) -> bool:
        """Heuristic: anything after 0001_initial → assume the table has rows."""
        return self.migration_index > 0

    def _model_field_names(self, model_lower: str) -> Optional[set]:
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

        # Rule 1: NOT NULL with no default on a populated table.
        # ``null=True`` explicit means nullable → no risk.
        # No null kwarg means default False (NOT NULL) → risk if no default and
        # the table already exists.
        is_not_null = null_val is False or null_val is None
        if (
            is_not_null
            and not has_default
            and self._table_likely_non_empty()
            and field_type not in ("AutoField", "BigAutoField", "SmallAutoField")
        ):
            self._add(
                call,
                "AddField",
                rule="add_field_not_null_no_default",
                description=(
                    f"Adds NOT NULL column '{name}' to '{model}' without a "
                    f"default; existing rows will raise IntegrityError."
                ),
                mitigation=(
                    "Add null=True first, backfill via RunPython, then a "
                    "third migration to set null=False. Or provide default=."
                ),
                confidence="high",
                severity="critical",
                model=model,
                field=name,
            )

        # Rule 7: unique=True on a populated table without a per-row default.
        if unique_val is True and self._table_likely_non_empty():
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
        )

    # ------------------------------------------------------------------
    # Rule 4: AddIndex without CONCURRENTLY
    # ------------------------------------------------------------------
    def _check_AddIndex(self, call: ast.Call) -> None:
        if not self._table_likely_non_empty():
            return
        model = _kwarg_literal(call, "model_name")
        self._add(
            call,
            "AddIndex",
            rule="add_index_locks_table",
            description=(
                f"AddIndex on '{model}' takes an ACCESS EXCLUSIVE lock on "
                f"Postgres for the duration of the build, blocking writes."
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
    # No-op stubs so dispatch never AttributeErrors on known ops.
    # ------------------------------------------------------------------
    def _check_CreateModel(self, call: ast.Call) -> None:
        return

    def _check_AddIndexConcurrently(self, call: ast.Call) -> None:
        return

    def _check_RemoveIndex(self, call: ast.Call) -> None:
        return

    def _check_RunPython(self, call: ast.Call) -> None:
        return

    def _check_AlterUniqueTogether(self, call: ast.Call) -> None:
        return

    def _check_AlterIndexTogether(self, call: ast.Call) -> None:
        return


def analyze_migration_risks(
    project_root: str,
    current_schema: Optional[Dict[str, Dict[str, set]]] = None,
) -> List[MigrationRisk]:
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

    findings: List[MigrationRisk] = []
    apps = _find_all_migration_apps(project_root)

    # Group by app so we know each migration's numeric index within its app.
    by_app: Dict[str, List[Tuple[Path, List[Path]]]] = {}
    for app_label, mig_dir in apps:
        files = _iter_migration_files(mig_dir)
        by_app.setdefault(app_label, []).append((mig_dir, files))

    for app_label, dirs in by_app.items():
        # Flatten + dedupe by filename (mono-repos may vendor the same app).
        seen: set = set()
        ordered_files: List[Path] = []
        for _mig_dir, files in dirs:
            for f in files:
                if f.name in seen:
                    continue
                seen.add(f.name)
                ordered_files.append(f)
        ordered_files.sort(key=lambda p: (_migration_prefix(p.stem), p.name))

        for idx, path in enumerate(ordered_files):
            analyzer = MigrationRiskAnalyzer(
                file_path=path,
                app=app_label,
                migration_name=path.stem,
                migration_index=idx,
                current_schema=current_schema,
            )
            findings.extend(analyzer.analyze())

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
