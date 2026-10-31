"""SQLAlchemy declarative models — static parser, ``ast`` only.

Finds the mapped classes of a project without importing it or touching a
database. Recognised styles:

* SQLAlchemy 2.0: ``class Base(DeclarativeBase)``, ``Mapped[...]`` with or
  without ``mapped_column(...)``, ``Annotated`` type aliases.
* SQLAlchemy 1.x: ``Base = declarative_base()``, ``registry().generate_base()``,
  ``@as_declarative()``, ``@mapper_registry.mapped``, ``Column(...)``.
* Flask-SQLAlchemy ``db.Model`` and Flask-AppBuilder ``Model``, with their
  automatic snake_case table names.
* SQLModel classes declared with ``table=True``; non-table SQLModel parents
  only lend their fields.

Inheritance is resolved across files by class name (``Base`` defined in
``db/base.py`` and imported elsewhere): ``__abstract__`` classes, mixins and
the declarative base itself contribute columns to every mapped subclass;
a mapped parent is single-table inheritance when the child declares no
table and no primary key of its own, joined inheritance otherwise.

Each mapped class becomes a :class:`~orm_lens.models.ParsedModel`
with ``orm = "sqlalchemy"``. Columns are :class:`ParsedField`; a
``ForeignKey`` makes the column a relation (``relation_kind`` ``ForeignKey``,
or ``OneToOneField`` when the column is unique or the primary key), with
``related_model`` resolved from the target table to its class.
``relationship()`` attributes land in :attr:`ParsedModel.relationships`;
one with ``secondary=`` is also listed in ``fields`` as a
``ManyToManyField`` through the association table, the way a Django
many-to-many is.
"""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from .models import ParsedField, ParsedModel, ParsedRelationship

# Cheap textual gate before ``ast.parse``. Broad on purpose: a model file
# that imports its base from elsewhere still says ``__tablename__``,
# ``mapped_column`` or ``Column(``.
_PREFILTER_RE = re.compile(
    r"sqlalchemy|sqlmodel|mapped_column|Mapped\[|__tablename__|__table__"
    r"|__mapper_args__|declarative_base|DeclarativeBase|\bdb\.Model\b"
    r"|\bColumn\(|relationship\(|Relationship\("
)

# A file is SQLAlchemy code (as opposed to Django code that happens to
# mention ``Model``) when it imports one of these or uses their idioms.
_SA_SIGNAL_RE = re.compile(
    r"^[ \t]*(?:from|import)[ \t]+(?:sqlalchemy|sqlmodel|flask_sqlalchemy|flask_appbuilder)\b"
    r"|__tablename__|\bmapped_column\(|\bdb\.(?:Column|relationship|Model)\b",
    re.M,
)
_DJANGO_IMPORT_RE = re.compile(r"^[ \t]*(?:from|import)[ \t]+django\b", re.M)

_DECLARATIVE_ROOTS = frozenset({"DeclarativeBase", "DeclarativeBaseNoMeta"})
# Mixed into a declarative base without changing what it is.
_NEUTRAL_BASES = frozenset(
    {"AsyncAttrs", "MappedAsDataclass", "object", "Generic", "Protocol"}
)
_COLUMN_CALLS = frozenset({"mapped_column", "Column"})
_RELATIONSHIP_CALLS = frozenset({"relationship", "Relationship", "relation"})
# Wrappers whose first argument is the real column.
_COLUMN_WRAPPERS = frozenset({"deferred", "column_property"})
# Positional arguments of Column()/mapped_column() that are not its type.
_SCHEMA_ITEMS = frozenset(
    {
        "ForeignKey", "Sequence", "Identity", "Computed", "CheckConstraint",
        "Index", "FetchedValue", "DefaultClause", "UniqueConstraint",
        "text", "func",
    }
)
_PY_TYPES = {
    "int": "Integer",
    "str": "String",
    "bool": "Boolean",
    "float": "Float",
    "Decimal": "Numeric",
    "datetime": "DateTime",
    "date": "Date",
    "time": "Time",
    "timedelta": "Interval",
    "UUID": "Uuid",
    "bytes": "LargeBinary",
    "dict": "JSON",
    "Dict": "JSON",
    "list": "ARRAY",
    "List": "ARRAY",
    "EmailStr": "String",
    "HttpUrl": "String",
    "AnyUrl": "String",
    "AnyHttpUrl": "String",
}
_COLLECTION_TAILS = frozenset(
    {
        "list", "List", "set", "Set", "frozenset", "FrozenSet", "Sequence",
        "MutableSequence", "Collection", "Iterable", "AbstractSet",
        "MutableSet", "InstrumentedList", "tuple", "Tuple",
    }
)
_MAPPING_TAILS = frozenset({"dict", "Dict", "Mapping", "MutableMapping"})
_MAPPED_TAILS = {"Mapped": None, "WriteOnlyMapped": "write_only", "DynamicMapped": "dynamic"}
_LAZY_BOOL = {True: "select", False: "joined"}

#: Directory names never walked for models, on top of the shared skip list.
_SKIP_DIRS = frozenset({"site-packages", "dist", "build", "eggs"})


_DEP_FILE_RE = re.compile(
    r"^(?:pyproject\.toml|setup\.py|setup\.cfg|Pipfile|requirements[\w.-]*\.(?:txt|in))$"
)
_DEP_NAME_RE = re.compile(
    r"(?i)\b(?:sqlalchemy|sqlmodel|flask[-_]sqlalchemy|flask[-_]appbuilder)\b"
)


def declares_sqlalchemy(root: Path | str, depth: int = 2) -> bool:
    """True when the project says it uses SQLAlchemy.

    An ``alembic.ini``, or a dependency file (``pyproject.toml``,
    ``requirements*.txt``, ``setup.py``, ``setup.cfg``, ``Pipfile``) naming
    SQLAlchemy, SQLModel, Flask-SQLAlchemy or Flask-AppBuilder, at the root
    or up to ``depth`` directories below it (``server/pyproject.toml``,
    ``backend/requirements.txt``). Lets a large Django project skip reading
    every file in search of SQLAlchemy models it does not have.
    """
    from .parser import BROAD_SKIP_DIRS

    base = Path(root)
    skip = BROAD_SKIP_DIRS | _SKIP_DIRS | {"node_modules"}
    level = [base]
    for _ in range(depth + 1):
        nxt: list[Path] = []
        for d in level:
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                if e.is_dir(follow_symlinks=False):
                    if not e.name.startswith(".") and e.name not in skip:
                        nxt.append(Path(e.path))
                    continue
                if e.name == "alembic.ini":
                    return True
                if _DEP_FILE_RE.match(e.name):
                    try:
                        text = Path(e.path).read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    if _DEP_NAME_RE.search(text):
                        return True
        level = nxt
    return False


def is_sqlalchemy_only_source(content: str) -> bool:
    """True when a file reads as SQLAlchemy code and never imports Django.

    The Django parser uses it to leave ``class User(db.Model)`` and
    Flask-AppBuilder ``Model`` classes alone: their ``Model`` tail used to
    pass for a Django base.
    """
    return bool(_SA_SIGNAL_RE.search(content)) and not _DJANGO_IMPORT_RE.search(
        content
    )


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _dotted(node: ast.AST | None) -> str | None:
    parts: list[str] = []
    cursor = node
    while isinstance(cursor, ast.Attribute):
        parts.append(cursor.attr)
        cursor = cursor.value
    if isinstance(cursor, ast.Name):
        parts.append(cursor.id)
        return ".".join(reversed(parts))
    return None


def _tail(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _const_bool(node: ast.AST | None) -> bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


def _kwargs(call: ast.Call) -> dict[str, ast.expr]:
    return {kw.arg: kw.value for kw in call.keywords if kw.arg}


def _segment(source: str, node: ast.AST) -> str:
    text = ast.get_source_segment(source, node)
    if text is None:  # pragma: no cover - only for synthesized nodes
        try:
            text = ast.unparse(node)
        except Exception:
            text = ""
    return " ".join(text.split())


def _call_args_text(source: str, call: ast.Call) -> str:
    parts = [_segment(source, a) for a in call.args]
    for kw in call.keywords:
        value = _segment(source, kw.value)
        parts.append(f"{kw.arg}={value}" if kw.arg else f"**{value}")
    return ", ".join(parts)


def _string_annotation(node: ast.AST | None) -> ast.AST | None:
    """Parse a quoted annotation (``Mapped["User"]``) back into an expression."""
    text = _const_str(node)
    if text is None:
        return node
    try:
        return ast.parse(text, mode="eval").body
    except SyntaxError:
        return ast.Name(id=text.strip(), ctx=ast.Load())


def _subscript_items(node: ast.Subscript) -> list[ast.expr]:
    inner = node.slice
    if isinstance(inner, ast.Tuple):
        return list(inner.elts)
    return [inner]  # type: ignore[list-item]


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None or (
        isinstance(node, ast.Name) and node.id == "None"
    )


@dataclass
class _Ann:
    """What an annotation says about an attribute."""

    inner: ast.AST | None = None
    collection: bool | None = None
    lazy: str | None = None
    mapped: bool = False
    class_var: bool = False


def _read_annotation(node: ast.AST | None, depth: int = 0) -> _Ann:
    out = _Ann()
    node = _string_annotation(node)
    while node is not None and depth < 12:
        depth += 1
        node = _string_annotation(node)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            # ``X | None``
            node = node.right if _is_none(node.left) else node.left
            continue
        if isinstance(node, ast.Subscript):
            base = _tail(node.value)
            items = _subscript_items(node)
            if base in _MAPPED_TAILS:
                out.mapped = True
                out.lazy = out.lazy or _MAPPED_TAILS[base]
                node = items[0]
                continue
            if base == "ClassVar":
                out.class_var = True
                return out
            if base == "Optional":
                node = items[0]
                continue
            if base == "Union":
                rest = [i for i in items if not _is_none(i)]
                node = rest[0] if rest else None
                continue
            if base == "Annotated":
                node = items[0]
                continue
            if base in _COLLECTION_TAILS:
                out.collection = True
                node = items[0]
                continue
            if base in _MAPPING_TAILS:
                out.collection = True
                node = items[-1]
                continue
            node = node.value
            continue
        break
    out.inner = node
    if out.collection is None and node is not None:
        out.collection = False
    return out


def _annotation_type(ann: _Ann) -> str | None:
    tail = _tail(ann.inner) if ann.inner is not None else None
    if tail is None:
        return None
    if ann.collection:
        return "JSON" if tail in _MAPPING_TAILS else "ARRAY"
    return _PY_TYPES.get(tail, tail)


def _target_name(node: ast.AST | None) -> str | None:
    """Class name from a relationship's first argument or a lambda/str."""
    if isinstance(node, ast.Lambda):
        node = node.body
    text = _const_str(node)
    if text is not None:
        text = text.strip()
        # ``"Address"``, ``"app.models.Address"``, ``"Address.id"`` is not a
        # thing for relationship(); a dotted string is a module path.
        return text.rsplit(".", 1)[-1] if text else None
    return _tail(node)


_CAMEL_RE = re.compile(r"((?<=[a-z0-9])[A-Z]|(?!^)[A-Z](?=[a-z]))")


def _snake(name: str) -> str:
    """Flask-SQLAlchemy's ``camel_to_snake_case``."""
    return _CAMEL_RE.sub(r"_\1", name).lower().lstrip("_")


def _on_delete(node: ast.AST | None) -> str | None:
    text = _const_str(node)
    if not text:
        return None
    return "_".join(text.strip().upper().split())


# ---------------------------------------------------------------------------
# Pass 1: per-file collection
# ---------------------------------------------------------------------------


@dataclass
class _Column:
    field: ParsedField
    fk_target: str | None = None
    fk_class: str | None = None
    unique: bool = False
    primary_key: bool = False
    sqlmodel_only: bool = False
    """Declared with SQLModel's ``Field()`` or a bare annotation; only a
    column on a SQLModel table class."""


@dataclass
class _Rel:
    rel: ParsedRelationship
    uselist: bool | None = None
    annotation_collection: bool | None = None
    remote_side: bool = False
    backref_name: str | None = None
    backref_lazy: str | None = None
    backref_uselist: bool | None = None
    secondary_expr: ast.AST | None = None
    fk_owners: tuple[str, ...] = ()
    """Classes owning the ``foreign_keys=`` columns; ``""`` for a bare
    column name, i.e. the declaring class itself."""
    raw: str = ""


@dataclass
class _Table:
    name: str
    line: int


@dataclass
class _Module:
    path: str
    imports: dict[str, str] = field(default_factory=dict)
    base_names: set[str] = field(default_factory=set)
    base_mixins: dict[str, str] = field(default_factory=dict)
    registries: set[str] = field(default_factory=set)
    tables: dict[str, _Table] = field(default_factory=dict)
    annotated: dict[str, tuple[str | None, str, bool]] = field(default_factory=dict)
    sa_signal: bool = False


@dataclass
class _Class:
    name: str
    module: _Module
    line: int
    bases: list[str]
    keywords: dict[str, ast.expr]
    decorators: list[str]
    columns: list[_Column] = field(default_factory=list)
    rels: list[_Rel] = field(default_factory=list)
    tablename: str | None = None
    tablename_rule: str | None = None
    table_var: str | None = None
    abstract: bool = False
    fk_constraints: list[tuple[list[str], list[str], str | None]] = field(
        default_factory=list
    )


def _module_level(body: Sequence[ast.stmt]) -> Iterable[ast.stmt]:
    """Top-level statements, descending into module-level if/try/with."""
    for stmt in body:
        if isinstance(stmt, ast.If):
            yield from _module_level(stmt.body)
            yield from _module_level(stmt.orelse)
        elif isinstance(stmt, ast.Try):
            yield from _module_level(stmt.body)
            for handler in stmt.handlers:
                yield from _module_level(handler.body)
            yield from _module_level(stmt.orelse)
            yield from _module_level(stmt.finalbody)
        elif isinstance(stmt, ast.With):
            yield from _module_level(stmt.body)
        else:
            yield stmt


def _assign_parts(stmt: ast.stmt) -> tuple[list[str], ast.expr | None, ast.expr | None]:
    if isinstance(stmt, ast.Assign):
        names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
        return names, stmt.value, None
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return [stmt.target.id], stmt.value, stmt.annotation
    return [], None, None


_PEP758_EXCEPT_RE = re.compile(r"^([ \t]*except\*?)[ \t]+([^\n():#]+,[^\n():#]*?)[ \t]*:", re.M)


def parse_source(source: str, filename: str = "<unknown>") -> ast.Module:
    """``ast.parse`` that also reads Python 3.14's ``except A, B:``.

    Projects that target 3.14 (PEP 758) are scanned by whatever Python the
    tool runs on. On older versions the unparenthesized form is rewritten to
    ``except (A, B):`` on the same line and parsing is retried, so a single
    handler does not hide every model in the file.
    """
    try:
        return ast.parse(source, filename=filename)
    except SyntaxError:
        fixed, count = _PEP758_EXCEPT_RE.subn(r"\1 (\2):", source)
        if not count:
            raise
        return ast.parse(fixed, filename=filename)


def _parse_module(path: str, source: str) -> tuple[_Module, list[_Class]]:
    tree = parse_source(source, filename=path)
    module = _Module(path=path, sa_signal=bool(_SA_SIGNAL_RE.search(source)))
    classes: list[_Class] = []
    for stmt in _module_level(tree.body):
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                module.imports[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(stmt, ast.ImportFrom):
            prefix = "." * (stmt.level or 0) + (stmt.module or "")
            for alias in stmt.names:
                module.imports[alias.asname or alias.name] = f"{prefix}.{alias.name}"
        elif isinstance(stmt, ast.ClassDef):
            classes.append(_parse_class(stmt, module, source))
        else:
            names, value, _ann = _assign_parts(stmt)
            if names and value is not None:
                _module_assignment(module, names, value, source)
    return module, classes


def _module_assignment(
    module: _Module, names: list[str], value: ast.expr, source: str
) -> None:
    if isinstance(value, ast.Call):
        tail = _tail(value.func)
        if tail == "declarative_base" or tail == "generate_base":
            module.base_names.update(names)
            mixin = _dotted(_kwargs(value).get("cls"))
            if mixin:
                for n in names:
                    module.base_mixins[n] = mixin.rsplit(".", 1)[-1]
        elif tail == "registry":
            module.registries.update(names)
        elif tail == "SQLAlchemy":
            module.base_names.update(f"{n}.Model" for n in names)
        elif tail == "Table":
            name = _const_str(value.args[0]) if value.args else None
            if name:
                for n in names:
                    module.tables[n] = _Table(name=name, line=value.lineno - 1)
    elif isinstance(value, ast.Attribute) and value.attr == "Model":
        prefix = _dotted(value.value)
        if prefix and prefix != "models":
            module.base_names.update(names)
    elif isinstance(value, ast.Subscript) and _tail(value.value) == "Annotated":
        items = _subscript_items(value)
        calls = [i for i in items[1:] if isinstance(i, ast.Call) and _tail(i) in _COLUMN_CALLS]
        if calls:
            ann = _read_annotation(items[0])
            type_name = _column_type(calls[0]) or _annotation_type(ann)
            args = _call_args_text(source, calls[0])
            pk = _const_bool(_kwargs(calls[0]).get("primary_key")) is True
            for n in names:
                module.annotated[n] = (type_name, args, pk)


def _decorator_name(node: ast.expr) -> str:
    return _dotted(node.func if isinstance(node, ast.Call) else node) or ""


def _parse_class(node: ast.ClassDef, module: _Module, source: str) -> _Class:
    bases = []
    for b in node.bases:
        if isinstance(b, ast.Subscript):  # Generic[T], Base[Any]
            b = b.value
        name = _dotted(b)
        if name:
            bases.append(name)
    cls = _Class(
        name=node.name,
        module=module,
        line=node.lineno - 1,
        bases=bases,
        keywords={kw.arg: kw.value for kw in node.keywords if kw.arg},
        decorators=[_decorator_name(d) for d in node.decorator_list],
    )
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _parse_declared_attr(cls, stmt, source)
            continue
        names, value, annotation = _assign_parts(stmt)
        if len(names) != 1:
            continue
        name = names[0]
        line = stmt.lineno - 1
        if name == "__tablename__":
            cls.tablename = _const_str(value)
            continue
        if name == "__abstract__":
            cls.abstract = _const_bool(value) is True
            continue
        if name == "__table__":
            if isinstance(value, ast.Call) and _tail(value.func) == "Table":
                cls.tablename = _const_str(value.args[0]) if value.args else None
                for arg in value.args[1:]:
                    if isinstance(arg, ast.Call) and _tail(arg.func) == "Column":
                        col_name = _const_str(arg.args[0]) if arg.args else None
                        if col_name:
                            cls.columns.append(
                                _parse_column(col_name, None, arg, source, arg.lineno - 1, module)
                            )
            else:
                cls.table_var = _dotted(value)
            continue
        if name == "__table_args__":
            _parse_table_args(cls, value)
            continue
        if name.startswith("__"):
            continue
        _classify(cls, name, annotation, value, source, line)
    return cls


def _parse_table_args(cls: _Class, value: ast.expr | None) -> None:
    items: list[ast.expr] = []
    if isinstance(value, (ast.Tuple, ast.List)):
        items = list(value.elts)
    elif value is not None:
        items = [value]
    for item in items:
        if not (isinstance(item, ast.Call) and _tail(item.func) == "ForeignKeyConstraint"):
            continue
        if len(item.args) < 2:
            continue
        local, remote = item.args[0], item.args[1]
        if not isinstance(local, (ast.List, ast.Tuple)) or not isinstance(
            remote, (ast.List, ast.Tuple)
        ):
            continue
        local_names = [s for s in (_const_str(e) for e in local.elts) if s]
        remote_names = [s for s in (_const_str(e) for e in remote.elts) if s]
        if local_names and remote_names:
            cls.fk_constraints.append(
                (local_names, remote_names, _on_delete(_kwargs(item).get("ondelete")))
            )


def _parse_declared_attr(
    cls: _Class, fn: ast.FunctionDef | ast.AsyncFunctionDef, source: str
) -> None:
    if not any(d.split(".")[0] == "declared_attr" or d.endswith(".declared_attr")
               for d in (_decorator_name(x) for x in fn.decorator_list)):
        return
    returns = [
        n.value for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None
    ]
    if fn.name == "__tablename__":
        if len(returns) == 1 and _const_str(returns[0]) is not None:
            cls.tablename = _const_str(returns[0])
            return
        uses_name = any(
            isinstance(n, ast.Attribute) and n.attr == "__name__"
            for r in returns
            for n in ast.walk(r)
        )
        if not uses_name:
            return
        plain_lower = any(
            isinstance(r, ast.Call)
            and isinstance(r.func, ast.Attribute)
            and r.func.attr == "lower"
            and isinstance(r.func.value, ast.Attribute)
            and r.func.value.attr == "__name__"
            for r in returns
        )
        cls.tablename_rule = "lower" if plain_lower else "snake"
        return
    if fn.name.startswith("__") or len(returns) != 1:
        return
    _classify(cls, fn.name, fn.returns, returns[0], source, fn.lineno - 1)


def _classify(
    cls: _Class,
    name: str,
    annotation: ast.expr | None,
    value: ast.expr | None,
    source: str,
    line: int,
) -> None:
    ann = _read_annotation(annotation) if annotation is not None else _Ann()
    if ann.class_var:
        return
    if isinstance(value, ast.Call) and _tail(value.func) in _COLUMN_WRAPPERS:
        inner = value.args[0] if value.args else None
        if not (isinstance(inner, ast.Call) and _tail(inner.func) in _COLUMN_CALLS):
            return
        value = inner
    if isinstance(value, ast.Call):
        tail = _tail(value.func)
        if tail in _COLUMN_CALLS:
            cls.columns.append(_parse_column(name, ann, value, source, line, cls.module))
            return
        if tail in _RELATIONSHIP_CALLS:
            cls.rels.append(_parse_relationship(name, ann, value, source, line))
            return
        if tail == "Field":
            col = _parse_sqlmodel_field(name, ann, value, source, line, cls.module)
            if col is not None:
                cls.columns.append(col)
            return
        return
    if value is None and annotation is not None:
        col = _annotation_column(name, ann, line, cls.module)
        if col is not None:
            col.sqlmodel_only = not ann.mapped
            cls.columns.append(col)
        return
    if (
        value is not None
        and annotation is not None
        and not ann.mapped
        and isinstance(value, (ast.Constant, ast.Name, ast.Attribute))
    ):
        # SQLModel: ``name: str = "default"``.
        col = _annotation_column(name, ann, line, cls.module)
        if col is not None:
            col.sqlmodel_only = True
            cls.columns.append(col)


def _column_type(call: ast.Call) -> str | None:
    for i, arg in enumerate(call.args):
        if i == 0 and _const_str(arg) is not None:
            continue
        tail = _tail(arg)
        if tail is None or tail in _SCHEMA_ITEMS:
            continue
        if isinstance(arg, (ast.Name, ast.Attribute, ast.Call)):
            return tail
    type_kw = _kwargs(call).get("type_")
    return _tail(type_kw) if type_kw is not None else None


def _foreign_key(call: ast.Call) -> tuple[str | None, str | None, str | None]:
    """``(table_target, class_target, ondelete)`` of the first ForeignKey."""
    for arg in call.args:
        if isinstance(arg, ast.Call) and _tail(arg.func) == "ForeignKey":
            target = arg.args[0] if arg.args else _kwargs(arg).get("column")
            ondelete = _on_delete(_kwargs(arg).get("ondelete"))
            text = _const_str(target)
            if text is not None:
                return text, None, ondelete
            dotted = _dotted(target)
            if dotted and "." in dotted:
                return None, dotted.split(".")[-2], ondelete
            return None, None, ondelete
    return None, None, None


def _parse_column(
    name: str,
    ann: _Ann | None,
    call: ast.Call,
    source: str,
    line: int,
    module: _Module,
) -> _Column:
    kwargs = _kwargs(call)
    type_name = _column_type(call)
    args = _call_args_text(source, call)
    alias_pk = False
    if ann is not None and ann.inner is not None:
        alias = module.annotated.get(_tail(ann.inner) or "")
        if alias is not None:
            alias_type, alias_args, alias_pk = alias
            type_name = type_name or alias_type
            args = ", ".join(p for p in (alias_args, args) if p)
        if type_name is None:
            type_name = _annotation_type(ann)
    fk_table, fk_class, ondelete = _foreign_key(call)
    unique = _const_bool(kwargs.get("unique")) is True
    pk = _const_bool(kwargs.get("primary_key")) is True or alias_pk
    is_fk = fk_table is not None or fk_class is not None
    field_ = ParsedField(
        name=name,
        type=type_name or "Column",
        args=args,
        is_relation=is_fk,
        line_number=line,
    )
    if is_fk:
        field_.relation_kind = "OneToOneField" if unique or pk else "ForeignKey"
        field_.on_delete = ondelete
    return _Column(
        field=field_,
        fk_target=fk_table,
        fk_class=fk_class,
        unique=unique,
        primary_key=pk,
    )


def _parse_sqlmodel_field(
    name: str, ann: _Ann, call: ast.Call, source: str, line: int, module: _Module
) -> _Column | None:
    kwargs = _kwargs(call)
    sa_column = kwargs.get("sa_column")
    if isinstance(sa_column, ast.Call) and _tail(sa_column.func) in _COLUMN_CALLS:
        col = _parse_column(name, ann, sa_column, source, line, module)
        col.sqlmodel_only = True
        return col
    type_name = _tail(kwargs["sa_type"]) if "sa_type" in kwargs else _annotation_type(ann)
    fk_table = _const_str(kwargs.get("foreign_key"))
    pk = _const_bool(kwargs.get("primary_key")) is True
    unique = _const_bool(kwargs.get("unique")) is True
    field_ = ParsedField(
        name=name,
        type=type_name or "Column",
        args=_call_args_text(source, call),
        is_relation=fk_table is not None,
        line_number=line,
    )
    if fk_table is not None:
        field_.relation_kind = "OneToOneField" if unique or pk else "ForeignKey"
        field_.on_delete = _on_delete(kwargs.get("ondelete"))
    return _Column(
        field=field_,
        fk_target=fk_table,
        unique=unique,
        primary_key=pk,
        sqlmodel_only=True,
    )


def _annotation_column(name: str, ann: _Ann, line: int, module: _Module) -> _Column | None:
    if ann.inner is None:
        return None
    alias = module.annotated.get(_tail(ann.inner) or "")
    if alias is not None:
        alias_type, alias_args, alias_pk = alias
        return _Column(
            field=ParsedField(
                name=name,
                type=alias_type or "Column",
                args=alias_args,
                is_relation=False,
                line_number=line,
            ),
            primary_key=alias_pk,
        )
    return _Column(
        field=ParsedField(
            name=name,
            type=_annotation_type(ann) or "Column",
            args="",
            is_relation=False,
            line_number=line,
        )
    )


def _lazy(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if _is_none(node):
        return "noload"
    flag = _const_bool(node)
    if flag is not None:
        return _LAZY_BOOL[flag]
    text = _const_str(node)
    return text.strip() if text else None


def _parse_relationship(
    name: str, ann: _Ann, call: ast.Call, source: str, line: int
) -> _Rel:
    kwargs = dict(_kwargs(call))
    # SQLModel: Relationship(sa_relationship_kwargs={"lazy": "selectin"}).
    extra = kwargs.get("sa_relationship_kwargs")
    if isinstance(extra, ast.Dict):
        for key, val in zip(extra.keys, extra.values):
            text = _const_str(key)
            if text and text not in kwargs:
                kwargs[text] = val
    nested = kwargs.get("sa_relationship")
    if isinstance(nested, ast.Call) and _tail(nested.func) in _RELATIONSHIP_CALLS:
        return _parse_relationship(name, ann, nested, source, line)

    target = _target_name(call.args[0]) if call.args else None
    if target is None and "argument" in kwargs:
        target = _target_name(kwargs["argument"])
    if target is None and ann.inner is not None:
        target = _tail(ann.inner)
    secondary = kwargs.get("secondary") or kwargs.get("link_model")
    backref_name = None
    backref_lazy = None
    backref_uselist = None
    backref = kwargs.get("backref")
    if backref is not None:
        backref_name = _const_str(backref)
        if isinstance(backref, ast.Call) and backref.args:
            backref_name = _const_str(backref.args[0])
            bkw = _kwargs(backref)
            backref_lazy = _lazy(bkw.get("lazy"))
            backref_uselist = _const_bool(bkw.get("uselist"))
    rel = ParsedRelationship(
        name=name,
        target=target,
        line_number=line,
        lazy=_lazy(kwargs.get("lazy")) or ann.lazy or "select",
        back_populates=_const_str(kwargs.get("back_populates")),
        backref=backref_name,
    )
    return _Rel(
        rel=rel,
        uselist=_const_bool(kwargs.get("uselist")),
        annotation_collection=ann.collection if ann.inner is not None else None,
        remote_side="remote_side" in kwargs,
        backref_name=backref_name,
        backref_lazy=backref_lazy,
        backref_uselist=backref_uselist,
        secondary_expr=secondary,
        fk_owners=_fk_owners(kwargs.get("foreign_keys")),
        raw=_call_args_text(source, call),
    )


def _fk_owners(node: ast.AST | None) -> tuple[str, ...]:
    """``foreign_keys="Users.team_id"`` / ``[team_id]`` / ``[Order.customer_id]``
    → the class each column belongs to (``""`` when it is this class's)."""
    if node is None:
        return ()
    if isinstance(node, ast.Lambda):
        node = node.body
    text = _const_str(node)
    if text is not None:
        try:
            node = ast.parse(text.strip(), mode="eval").body
        except SyntaxError:
            return ()
    items = list(node.elts) if isinstance(node, (ast.List, ast.Tuple, ast.Set)) else [node]
    owners: list[str] = []
    for item in items:
        dotted = _dotted(item)
        if dotted is None:
            continue
        parts = dotted.split(".")
        if len(parts) < 2 or parts[0] in ("__table__", "cls", "self"):
            owners.append("")
        else:
            owners.append(parts[-2])
    return tuple(owners)


# ---------------------------------------------------------------------------
# Pass 2: resolution
# ---------------------------------------------------------------------------

_ROOT = "root"  # a declarative base marker: subclasses are mapped
_DECL = "declarative"  # the DeclarativeBase class itself
_SQLMODEL = "sqlmodel"


class _Resolver:
    def __init__(self, classes: list[_Class], modules: list[_Module]) -> None:
        self.classes = classes
        self.by_name: dict[str, list[_Class]] = {}
        for c in classes:
            self.by_name.setdefault(c.name, []).append(c)
        self.base_names: set[str] = set()
        self.base_mixins: dict[str, str] = {}
        self.tables: dict[str, _Table] = {}
        for m in modules:
            self.base_names.update(m.base_names)
            self.base_mixins.update(m.base_mixins)
            for var, table in m.tables.items():
                self.tables.setdefault(var, table)
        self._status: dict[int, str] = {}
        self._ancestors: dict[int, list[_Class]] = {}
        self._by_stem: dict[str, _Module] = {
            Path(m.path).with_suffix("").as_posix(): m for m in modules
        }
        self._module_cache: dict[tuple[str, str], _Module | None] = {}

    # -- base resolution ----------------------------------------------------

    def _module_for(self, importer: _Module, dotted_module: str) -> _Module | None:
        """The scanned module an import statement points at, if any."""
        key = (importer.path, dotted_module)
        if key in self._module_cache:
            return self._module_cache[key]
        found: _Module | None = None
        level = len(dotted_module) - len(dotted_module.lstrip("."))
        rest = dotted_module.lstrip(".").replace(".", "/")
        if level:
            base_dir = Path(importer.path).parent
            for _ in range(level - 1):
                base_dir = base_dir.parent
            stem = (base_dir / rest).as_posix() if rest else base_dir.as_posix()
            found = self._by_stem.get(stem) or self._by_stem.get(f"{stem}/__init__")
        elif rest:
            for stem, mod in self._by_stem.items():
                if stem.endswith("/" + rest) or stem.endswith("/" + rest + "/__init__"):
                    found = mod
                    break
        self._module_cache[key] = found
        return found

    def _resolve_import(
        self, importer: _Module, full: str, cls: _Class, hops: int = 0
    ) -> str | _Class | None:
        """Follow ``from x import Name`` (and one re-export per hop) to a
        class, or to a declarative base bound by assignment."""
        if hops > 4 or "." not in full.lstrip("."):
            return None
        mod_name, name = full.rsplit(".", 1)
        target = self._module_for(importer, mod_name)
        if target is None:
            return None
        if name in target.base_names:
            return _ROOT
        for c in self.by_name.get(name, []):
            if c.module is target and c is not cls:
                return c
        again = target.imports.get(name)
        if again:
            return self._resolve_import(target, again, cls, hops + 1)
        return None

    def resolve_base(self, cls: _Class, base: str) -> str | _Class | None:
        module = cls.module
        head = base.split(".")[0]
        origin = module.imports.get(head, "")
        full = origin + base[len(head):] if origin else base
        tail = full.rsplit(".", 1)[-1]
        if tail in _DECLARATIVE_ROOTS:
            return _DECL
        if tail == "SQLModel":
            return _SQLMODEL
        if tail in _NEUTRAL_BASES or base.startswith("models."):
            return None  # ``models.Model`` and friends are Django's
        if base in module.base_names:
            return _ROOT
        if tail == "Model":
            if full.startswith(("flask_appbuilder", "flask_sqlalchemy")):
                return _ROOT
            prefix = base.rsplit(".", 1)[0] if "." in base else ""
            if prefix and prefix != "models" and module.sa_signal:
                return _ROOT
        if origin:
            resolved = self._resolve_import(module, full, cls)
            if resolved is not None:
                return resolved
        candidates = [c for c in self.by_name.get(tail, []) if c is not cls]
        same_file = [c for c in candidates if c.module is module]
        if same_file and not origin:
            return same_file[0]
        if candidates:
            return candidates[0]
        if tail in self.base_names and origin:
            return _ROOT
        return None

    def parents(self, cls: _Class) -> list[_Class]:
        out = []
        for b in cls.bases:
            r = self.resolve_base(cls, b)
            if isinstance(r, _Class):
                out.append(r)
        return out

    # -- class status -------------------------------------------------------

    def status(self, cls: _Class, _stack: frozenset = frozenset()) -> str:
        """``mapped`` | ``abstract`` | ``declarative`` | ``sqlmodel`` | ``plain``."""
        key = id(cls)
        if key in self._status:
            return self._status[key]
        if key in _stack:
            return "plain"
        stack = _stack | {key}
        sa = False
        sqlmodel = False
        decl = any(d.split(".")[-1] == "as_declarative" for d in cls.decorators)
        if any(
            d.split(".")[-1] in ("mapped", "mapped_as_dataclass") for d in cls.decorators
        ):
            sa = True
        for b in cls.bases:
            r = self.resolve_base(cls, b)
            if r == _DECL:
                decl = True
            elif r == _ROOT:
                sa = True
            elif r == _SQLMODEL:
                sqlmodel = True
            elif isinstance(r, _Class):
                parent = self.status(r, stack)
                if parent in ("mapped", "abstract", "declarative"):
                    sa = True
                elif parent == "sqlmodel":
                    sqlmodel = True
        if decl:
            result = "declarative"
        elif sa:
            result = "abstract" if cls.abstract else "mapped"
        elif sqlmodel:
            table = _const_bool(cls.keywords.get("table")) is True
            result = "mapped" if table else "sqlmodel"
        else:
            result = "plain"
        self._status[key] = result
        return result

    def is_sqlmodel(self, cls: _Class, _seen: frozenset = frozenset()) -> bool:
        if id(cls) in _seen:
            return False
        for b in cls.bases:
            r = self.resolve_base(cls, b)
            if r == _SQLMODEL:
                return True
            if isinstance(r, _Class) and self.is_sqlmodel(r, _seen | {id(cls)}):
                return True
        return False

    def is_flask(self, cls: _Class, _seen: frozenset = frozenset()) -> bool:
        if id(cls) in _seen:
            return False
        for b in cls.bases:
            r = self.resolve_base(cls, b)
            if r == _ROOT and b.rsplit(".", 1)[-1] == "Model":
                return True
            if isinstance(r, _Class) and self.is_flask(r, _seen | {id(cls)}):
                return True
        return False

    # -- inherited parts ----------------------------------------------------

    def ancestors(self, cls: _Class) -> list[_Class]:
        """Every resolvable ancestor, nearest first, each once."""
        cached = self._ancestors.get(id(cls))
        if cached is not None:
            return cached
        out: list[_Class] = []
        seen = {id(cls)}
        queue = list(self.parents(cls))
        while queue:
            c = queue.pop(0)
            if id(c) in seen:
                continue
            seen.add(id(c))
            out.append(c)
            queue.extend(self.parents(c))
        # ``declarative_base(cls=Mixin)``: the mixin's columns reach everyone.
        for anc in [cls, *out]:
            for b in anc.bases:
                mixin = self.base_mixins.get(b)
                if mixin:
                    for c in self.by_name.get(mixin, []):
                        if id(c) not in seen:
                            seen.add(id(c))
                            out.append(c)
        self._ancestors[id(cls)] = out
        return out

    def table_rule(self, cls: _Class) -> str | None:
        for c in [cls, *self.ancestors(cls)]:
            if c.tablename_rule:
                return c.tablename_rule
        if self.is_flask(cls):
            return "snake"
        if self.is_sqlmodel(cls):
            return "lower"
        return None


def _wanted_column(col: _Column, sqlmodel: bool) -> bool:
    return sqlmodel or not col.sqlmodel_only


def _build_models(classes: list[_Class], modules: list[_Module]) -> list[ParsedModel]:
    from .parser import _app_dir_for  # local import: parser imports this module

    res = _Resolver(classes, modules)
    mapped = [c for c in classes if res.status(c) == "mapped"]
    models: list[ParsedModel] = []
    by_class: dict[int, ParsedModel] = {}
    columns_by_model: dict[int, list[_Column]] = {}

    # Tables first: explicit names, then rules, then single-table children.
    table_of: dict[int, str | None] = {}

    def own_pk(c: _Class, sqlmodel: bool) -> bool:
        return any(col.primary_key for col in c.columns if _wanted_column(col, sqlmodel))

    def table_name(c: _Class, stack: frozenset = frozenset()) -> str | None:
        if id(c) in table_of:
            return table_of[id(c)]
        if id(c) in stack:
            return None
        name = c.tablename
        if name is None and c.table_var:
            t = res.tables.get(c.table_var.rsplit(".", 1)[-1])
            name = t.name if t else None
        if name is None:
            mapped_parent = next(
                (p for p in res.ancestors(c) if res.status(p) == "mapped"), None
            )
            sqlmodel = res.is_sqlmodel(c)
            if mapped_parent is not None and not own_pk(c, sqlmodel):
                name = table_name(mapped_parent, stack | {id(c)})
            else:
                rule = res.table_rule(c)
                if rule == "snake":
                    name = _snake(c.name)
                elif rule == "lower":
                    name = c.name.lower()
        table_of[id(c)] = name
        return name

    for c in mapped:
        sqlmodel = res.is_sqlmodel(c)
        _app_dir, app_name = _app_dir_for(c.module.path)
        model = ParsedModel(
            name=c.name,
            app_name=app_name,
            file_path=c.module.path,
            line_number=c.line,
            base_classes=list(c.bases),
            orm="sqlalchemy",
            table_name=table_name(c),
        )
        own = [col for col in c.columns if _wanted_column(col, sqlmodel)]
        model.fields = [col.field for col in own]
        own_names = {col.field.name for col in own}
        inherited: list[_Column] = []
        for anc in res.ancestors(c):
            if res.status(anc) == "mapped":
                continue  # its own table (joined) or the same one (single)
            anc_sqlmodel = sqlmodel or res.status(anc) == "sqlmodel"
            for col in anc.columns:
                if col.field.name in own_names or not _wanted_column(col, anc_sqlmodel):
                    continue
                own_names.add(col.field.name)
                copy = ParsedField(**{**col.field.__dict__, "inherited_from": anc.name})
                model.inherited_fields.append(copy)
                inherited.append(_Column(**{**col.__dict__, "field": copy}))
        columns_by_model[id(c)] = own + inherited
        _apply_fk_constraints(c, own + inherited)
        for r in c.rels:
            model.relationships.append(_copy_rel(r.rel))
        rel_names = {r.name for r in model.relationships}
        for anc in res.ancestors(c):
            for r in anc.rels:
                if r.rel.name in rel_names:
                    continue
                rel_names.add(r.rel.name)
                model.relationships.append(_copy_rel(r.rel, inherited_from=anc.name))
        models.append(model)
        by_class[id(c)] = model

    # Resolve FK targets: table name -> class.
    table_to_model: dict[str, ParsedModel] = {}
    for c in mapped:
        m = by_class[id(c)]
        if m.table_name and m.table_name not in table_to_model:
            parent_mapped = any(res.status(p) == "mapped" for p in res.ancestors(c))
            if not parent_mapped:
                table_to_model[m.table_name] = m
    for c in mapped:
        m = by_class[id(c)]
        if m.table_name and m.table_name not in table_to_model:
            table_to_model[m.table_name] = m
    for c in mapped:
        for col in columns_by_model[id(c)]:
            if not col.field.is_relation:
                continue
            if col.fk_class:
                col.field.related_model = col.fk_class
            elif col.fk_target:
                parts = col.fk_target.split(".")
                table = parts[-2] if len(parts) >= 2 else parts[0]
                target = table_to_model.get(table)
                col.field.related_model = target.name if target else table

    # Relationship shape, secondary tables and backrefs.
    rel_specs: dict[tuple[int, str], _Rel] = {}
    for c in mapped:
        for r in c.rels:
            rel_specs[(id(c), r.rel.name)] = r
        for anc in res.ancestors(c):
            for r in anc.rels:
                rel_specs.setdefault((id(c), r.rel.name), r)
    m2m_seen: set[tuple[frozenset, str]] = set()
    by_name: dict[str, ParsedModel] = {}
    for m in models:
        by_name.setdefault(m.name, m)
    for c in mapped:
        m = by_class[id(c)]
        cols = columns_by_model[id(c)]
        for rel in m.relationships:
            spec = rel_specs.get((id(c), rel.name))
            if spec is None:
                continue
            secondary = _secondary_name(spec.secondary_expr, res, by_name)
            rel.secondary = secondary
            rel.collection = _collection(spec, secondary, m, cols, rel, by_name, columns_by_model, by_class)
            if secondary and rel.inherited_from is None:
                key = (frozenset({m.name, rel.target or ""}), secondary)
                if key not in m2m_seen:
                    m2m_seen.add(key)
                    m.fields.append(
                        ParsedField(
                            name=rel.name,
                            type="relationship",
                            args=spec.raw,
                            is_relation=True,
                            line_number=rel.line_number,
                            related_model=rel.target,
                            relation_kind="ManyToManyField",
                            through_model=secondary,
                        )
                    )
    # Backrefs create an attribute on the other class.
    for c in mapped:
        m = by_class[id(c)]
        for rel in list(m.relationships):
            spec = rel_specs.get((id(c), rel.name))
            if spec is None or not spec.backref_name or rel.inherited_from:
                continue
            target = by_name.get(rel.target or "")
            if target is None or any(r.name == spec.backref_name for r in target.relationships):
                continue
            if spec.backref_uselist is not None:
                collection: bool | None = spec.backref_uselist
            elif rel.secondary:
                collection = True
            elif rel.collection is None:
                collection = None
            else:
                collection = not rel.collection
            target.relationships.append(
                ParsedRelationship(
                    name=spec.backref_name,
                    target=m.name,
                    line_number=rel.line_number,
                    lazy=spec.backref_lazy or "select",
                    collection=collection,
                    secondary=rel.secondary,
                    via_backref=True,
                )
            )
    return models


def _copy_rel(rel: ParsedRelationship, inherited_from: str | None = None) -> ParsedRelationship:
    return ParsedRelationship(**{**rel.__dict__, "inherited_from": inherited_from})


def _apply_fk_constraints(c: _Class, cols: list[_Column]) -> None:
    by_name = {col.field.name: col for col in cols}
    for local, remote, ondelete in c.fk_constraints:
        if len(local) != 1:
            continue  # composite keys: no single column to draw from
        col = by_name.get(local[0])
        if col is None or col.field.is_relation:
            continue
        col.field.is_relation = True
        col.field.relation_kind = "OneToOneField" if col.unique else "ForeignKey"
        col.field.on_delete = ondelete
        col.fk_target = remote[0]


def _secondary_name(
    expr: ast.AST | None, res: _Resolver, by_name: dict[str, ParsedModel]
) -> str | None:
    if expr is None:
        return None
    if isinstance(expr, ast.Lambda):
        expr = expr.body
    text = _const_str(expr)
    if text:
        return text.strip()
    if isinstance(expr, ast.Attribute) and expr.attr == "__table__":
        expr = expr.value  # ``secondary=Assoc.__table__``
    tail = _tail(expr)
    if tail is None:
        return None
    table = res.tables.get(tail)
    if table is not None:
        return table.name
    model = by_name.get(tail)  # an association class, or SQLModel link_model=
    if model is not None:
        return model.table_name or model.name
    return tail


def _collection(
    spec: _Rel,
    secondary: str | None,
    model: ParsedModel,
    cols: list[_Column],
    rel: ParsedRelationship,
    by_name: dict[str, ParsedModel],
    columns_by_model: dict[int, list[_Column]],
    by_class: dict[int, ParsedModel],
) -> bool | None:
    if spec.uselist is not None:
        return spec.uselist
    if spec.annotation_collection is not None:
        return spec.annotation_collection
    if secondary:
        return True
    if spec.remote_side:
        return False
    target = by_name.get(rel.target or "")
    if spec.fk_owners:
        owners = {o or model.name for o in spec.fk_owners}
        if target is not None and target is not model and owners == {target.name}:
            return True  # the foreign key is on the other side: one-to-many
        if owners == {model.name} and target is not model:
            return False  # this side holds the foreign key: many-to-one
    if target is None:
        return None
    if target is model:
        return True  # adjacency list without remote_side: the children
    here = any(col.field.is_relation and col.field.related_model == target.name for col in cols)
    there = any(
        col.field.is_relation and col.field.related_model == model.name
        for key, other in by_class.items()
        if other is target
        for col in columns_by_model.get(key, [])
    )
    if here and not there:
        return False  # this side holds the foreign key: many-to-one
    if there and not here:
        return True
    return None  # keys both ways (or none found): the source must say


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def _is_test_path(rel: Path) -> bool:
    name = rel.name
    if name in ("tests.py", "conftest.py") or name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part in ("tests", "test") for part in rel.parts[:-1])


def _walk_py(root: Path, exclude_globs: Sequence[str]) -> Iterable[Path]:
    """Every ``.py`` under ``root`` a model could live in.

    Skips test modules, vendored trees and Alembic revision directories
    (``versions/`` next to an ``env.py``): old revisions often declare
    throwaway copies of the models for data migrations.
    """
    from .parser import BROAD_SKIP_DIRS

    skip = BROAD_SKIP_DIRS | _SKIP_DIRS
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".")
            and d not in skip
            and not (
                d == "versions"
                and (
                    os.path.exists(os.path.join(dirpath, "env.py"))
                    or os.path.exists(os.path.join(dirpath, "script.py.mako"))
                )
            )
        )
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            full = Path(dirpath) / name
            try:
                rel = full.relative_to(root)
            except ValueError:
                rel = full
            if _is_test_path(rel):
                continue
            if exclude_globs and any(fnmatch(rel.as_posix(), pat) for pat in exclude_globs):
                continue
            yield full


def _read(path: Path) -> str | None:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return source[1:] if source.startswith("\ufeff") else source


def iter_sqlalchemy_candidates(
    root: Path, exclude_globs: Sequence[str] = ()
) -> Iterable[tuple[Path, str]]:
    """Yield ``(path, source)`` for every file that may declare SA models."""
    for path in _walk_py(root, exclude_globs):
        source = _read(path)
        if source is not None and _PREFILTER_RE.search(source):
            yield path, source


ModuleLoader = Callable[[str, str], "tuple[str, str] | None"]
"""``(importer_path, dotted_module) -> (path, source)`` of the imported file."""

#: How many rounds of "load the file a base class is imported from".
_PULL_ROUNDS = 4


def parse_sqlalchemy_sources(
    sources: Iterable[tuple[str, str]], load_module: ModuleLoader | None = None
) -> list[ParsedModel]:
    """Mapped classes declared across ``(path, source)`` pairs.

    Resolution runs over the union, so a base or mixin in one file reaches
    the models of another. Files that do not parse are skipped.

    ``load_module`` fetches files the caller did not pass: a base class can
    live in a file with no SQLAlchemy in it at all (an abstract interface
    imported under an alias, ``from core.models import Dashboard as
    CoreDashboard``). Each round loads the files that unresolved bases are
    imported from, following re-exports, until nothing new turns up.
    """
    modules: list[_Module] = []
    classes: list[_Class] = []
    seen: set[str] = set()

    def add(path: str, source: str) -> _Module | None:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            return None
        seen.add(key)
        try:
            module, found = _parse_module(path, source)
        except (SyntaxError, ValueError, RecursionError):
            return None
        modules.append(module)
        classes.extend(found)
        return module

    for path, source in sources:
        add(path, source)
    if load_module is not None:
        wanted: set[tuple[str, str, str]] = set()
        for c in classes:
            for b in c.bases:
                head = b.split(".")[0]
                origin = c.module.imports.get(head)
                if origin:
                    mod, _, name = (origin + b[len(head):]).rpartition(".")
                    if mod and mod.lstrip("."):
                        wanted.add((c.module.path, mod, name))
        done: set[tuple[str, str, str]] = set()
        for _round in range(_PULL_ROUNDS):
            todo = wanted - done
            if not todo:
                break
            done |= todo
            for importer, mod, name in sorted(todo):
                hit = load_module(importer, mod)
                if hit is None:
                    continue
                module = add(*hit)
                if module is None:
                    continue
                # A re-export: follow the name to where it is defined.
                again = module.imports.get(name)
                if again and not any(c.name == name and c.module is module for c in classes):
                    target_mod, _, target_name = again.rpartition(".")
                    if target_mod:
                        wanted.add((module.path, target_mod, target_name))
                for c in classes:
                    if c.module is not module:
                        continue
                    for b in c.bases:
                        head = b.split(".")[0]
                        origin = module.imports.get(head)
                        if origin:
                            m2, _, n2 = (origin + b[len(head):]).rpartition(".")
                            if m2 and m2.lstrip("."):
                                wanted.add((module.path, m2, n2))
    return _build_models(classes, modules)


def _module_loader(paths: Iterable[Path]) -> ModuleLoader:
    """Resolve imports to the given files, the way Python would find them
    when the project (or one of its ``src/`` folders) is on ``sys.path``."""
    by_last: dict[str, list[str]] = {}
    for path in paths:
        stem = path.with_suffix("").as_posix()
        last = stem.rsplit("/", 1)[-1]
        if last == "__init__":
            stem = stem[: -len("/__init__")]
            last = stem.rsplit("/", 1)[-1]
        by_last.setdefault(last, []).append(path.as_posix())

    def find(stem: str) -> str | None:
        last = stem.rsplit("/", 1)[-1]
        for candidate in by_last.get(last, []):
            bare = candidate[: -len(".py")]
            if bare.endswith("/__init__"):
                bare = bare[: -len("/__init__")]
            if bare == stem or bare.endswith("/" + stem):
                return candidate
        return None

    def load(importer: str, dotted: str) -> tuple[str, str] | None:
        level = len(dotted) - len(dotted.lstrip("."))
        rest = dotted.lstrip(".").replace(".", "/")
        if level:
            base = Path(importer).parent
            for _ in range(level - 1):
                base = base.parent
            stem = (base / rest).as_posix() if rest else base.as_posix()
        else:
            stem = rest
        found = find(stem)
        if found is None:
            return None
        source = _read(Path(found))
        return (str(Path(found)), source) if source is not None else None

    return load


def scan_sqlalchemy_models(
    root: Path | str, exclude_globs: Sequence[str] = ()
) -> tuple[list[ParsedModel], int]:
    """Walk ``root`` and return ``(models, candidate_file_count)``."""
    root_path = Path(root).resolve()
    paths = list(_walk_py(root_path, exclude_globs))
    sources: list[tuple[str, str]] = []
    for path in paths:
        source = _read(path)
        if source is not None and _PREFILTER_RE.search(source):
            sources.append((str(path), source))
    if not sources:
        return [], 0
    return parse_sqlalchemy_sources(sources, _module_loader(paths)), len(sources)
