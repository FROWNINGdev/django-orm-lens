"""Static migration-risk checks for Alembic revisions (SQLAlchemy, FastAPI, Flask).

Same contract as the Django analyzer in :mod:`.migrations_parser`: revision files
are read with ``ast``, never imported or run, no database is touched, and every
finding is a :class:`~.migrations_parser.MigrationRisk`, so the text, JSON,
SARIF and GitHub formatters work unchanged.

The rules target what breaks or blocks on a table that already has rows, the
way production databases do (PostgreSQL semantics where engines differ):

* ``add_column`` NOT NULL without ``server_default``: SQLAlchemy's ``default=``
  is applied by the ORM on INSERT only, so existing rows get NULL and the ALTER
  fails.
* ``create_index`` without ``postgresql_concurrently=True`` blocks writes for
  the whole build.
* ``alter_column`` to NOT NULL scans the table under an exclusive lock and fails
  on any NULL; a type change usually rewrites the table.
* renames and dropped columns break the code still running during a deploy.
* unique / foreign-key / check constraints validate every row while locked.
* more than one head makes ``alembic upgrade head`` refuse to run.

Precision rules, learned from the Django analyzer's real-world census: a table
created earlier in the same revision is empty, the base revision runs on an
empty database, and a data operation before a NOT NULL column may have emptied
or backfilled the table (reported as a warning, not a certain critical).
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

from .migrations_parser import MigrationRisk

_SKIP_DIRS = frozenset(
    {"node_modules", "venv", ".venv", "env", ".git", "__pycache__", "site-packages", "dist", "build"}
)
_REVISION_RE = re.compile(r"^\s*revision\s*(?::[^=\n]+)?=\s*['\"]", re.M)
_DATA_SQL_RE = re.compile(r"\b(DELETE|TRUNCATE|UPDATE|INSERT)\b", re.I)


def _iter_revision_files(root: Path) -> list[Path]:
    """Every ``.py`` under a ``versions`` directory that declares a revision.

    Walks its own tree: the shared workspace walk skips ``migrations/``, which
    is exactly where Flask-Migrate keeps ``migrations/versions/``. Revisions may
    also sit one level deeper (``versions/postgresql/``).
    """
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]
        parts = Path(dirpath).parts
        if "versions" not in parts:
            continue
        for name in filenames:
            if not name.endswith(".py") or name == "__init__.py":
                continue
            path = Path(dirpath) / name
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _REVISION_RE.search(source) and "def upgrade" in source:
                out.append(path)
    return sorted(out)


def _literal(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, RecursionError):
        return None


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _arg(call: ast.Call, index: int, name: str) -> ast.AST | None:
    """Positional ``index`` or keyword ``name``, whichever the call used."""
    value = _kw(call, name)
    if value is not None:
        return value
    return call.args[index] if len(call.args) > index else None


def _name_of(node: ast.AST | None) -> str | None:
    """A table or column name: a string literal, or ``op.f("...")``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and node.args:
        return _name_of(node.args[0])
    return None


def _module_assignments(tree: ast.Module) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            out[node.target.id] = node.value
    return out


def _revision_ids(node: ast.AST | None) -> list[str]:
    value = _literal(node)
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str)]
    return []


class _RevisionAnalyzer:
    """Walk one revision's ``upgrade()`` in source order and record risks."""

    def __init__(self, path: Path, revision: str, is_base: bool, strings: dict[str, str]) -> None:
        self.path = path
        self.revision = revision
        self.is_base = is_base
        self.strings = strings
        self.created: set[str] = set()
        self.data_op_before = False
        self.findings: list[MigrationRisk] = []

    # -- recording --------------------------------------------------------
    def _add(
        self,
        call: ast.Call,
        operation: str,
        rule: str,
        table: str | None,
        column: str | None,
        description: str,
        mitigation: str,
        severity: str = "warning",
        confidence: str = "medium",
        old_name: str | None = None,
    ) -> None:
        self.findings.append(
            MigrationRisk(
                file_path=str(self.path),
                line_number=getattr(call, "lineno", 0),
                app="alembic",
                migration=self.path.stem,
                operation=operation,
                model=table,
                field=column,
                rule=rule,
                description=description,
                mitigation=mitigation,
                confidence=confidence,
                severity=severity,
                old_name=old_name,
            )
        )

    def _populated(self, table: str | None) -> bool:
        if self.is_base:
            return False
        return not (table and table in self.created)

    # -- walking ----------------------------------------------------------
    def walk(self, body: list[ast.stmt], batch_table: str | None = None, batch_alias: str | None = None) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.With, ast.AsyncWith)):
                table, alias = batch_table, batch_alias
                for item in stmt.items:
                    expr = item.context_expr
                    if (
                        isinstance(expr, ast.Call)
                        and isinstance(expr.func, ast.Attribute)
                        and expr.func.attr == "batch_alter_table"
                    ):
                        table = _name_of(_arg(expr, 0, "table_name"))
                        if isinstance(item.optional_vars, ast.Name):
                            alias = item.optional_vars.id
                self.walk(stmt.body, table, alias)
                continue
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for node in self._calls_in_order(stmt):
                self._dispatch(node, batch_table, batch_alias)
            for child in ("body", "orelse", "finalbody"):
                nested = getattr(stmt, child, None)
                if isinstance(nested, list) and nested:
                    self.walk(nested, batch_table, batch_alias)
            for handler in getattr(stmt, "handlers", []) or []:
                self.walk(handler.body, batch_table, batch_alias)

    @staticmethod
    def _calls_in_order(stmt: ast.stmt) -> list[ast.Call]:
        """Calls in this statement itself, not in nested blocks, in source order."""
        if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try)):
            heads: list[ast.AST] = []
            for field in ("test", "iter"):
                value = getattr(stmt, field, None)
                if value is not None:
                    heads.append(value)
            nodes = [n for h in heads for n in ast.walk(h)]
        else:
            nodes = list(ast.walk(stmt))
        calls = [n for n in nodes if isinstance(n, ast.Call)]
        return sorted(calls, key=lambda c: (getattr(c, "lineno", 0), getattr(c, "col_offset", 0)))

    def _dispatch(self, call: ast.Call, batch_table: str | None, batch_alias: str | None) -> None:
        func = call.func
        if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
            return
        receiver, op = func.value.id, func.attr
        in_batch = batch_alias is not None and receiver == batch_alias
        if receiver != "op" and not in_batch:
            # A connection obtained from op.get_bind() running SQL is data work.
            if op in ("execute", "exec_driver_sql"):
                self.data_op_before = True
            return
        if op == "create_table":
            name = _name_of(_arg(call, 0, "table_name"))
            if name:
                self.created.add(name)
            return
        if op in ("execute", "bulk_insert"):
            if op == "bulk_insert" or self._sql_changes_rows(_arg(call, 0, "sqltext")):
                self.data_op_before = True
            return
        handler = getattr(self, f"_check_{op}", None)
        if handler is not None:
            # Batch operations omit the table argument; the with-block names it.
            handler(call, batch_table if in_batch else None)

    def _sql_changes_rows(self, node: ast.AST | None) -> bool:
        if isinstance(node, ast.Call):
            # sa.text("..."), table.update(), table.delete(), table.insert()
            if isinstance(node.func, ast.Attribute) and node.func.attr in ("update", "delete", "insert"):
                return True
            return any(self._sql_changes_rows(a) for a in node.args)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return bool(_DATA_SQL_RE.search(node.value))
        if isinstance(node, ast.Name):
            return bool(_DATA_SQL_RE.search(self.strings.get(node.id, "")))
        if isinstance(node, ast.JoinedStr):
            return bool(_DATA_SQL_RE.search(ast.unparse(node)))
        return False

    def _table(self, call: ast.Call, batch_table: str | None, index: int = 0, name: str = "table_name") -> str | None:
        if batch_table is not None:
            return batch_table
        return _name_of(_arg(call, index, name))

    # -- rules ------------------------------------------------------------
    def _check_add_column(self, call: ast.Call, batch_table: str | None) -> None:
        table = self._table(call, batch_table)
        column = _arg(call, 0 if batch_table else 1, "column")
        if not isinstance(column, ast.Call):
            return
        col_name = _name_of(column.args[0]) if column.args else _name_of(_kw(column, "name"))
        nullable = _literal(_kw(column, "nullable"))
        primary_key = _literal(_kw(column, "primary_key")) is True
        not_null = nullable is False or (primary_key and nullable is not True)
        if not not_null or _kw(column, "server_default") is not None:
            return
        # A generated or identity column is filled by the database.
        for extra in column.args[1:]:
            if isinstance(extra, ast.Call) and isinstance(extra.func, (ast.Attribute, ast.Name)):
                fname = extra.func.attr if isinstance(extra.func, ast.Attribute) else extra.func.id
                if fname in ("Computed", "Identity"):
                    return
        if not self._populated(table):
            return
        has_python_default = _kw(column, "default") is not None
        description = (
            f"Adds NOT NULL column '{col_name}' to '{table}' without server_default; "
            f"existing rows get NULL and the ALTER fails."
        )
        if has_python_default:
            description += " default= is applied by SQLAlchemy on INSERT only and does not fill existing rows."
        severity, confidence = "critical", "high"
        if self.data_op_before:
            description += " A data operation runs earlier in this revision; if it empties the table, this is safe."
            severity, confidence = "warning", "medium"
        self._add(
            call, "add_column", "alembic_add_column_not_null_no_server_default", table, col_name,
            description,
            "Add the column nullable, backfill it, then alter_column(nullable=False) in a later "
            "revision. Or give it a server_default.",
            severity, confidence,
        )

    def _check_create_index(self, call: ast.Call, batch_table: str | None) -> None:
        table = self._table(call, batch_table, 1, "table_name")
        if not self._populated(table):
            return
        if _literal(_kw(call, "postgresql_concurrently")) is True:
            return
        name = _name_of(_arg(call, 0, "index_name"))
        unique = _literal(_kw(call, "unique")) is True
        self._add(
            call, "create_index", "alembic_create_index_locks_table", table, None,
            f"Builds {'unique ' if unique else ''}index '{name}' on '{table}' without CONCURRENTLY; "
            f"PostgreSQL blocks writes to the table for the whole build.",
            "On PostgreSQL pass postgresql_concurrently=True inside "
            "op.get_context().autocommit_block().",
        )

    def _check_alter_column(self, call: ast.Call, batch_table: str | None) -> None:
        table = self._table(call, batch_table)
        column = _name_of(_arg(call, 0 if batch_table else 1, "column_name"))
        if not self._populated(table):
            return
        new_name = _name_of(_kw(call, "new_column_name"))
        if new_name:
            self._add(
                call, "alter_column", "alembic_rename_column_breaks_running_code", table, new_name,
                f"Renames '{table}.{column}' to '{new_name}'; code still running from the previous "
                f"release keeps using the old name until it is replaced.",
                "Add the new column, write to both, backfill, switch reads, then drop the old one.",
                old_name=column,
            )
        if _literal(_kw(call, "nullable")) is False and _kw(call, "server_default") is None:
            self._add(
                call, "alter_column", "alembic_set_not_null_scans_table", table, column,
                f"Sets '{table}.{column}' NOT NULL: PostgreSQL scans the whole table under an exclusive "
                f"lock, and the ALTER fails if any row is still NULL.",
                "Backfill first. On large tables add CHECK (col IS NOT NULL) NOT VALID, VALIDATE it, "
                "then set NOT NULL.",
            )
        if _kw(call, "type_") is not None:
            self._add(
                call, "alter_column", "alembic_alter_column_type_rewrites", table, column,
                f"Changes the type of '{table}.{column}'; most type changes rewrite the table under an "
                f"exclusive lock.",
                "Add a column of the new type, backfill, switch reads, then drop the old column.",
            )

    def _check_drop_column(self, call: ast.Call, batch_table: str | None) -> None:
        table = self._table(call, batch_table)
        column = _name_of(_arg(call, 0 if batch_table else 1, "column_name"))
        if not self._populated(table):
            return
        self._add(
            call, "drop_column", "alembic_drop_column_breaks_running_code", table, column,
            f"Drops '{table}.{column}'; the previous release's models still select it until every "
            f"instance is replaced.",
            "Remove the column from the models and deploy first; drop it in a later release.",
        )

    def _check_drop_table(self, call: ast.Call, batch_table: str | None) -> None:
        table = self._table(call, batch_table)
        if not self._populated(table):
            return
        self._add(
            call, "drop_table", "alembic_drop_table_breaks_running_code", table, None,
            f"Drops table '{table}'; the previous release's models still query it, so every "
            f"remaining instance fails until it is replaced.",
            "Remove the table from the models and deploy first; drop it in a later release.",
        )

    def _check_rename_table(self, call: ast.Call, batch_table: str | None) -> None:
        old = _name_of(_arg(call, 0, "old_table_name"))
        new = _name_of(_arg(call, 1, "new_table_name"))
        if self.is_base:
            return
        self._add(
            call, "rename_table", "alembic_rename_table_breaks_running_code", new, None,
            f"Renames table '{old}' to '{new}'; code still running from the previous release keeps "
            f"querying '{old}'.",
            "Create the new table or a view under the new name, migrate readers, then drop the old one.",
            old_name=old,
        )

    def _check_create_unique_constraint(self, call: ast.Call, batch_table: str | None) -> None:
        table = self._table(call, batch_table, 1, "table_name")
        if not self._populated(table):
            return
        self._add(
            call, "create_unique_constraint", "alembic_add_unique_constraint_locks_and_may_fail", table, None,
            f"Adds a unique constraint on '{table}': the index is built while writes are blocked, and "
            f"existing duplicates make it fail.",
            "CREATE UNIQUE INDEX CONCURRENTLY first, then ADD CONSTRAINT ... USING INDEX.",
        )

    def _check_create_foreign_key(self, call: ast.Call, batch_table: str | None) -> None:
        table = self._table(call, batch_table, 1, "source_table")
        if not self._populated(table):
            return
        self._add(
            call, "create_foreign_key", "alembic_add_foreign_key_validates_rows", table, None,
            f"Adds a foreign key on '{table}': every existing row is checked while both tables are "
            f"locked against writes.",
            "Add it NOT VALID with op.execute, then VALIDATE CONSTRAINT in a separate step.",
        )

    def _check_create_check_constraint(self, call: ast.Call, batch_table: str | None) -> None:
        table = self._table(call, batch_table, 1, "table_name")
        if not self._populated(table):
            return
        self._add(
            call, "create_check_constraint", "alembic_add_check_constraint_validates_rows", table, None,
            f"Adds a check constraint on '{table}': every existing row is checked under an exclusive lock.",
            "Add it NOT VALID with op.execute, then VALIDATE CONSTRAINT in a separate step.",
        )


def _graph_findings(revisions: list[dict[str, Any]], directory: Path) -> list[MigrationRisk]:
    """``alembic upgrade head`` refuses to run while the graph has two heads."""
    if len(revisions) < 2:
        return []
    ids = {r["revision"] for r in revisions}
    referenced = {d for r in revisions for d in r["down"] if d in ids}
    heads = sorted((r for r in revisions if r["revision"] not in referenced), key=lambda r: r["path"].name)
    if len(heads) < 2:
        return []
    labelled = any(r["branch_labels"] for r in revisions)
    names = ", ".join(h["revision"] for h in heads)
    out = []
    for head in heads:
        out.append(
            MigrationRisk(
                file_path=str(head["path"]),
                line_number=1,
                app="alembic",
                migration=head["path"].stem,
                operation="(revision graph)",
                model=None,
                field=None,
                rule="alembic_multiple_heads",
                description=(
                    f"Revisions in {directory.name}/ have {len(heads)} heads ({names}); "
                    f"`alembic upgrade head` fails with 'Multiple head revisions are present'."
                    + (" Branch labels are in use, so this may be intended (upgrade heads)." if labelled else "")
                ),
                mitigation="Run `alembic merge heads -m merge` to add a revision that depends on every head.",
                confidence="medium" if labelled else "high",
                severity="warning" if labelled else "critical",
            )
        )
    return out


_HEADER_RE = re.compile(
    r"^(revision|down_revision|branch_labels)\s*(?::[^=\n]+)?=\s*(.+?)$", re.M
)
_QUOTED_RE = re.compile(r"['\"]([^'\"]+)['\"]")


def _header_by_regex(source: str) -> dict[str, Any] | None:
    """Revision header of a file ``ast`` cannot parse.

    A revision written for a newer Python than the one running the scan (for
    example PEP 758's unparenthesised ``except A, B:`` on 3.14) must still
    count in the revision graph, or its parent looks like a second head.
    Operations in such a file are not analyzed.
    """
    found = {name: value for name, value in _HEADER_RE.findall(source)}
    revision = _QUOTED_RE.findall(found.get("revision", ""))
    if not revision:
        return None
    down_raw = found.get("down_revision", "")
    if down_raw.strip().startswith("("):
        # A merge revision may wrap its tuple over several lines.
        start = source.find(down_raw)
        down_raw = source[start:source.find(")", start) + 1]
    return {
        "revision": revision[0],
        "down": _QUOTED_RE.findall(down_raw),
        "branch_labels": bool(_QUOTED_RE.findall(found.get("branch_labels", ""))),
    }


def analyze_alembic_risks(project_root: str) -> list[MigrationRisk]:
    """Walk every Alembic ``versions/`` directory under ``project_root``."""
    root = Path(project_root)
    findings: list[MigrationRisk] = []
    by_dir: dict[Path, list[dict[str, Any]]] = {}
    for path in _iter_revision_files(root):
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, ValueError):
            header = _header_by_regex(source)
            if header is not None:
                by_dir.setdefault(path.parent, []).append({**header, "path": path})
            continue
        assigns = _module_assignments(tree)
        revision = _literal(assigns.get("revision"))
        if not isinstance(revision, str):
            continue
        down = _revision_ids(assigns.get("down_revision"))
        strings = {
            name: value.value
            for name, value in assigns.items()
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        }
        upgrade = next(
            (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"),
            None,
        )
        if upgrade is not None:
            analyzer = _RevisionAnalyzer(path, revision, is_base=not down, strings=strings)
            analyzer.walk(upgrade.body)
            findings.extend(analyzer.findings)
        # One history per directory: Prefect keeps versions/postgresql/ and
        # versions/sqlite/ as two separate chains under one versions/.
        by_dir.setdefault(path.parent, []).append(
            {
                "revision": revision,
                "down": down,
                "path": path,
                "branch_labels": bool(_literal(assigns.get("branch_labels"))),
            }
        )
    for directory, revisions in by_dir.items():
        findings.extend(_graph_findings(revisions, directory))
    return findings
