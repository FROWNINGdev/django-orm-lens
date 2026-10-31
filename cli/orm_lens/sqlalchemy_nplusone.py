"""Static N+1 detector for SQLAlchemy — no import, no database.

Flags a loop over ORM query results that reads a lazily loaded
``relationship()`` of each row: one query for the list, then one more per
row. The query is followed from where it is built to where it is iterated,
inside one function:

* ``select(User)...`` passed to ``session.scalars(...)``, or to
  ``session.execute(...).scalars()``; ``await`` and ``.all()`` /
  ``.unique().all()`` are seen through, and so is a statement kept in a
  variable (``stmt = select(User)``, ``stmt = stmt.where(...)``).
* the legacy ``session.query(User)...`` and Flask-SQLAlchemy's
  ``User.query...``; ``db.paginate(...)`` and ``.paginate(...).items``.
* a single object (``session.get(User, id)``, ``.first()``,
  ``.scalar_one()``) whose collection is then looped over.

A relationship counts as loaded when the query names it in
``.options(...)``: ``selectinload``, ``joinedload``, ``subqueryload``,
``immediateload``, ``contains_eager``, ``raiseload`` and ``noload``,
chained (``selectinload(User.posts).joinedload(Post.author)``) or after
``defaultload``; ``"*"`` covers every relationship at its level. A query
whose options cannot be read (``.options(*opts)``, a helper call) is left
alone. Relationships configured with a non-lazy loader (``selectin``,
``joined``, ``subquery``, ``immediate``) never load per row; ``raise``,
``noload``, ``dynamic`` and ``write_only`` are not reported either.

Confidence: ``high`` when a collection is loaded per row, ``medium`` for a
many-to-one, which the identity map may answer without SQL when the
related object is already in the session.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from .models import ParsedRelationship, WorkspaceIndex
from .query_analyzer import NPlusOneFinding, _is_test_file, _iter_py_files_broad, _rel_posix
from .sqlalchemy_parser import parse_source

# An Alembic revision (``down_revision = ...`` at module level). Its loops
# run once, during a deploy, like Django migrations, which the Django
# detector skips too.
_ALEMBIC_REVISION_RE = re.compile(r"^down_revision\s*(?::[^=\n]+)?=", re.M)

_PREFILTER_RE = re.compile(
    r"\bselect\(|\.query\b|\.scalars?\(|\.execute\(|paginate\(|\.get\(|\.stream"
)

#: Loader strategies that never cost a query per row inside a loop.
_NOT_PER_ROW = frozenset(
    {
        "selectin", "joined", "subquery", "immediate", "raise", "raise_on_sql",
        "noload", "dynamic", "write_only",
    }
)
_EAGER_OPTIONS = frozenset(
    {
        "selectinload", "joinedload", "subqueryload", "immediateload",
        "contains_eager", "raiseload", "noload", "joinedload_all",
        "subqueryload_all", "selectinload_all",
    }
)
#: Options that walk a path without loading the hop they name.
_PATH_OPTIONS = frozenset({"defaultload", "lazyload"})
#: Options that change columns only; harmless for relationships.
_COLUMN_OPTIONS = frozenset(
    {
        "load_only", "defer", "undefer", "undefer_group", "with_expression",
        "selectin_polymorphic", "with_loader_criteria", "raiseload_columns",
    }
)
_STMT_METHODS = frozenset(
    {
        "where", "filter", "filter_by", "order_by", "limit", "offset", "join",
        "outerjoin", "join_from", "outerjoin_from", "distinct", "group_by",
        "having", "execution_options", "select_from", "correlate",
        "with_for_update", "params", "slice", "fetch", "prefix_with",
        "suffix_with", "populate_existing", "autoflush", "enable_eagerloads",
        "set_label_style", "apply_labels", "reset_joinpoint", "with_hint",
        "yield_per",
    }
)
_SEQ_METHODS = frozenset({"all", "fetchall", "unique", "yield_per", "execution_options"})
_SEQ_BUILTINS = frozenset({"list", "tuple", "sorted", "reversed", "iter", "set"})
_ONE_METHODS = frozenset(
    {
        "first", "one", "one_or_none", "scalar", "scalar_one",
        "scalar_one_or_none", "first_or_404", "one_or_404", "get_or_404",
    }
)


@dataclass(frozen=True)
class _Src:
    """What an expression evaluates to, as far as loading goes."""

    kind: str
    """``stmt`` (a select), ``query`` (legacy Query, iterable),
    ``seq`` (objects), ``rows`` (Row tuples), ``page`` (pagination),
    ``enumerate`` (``enumerate()`` over objects) or ``one`` (a single
    object)."""
    model: str
    root: str
    prefix: tuple[str, ...] = ()
    loaded: frozenset[str] = frozenset()
    """Loaded paths, ``"<RootClass>:<dotted.path>"``."""
    entities: tuple[str | None, ...] = ()
    opaque: bool = False
    label: str = ""


class _Schema:
    def __init__(self, index: WorkspaceIndex) -> None:
        self.rels: dict[str, dict[str, ParsedRelationship]] = {}
        for app in index.apps:
            for model in app.models:
                if model.orm != "sqlalchemy":
                    continue
                attrs = self.rels.setdefault(model.name, {})
                for rel in model.relationships:
                    attrs.setdefault(rel.name, rel)

    def is_model(self, name: str | None) -> bool:
        return name is not None and name in self.rels

    def rel(self, model: str, attr: str) -> ParsedRelationship | None:
        return self.rels.get(model, {}).get(attr)


def _tail(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _label(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    try:
        text = ast.unparse(node)
    except Exception:  # pragma: no cover
        return "<query>"
    text = " ".join(text.split())
    return text if len(text) <= 60 else text[:57] + "..."


class _Evaluator:
    def __init__(self, schema: _Schema) -> None:
        self.schema = schema

    def eval(self, node: ast.AST | None, env: dict[str, _Src]) -> _Src | None:
        if node is None:
            return None
        if isinstance(node, ast.Await):
            return self.eval(node.value, env)
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.Subscript):
            inner = self.eval(node.value, env)
            if inner is not None and inner.kind == "seq" and isinstance(node.slice, ast.Slice):
                return inner
            return None
        if isinstance(node, ast.Attribute):
            return self._attribute(node, env)
        if isinstance(node, ast.Call):
            return self._call(node, env)
        return None

    def _attribute(self, node: ast.Attribute, env: dict[str, _Src]) -> _Src | None:
        if node.attr == "query" and isinstance(node.value, ast.Name):
            name = node.value.id
            if self.schema.is_model(name):
                return _Src(kind="query", model=name, root=name, entities=(name,))
        owner = self.eval(node.value, env)
        if owner is None:
            return None
        if owner.kind == "page" and node.attr == "items":
            return replace(owner, kind="seq")
        if owner.kind == "one":
            rel = self.schema.rel(owner.model, node.attr)
            if rel is None or not rel.target:
                return None
            kind = "seq" if rel.collection else "one"
            return replace(
                owner,
                kind=kind,
                model=rel.target,
                prefix=(*owner.prefix, node.attr),
                entities=(rel.target,),
                label=_label(node),
            )
        return None

    def _call(self, node: ast.Call, env: dict[str, _Src]) -> _Src | None:
        func = node.func
        if isinstance(func, ast.Name):
            if func.id == "select":
                return self._select(node)
            if func.id in _SEQ_BUILTINS and node.args:
                inner = self.eval(node.args[0], env)
                if inner is not None and inner.kind in ("seq", "query", "page"):
                    return replace(inner, kind="seq")
            if func.id == "enumerate" and node.args:
                inner = self.eval(node.args[0], env)
                if inner is not None and inner.kind in ("seq", "query", "page"):
                    return replace(inner, kind="enumerate")
            return None
        if not isinstance(func, ast.Attribute):
            return None
        method = func.attr
        if method == "select" and _tail(func.value) in ("sa", "sqlalchemy", "future"):
            return self._select(node)
        if method == "query":
            return self._select(node, kind="query")
        if method in ("scalars", "stream_scalars"):
            if node.args:
                stmt = self.eval(node.args[0], env)
                if stmt is not None and stmt.kind == "stmt":
                    return replace(stmt, kind="seq", label=_label(node))
                return None
            recv = self.eval(func.value, env)
            if recv is not None and recv.kind == "rows" and recv.entities and recv.entities[0]:
                return replace(recv, kind="seq", model=recv.entities[0])
            return None
        if method in ("execute", "stream"):
            if node.args:
                stmt = self.eval(node.args[0], env)
                if stmt is not None and stmt.kind == "stmt":
                    return replace(stmt, kind="rows", label=_label(node))
            return None
        if method == "paginate":
            if node.args:
                stmt = self.eval(node.args[0], env)
                if stmt is not None and stmt.kind == "stmt":
                    return replace(stmt, kind="page", label=_label(node))
            recv = self.eval(func.value, env)
            if recv is not None and recv.kind == "query":
                return replace(recv, kind="page", label=_label(node))
            return None
        if method in ("get", "get_one"):
            # session.get(User, pk, options=[...]) / User.query.get(pk)
            if node.args and isinstance(node.args[0], ast.Name) and self.schema.is_model(
                node.args[0].id
            ):
                name = node.args[0].id
                src = _Src(kind="one", model=name, root=name, entities=(name,))
                for kw in node.keywords:
                    if kw.arg == "options" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        src = self._options(src, list(kw.value.elts))
                return src
            recv = self.eval(func.value, env)
            if recv is not None and recv.kind == "query":
                return replace(recv, kind="one")
            return None
        if method == "scalar" and node.args:
            stmt = self.eval(node.args[0], env)
            if stmt is not None and stmt.kind == "stmt":
                return replace(stmt, kind="one")
            return None
        recv = self.eval(func.value, env)
        if recv is None:
            return None
        if method == "options":
            if recv.kind in ("stmt", "query"):
                return self._options(recv, list(node.args))
            return None
        if method in _STMT_METHODS and recv.kind in ("stmt", "query"):
            return recv
        if method in _SEQ_METHODS and recv.kind in ("seq", "rows", "query"):
            return replace(recv, kind="seq" if recv.kind == "query" else recv.kind)
        if method in _ONE_METHODS and recv.kind in ("seq", "query", "rows"):
            if recv.kind == "rows" and method not in ("scalar_one", "scalar_one_or_none", "scalar"):
                return None
            return replace(recv, kind="one")
        return None

    def _select(self, node: ast.Call, kind: str = "stmt") -> _Src | None:
        entities: list[str | None] = []
        for arg in node.args:
            name = arg.id if isinstance(arg, ast.Name) else None
            entities.append(name if self.schema.is_model(name) else None)
        if not entities or entities[0] is None:
            return None
        first = entities[0]
        return _Src(kind=kind, model=first, root=first, entities=tuple(entities), label=_label(node))

    def _options(self, src: _Src, options: list[ast.expr]) -> _Src:
        loaded = set(src.loaded)
        opaque = src.opaque
        for opt in options:
            steps = _loader_steps(opt)
            if steps is None:
                opaque = True
                continue
            path: list[str] = []
            root: str | None = None
            for loader, args in steps:
                if loader == "Load":
                    root = args[0][0] if args and args[0][0] else root
                    continue
                if loader in _COLUMN_OPTIONS:
                    continue
                if loader not in _EAGER_OPTIONS and loader not in _PATH_OPTIONS:
                    opaque = True
                    break
                for owner, attr in args:
                    if root is None:
                        root = owner
                    path.extend(attr.split("."))
                    if loader in _EAGER_OPTIONS:
                        loaded.add(f"{root or src.root}:{'.'.join(path)}")
            # A raiseload/noload/eager ``"*"`` wildcard is recorded as such.
        return replace(src, loaded=frozenset(loaded), opaque=opaque)


def _loader_steps(opt: ast.expr) -> list[tuple[str, list[tuple[str | None, str]]]] | None:
    """``selectinload(User.posts).joinedload(Post.author)`` →
    ``[("selectinload", [("User", "posts")]), ("joinedload", [("Post", "author")])]``.
    ``None`` when the option is not a readable loader chain."""
    steps: list[tuple[str, list[tuple[str | None, str]]]] = []
    cursor: ast.AST = opt
    while isinstance(cursor, ast.Call):
        func = cursor.func
        name = _tail(func)
        if name is None:
            return None
        args: list[tuple[str | None, str]] = []
        if name == "Load":
            if cursor.args and isinstance(cursor.args[0], ast.Name):
                args = [(cursor.args[0].id, "")]
        elif name not in _COLUMN_OPTIONS:
            for a in cursor.args:
                parsed = _path_arg(a)
                if parsed is None:
                    return None
                args.append(parsed)
        steps.append((name, args))
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Call):
            cursor = func.value
            continue
        break
    else:
        return None
    steps.reverse()
    return steps


def _path_arg(node: ast.AST) -> tuple[str | None, str] | None:
    """``User.posts`` → ``("User", "posts")``; ``"posts.comments"`` → ``(None, ...)``."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in (
        "of_type", "and_"
    ):
        node = node.func.value
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return None, node.value
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id, node.attr
    return None


def _covered(src: _Src, path: tuple[str, ...]) -> bool:
    joined = ".".join(path)
    parent = ".".join(path[:-1])
    star = f"{parent}.*" if parent else "*"
    return f"{src.root}:{joined}" in src.loaded or f"{src.root}:{star}" in src.loaded


def _accesses(body: Iterable[ast.AST], var: str) -> list[tuple[str, ...]]:
    """Attribute chains read off ``var`` (``var.a.b`` → ``("a", "b")``).

    The last name is dropped when it is a method called on the chain or the
    target of an assignment/``del``: ``var.save()`` and ``var.owner = x``
    do not read a relationship, ``var.owner.name = x`` still reads ``owner``.
    Nested functions and lambdas are skipped.
    """
    out: list[tuple[str, ...]] = []

    def chain(node: ast.Attribute) -> tuple[list[str], ast.AST]:
        parts: list[str] = []
        cursor: ast.AST = node
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        parts.reverse()
        return parts, cursor

    def visit(node: ast.AST, called: bool = False) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return
        if isinstance(node, ast.Call):
            visit(node.func, called=True)
            for a in node.args:
                visit(a)
            for kw in node.keywords:
                visit(kw.value)
            return
        if isinstance(node, ast.Attribute):
            parts, root = chain(node)
            if isinstance(root, ast.Name) and root.id == var:
                if called or not isinstance(node.ctx, ast.Load):
                    parts = parts[:-1]
                if parts:
                    out.append(tuple(parts))
                return
            visit(root)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    for stmt in body:
        visit(stmt)
    return out


class _FunctionScanner:
    def __init__(self, ev: _Evaluator, schema: _Schema, file: str) -> None:
        self.ev = ev
        self.schema = schema
        self.file = file
        self.findings: list[NPlusOneFinding] = []

    def run(self, body: list[ast.stmt]) -> None:
        self._block(body, {})

    def _block(self, body: list[ast.stmt], env: dict[str, _Src]) -> None:
        for stmt in body:
            self._stmt(stmt, env)

    def _stmt(self, stmt: ast.stmt, env: dict[str, _Src]) -> None:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return  # scanned on their own
        self._comprehensions(stmt, env)
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            value = stmt.value
            src = self.ev.eval(value, env) if value is not None else None
            for t in targets:
                if isinstance(t, ast.Name):
                    if src is not None:
                        env[t.id] = src
                    else:
                        env.pop(t.id, None)
            return
        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            self._loop(stmt, env)
            return
        for field_name in ("body", "orelse", "finalbody"):
            block = getattr(stmt, field_name, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                self._block(block, env)
        for handler in getattr(stmt, "handlers", []) or []:
            self._block(handler.body, env)
        for case in getattr(stmt, "cases", []) or []:
            self._block(case.body, env)

    def _element_bindings(self, src: _Src | None, target: ast.AST) -> dict[str, _Src]:
        if src is None:
            return {}
        if isinstance(target, ast.Name):
            if src.kind in ("seq", "query", "page"):
                return {target.id: replace(src, kind="one")}
            return {}
        if src.kind == "enumerate":
            if (
                isinstance(target, (ast.Tuple, ast.List))
                and len(target.elts) == 2
                and isinstance(target.elts[1], ast.Name)
            ):
                return {target.elts[1].id: replace(src, kind="one")}
            return {}
        if isinstance(target, (ast.Tuple, ast.List)) and src.kind == "rows":
            out = {}
            for i, elt in enumerate(target.elts):
                if (
                    isinstance(elt, ast.Name)
                    and i < len(src.entities)
                    and src.entities[i]
                    and src.prefix == ()
                ):
                    entity = src.entities[i]
                    assert entity is not None
                    out[elt.id] = replace(src, kind="one", model=entity, root=entity)
            return out
        return {}

    def _loop(self, loop: ast.For | ast.AsyncFor, env: dict[str, _Src]) -> None:
        src = self.ev.eval(loop.iter, env)
        bindings = self._element_bindings(src, loop.target)
        for var, elem in bindings.items():
            self._report(loop.lineno, var, elem, _accesses(loop.body, var), loop.iter)
        inner = dict(env)
        for name in _target_names(loop.target):
            inner.pop(name, None)
        inner.update(bindings)
        self._block(loop.body, inner)
        # A name the body rebinds may hold anything after the loop
        # (``q = helper(q)`` per filter): stop trusting it.
        for name in _assigned_names(loop.body):
            if inner.get(name) is not env.get(name):
                env.pop(name, None)
        self._block(loop.orelse, env)

    def _comprehensions(self, stmt: ast.stmt, env: dict[str, _Src]) -> None:
        for node in _walk_no_defs(stmt, skip_loops=True):
            if not isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                continue
            local = dict(env)
            for gen in node.generators:
                src = self.ev.eval(gen.iter, local)
                bindings = self._element_bindings(src, gen.target)
                if isinstance(node, ast.DictComp):
                    exprs: list[ast.AST] = [node.key, node.value]
                else:
                    exprs = [node.elt]
                rest = [g for g in node.generators if g is not gen]
                for var, elem in bindings.items():
                    nodes: list[ast.AST] = [*exprs, *gen.ifs]
                    for g in rest:
                        nodes.extend([g.iter, *g.ifs])
                    self._report(node.lineno, var, elem, _accesses(nodes, var), gen.iter)
                local.update(bindings)

    def _report(
        self,
        line: int,
        var: str,
        elem: _Src,
        chains: list[tuple[str, ...]],
        iter_node: ast.AST,
    ) -> None:
        if elem.opaque:
            return
        accessed: list[str] = []
        fixes: list[str] = []
        collection_hit = False
        back = self._back_to_parent(elem)
        for parts in chains:
            model = elem.model
            hops: list[tuple[str, ParsedRelationship]] = []
            for attr in parts:
                rel = self.schema.rel(model, attr)
                if rel is None or not rel.target:
                    break
                hops.append((model, rel))
                path = (*elem.prefix, *(h[1].name for h in hops))
                # ``for post in user.posts: post.author`` is ``user`` again,
                # already in the identity map: no query.
                parent = len(hops) == 1 and attr in back and rel.collection is False
                if not parent and not _covered(elem, path) and rel.lazy not in _NOT_PER_ROW:
                    label = ".".join(h[1].name for h in hops)
                    if label not in accessed:
                        accessed.append(label)
                        fixes.append(self._fix(elem, hops))
                        if rel.collection:
                            collection_hit = True
                    break
                model = rel.target
        if not accessed:
            return
        self.findings.append(
            NPlusOneFinding(
                file=self.file,
                line=line,
                loop_var=var,
                queryset_var=_label(iter_node),
                accessed=accessed,
                suggested_fix=f".options({', '.join(fixes)})",
                confidence="high" if collection_hit else "medium",
            )
        )

    def _back_to_parent(self, elem: _Src) -> set[str]:
        """Attributes of a nested loop's rows that lead back to the parent."""
        if not elem.prefix:
            return set()
        model = elem.root
        owner = model
        rel = None
        for attr in elem.prefix:
            rel = self.schema.rel(model, attr)
            if rel is None or not rel.target:
                return set()
            owner, model = model, rel.target
        assert rel is not None
        names = {n for n in (rel.back_populates, rel.backref) if n}
        for other in self.schema.rels.get(elem.model, {}).values():
            if other.back_populates == rel.name and other.target == owner:
                names.add(other.name)
        return names

    def _fix(self, elem: _Src, hops: list[tuple[str, ParsedRelationship]]) -> str:
        # The option goes on the query that produced the root rows, so the
        # path starts there even for a loop over ``user.posts``.
        steps: list[str] = []
        model = elem.root
        for attr in elem.prefix:
            rel = self.schema.rel(model, attr)
            if rel is None or not rel.target:
                break
            steps.append(f"{'selectinload' if rel.collection else 'joinedload'}({model}.{attr})")
            model = rel.target
        for owner, rel in hops:
            steps.append(
                f"{'selectinload' if rel.collection else 'joinedload'}({owner}.{rel.name})"
            )
        return ".".join(steps)


def _target_names(target: ast.AST) -> list[str]:
    return [n.id for n in ast.walk(target) if isinstance(n, ast.Name)]


def _assigned_names(body: list[ast.stmt]) -> set[str]:
    names: set[str] = set()
    for stmt in body:
        for node in _walk_no_defs(stmt):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    names.update(_target_names(t))
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                names.update(_target_names(node.target))
    return names


def _walk_no_defs(node: ast.AST, skip_loops: bool = False) -> Iterable[ast.AST]:
    """``ast.walk`` that stays out of nested defs and, optionally, out of the
    bodies of nested statements (those are visited as statements)."""
    stack = [node]
    first = True
    while stack:
        cur = stack.pop()
        if not first and isinstance(
            cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        if not first and skip_loops and isinstance(cur, ast.stmt):
            continue
        first = False
        yield cur
        stack.extend(ast.iter_child_nodes(cur))


def _scopes(tree: ast.Module) -> Iterable[list[ast.stmt]]:
    yield tree.body
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.body


def scan_source(
    source: str, file: str, index: WorkspaceIndex | _Schema
) -> list[NPlusOneFinding]:
    """Findings for one file's source (``file`` is the path to report)."""
    schema = index if isinstance(index, _Schema) else _Schema(index)
    if not schema.rels or _ALEMBIC_REVISION_RE.search(source):
        return []
    try:
        tree = parse_source(source)
    except (SyntaxError, ValueError):
        return []
    scanner = _FunctionScanner(_Evaluator(schema), schema, file)
    for body in _scopes(tree):
        try:
            scanner.run(body)
        except RecursionError:  # pragma: no cover - pathological nesting
            continue
    return scanner.findings


def scan_all_nplusone(
    project_root: str, index: WorkspaceIndex, include_tests: bool = False
) -> list[NPlusOneFinding]:
    """Django and SQLAlchemy N+1 findings for one workspace.

    ``index`` should come from ``scan_workspace(..., include_sqlalchemy=True)``.
    Each detector gets its own ORM's models. When the workspace has
    SQLAlchemy models and no Django ones, the Django detector does not run:
    its schema-less heuristics would read SQLAlchemy loops as querysets and
    suggest ``select_related``. In a mixed workspace it skips the files that
    are SQLAlchemy code.
    """
    from .query_analyzer import scan_for_nplusone

    django = index.only("django")
    sqlalchemy = index.only("sqlalchemy")
    findings: list[NPlusOneFinding] = []
    # A Django "model" without a single field next to real SQLAlchemy models
    # is a helper class the Django parser's name heuristics let through
    # (``class AnonymousUser(AnonymousUserMixin)``), not a Django project.
    has_django = any(m.all_fields() for app in django.apps for m in app.models)
    if has_django or not sqlalchemy.apps:
        findings.extend(
            scan_for_nplusone(
                project_root,
                django,
                include_tests=include_tests,
                skip_sqlalchemy_files=bool(sqlalchemy.apps),
            )
        )
    if sqlalchemy.apps:
        findings.extend(
            scan_sqlalchemy_nplusone(project_root, sqlalchemy, include_tests=include_tests)
        )
    return findings


def scan_sqlalchemy_nplusone(
    project_root: str, index: WorkspaceIndex, include_tests: bool = False
) -> list[NPlusOneFinding]:
    """Walk ``project_root`` and return SQLAlchemy N+1 findings.

    ``index`` supplies the mapped classes and their relationships (from
    ``scan_workspace(..., include_sqlalchemy=True)``); Django models in it
    are ignored. Test modules are skipped unless ``include_tests``.
    """
    root = Path(project_root).resolve()
    if not root.is_dir():
        return []
    schema = _Schema(index)
    if not schema.rels:
        return []
    findings: list[NPlusOneFinding] = []
    for py in _iter_py_files_broad(root):
        try:
            rel = py.relative_to(root)
        except ValueError:
            rel = py
        if not include_tests and _is_test_file(rel):
            continue
        try:
            source = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "for " not in source or not _PREFILTER_RE.search(source):
            continue
        findings.extend(scan_source(source, _rel_posix(root, py), schema))
    return findings

