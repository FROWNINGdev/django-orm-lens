"""Static QuerySet usage analyzer — pure AST, no Django boot, no DB.

Walks every ``.py`` file in the workspace (skipping ``migrations/``, ``venv/``,
``node_modules/``, ``.git/`` and other hidden dirs) and extracts every call
of the form ``<ModelClassName>.objects.<qs_method>(...)`` where ``qs_method``
is one of ``filter``, ``exclude``, ``get``, ``order_by``, ``aggregate``.

Captured signals per usage site:
* keyword-arg names (field names, dropping ``__lookup`` suffixes)
* positional ``order_by`` string args (preserving the ``-`` prefix)
* ``advanced=True`` flag when the call contains a positional non-string
  arg (typically ``Q()``/``F()`` expressions) that we don't statically
  decompose

The analyzer proposes ``Meta.indexes`` entries by frequency:
* every field used in >=2 filter/exclude sites → single-field index candidate
* every co-occurrence in the SAME filter/exclude call → composite candidate
* every field appearing in >=2 order_by sites → order_by index candidate

Existing ``Meta.indexes`` are read from the parser output and returned so
callers can dedupe suggestions the user has already covered.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import (
    WorkspaceIndex,
    find_user_model,
    find_user_model_from_dict,
    resolve_related_tail,
)

QS_METHODS = frozenset({"filter", "exclude", "get", "order_by", "aggregate"})


def _iter_py_files(root: Path) -> Iterable[Path]:
    from .parser import iter_workspace_py_files  # local to avoid cycles
    return iter_workspace_py_files(root)


def _root_field(kwarg: str) -> str:
    """``user__email__iexact`` → ``user``. Plain ``user`` stays ``user``."""
    return kwarg.split("__", 1)[0]


def _order_field(raw: str) -> str:
    """Normalise ``-created_at`` / ``created_at`` — keep the ``-`` prefix but
    strip any ``__`` lookup tail (rare but appears in ``order_by`` on JSONField)."""
    prefix = ""
    body = raw
    if body.startswith("-"):
        prefix = "-"
        body = body[1:]
    body = body.split("__", 1)[0]
    return prefix + body


def _unwrap_call_chain(node: ast.Call) -> list[ast.Call]:
    """For ``Foo.objects.filter(a=1).filter(b=2).order_by('c')`` return every
    Call node in the chain, outermost last. The receiver root (``Foo.objects``)
    must be identified separately via :func:`_chain_root`.
    """
    chain: list[ast.Call] = []
    cursor: ast.AST = node
    while isinstance(cursor, ast.Call):
        chain.append(cursor)
        func = cursor.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Call):
            cursor = func.value
        else:
            break
    chain.reverse()
    return chain


def _chain_root(outermost: ast.Call) -> tuple[str, ast.Attribute] | None:
    """Return ``(ModelClassName, .objects_attr_node)`` for the leftmost
    ``<Model>.objects`` in the chain, or ``None`` if the chain doesn't start
    with a ``<Name>.objects`` pattern.
    """
    cursor: ast.AST = outermost
    while isinstance(cursor, ast.Call):
        func = cursor.func
        if not isinstance(func, ast.Attribute):
            return None
        inner = func.value
        if isinstance(inner, ast.Call):
            cursor = inner
            continue
        # inner should be <Model>.objects
        if (
            isinstance(inner, ast.Attribute)
            and inner.attr == "objects"
            and isinstance(inner.value, ast.Name)
        ):
            return inner.value.id, inner
        return None
    return None


def _kwarg_names(call: ast.Call) -> list[str]:
    return [kw.arg for kw in call.keywords if kw.arg is not None]


def _order_by_positionals(call: ast.Call) -> tuple[list[str], bool]:
    """Return (list of order_by strings, has_non_string_positional)."""
    strings: list[str] = []
    has_expr = False
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            strings.append(arg.value)
        else:
            has_expr = True
    return strings, has_expr


def _has_positional_expr(call: ast.Call) -> bool:
    """True if any positional arg exists that isn't a plain string constant
    — flags Q() / F() / subquery style advanced usage."""
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            continue
        return True
    return False


def _rel(root: Path, path: Path, line: int) -> str:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.as_posix()
    return f"{rel}:{line}"


def _existing_meta_indexes(meta: dict[str, str]) -> list[list[str]]:
    """Best-effort parse of ``Meta.indexes = [models.Index(fields=[...]), ...]``.

    ``meta`` values are raw source snippets (see parser). We regex the
    ``fields=[...]`` bit and pull each quoted field name. Returns a list of
    field-name lists (order preserved). Non-parseable entries are skipped.
    """
    raw = meta.get("indexes")
    if not raw:
        return []
    out: list[list[str]] = []
    for m in re.finditer(r"fields\s*=\s*\[([^\]]*)\]", raw):
        body = m.group(1)
        fields = re.findall(r"['\"]([^'\"]+)['\"]", body)
        if fields:
            out.append(fields)
    return out


class _Collector(ast.NodeVisitor):
    def __init__(self, target_name: str, file_path: Path, root: Path) -> None:
        self.target = target_name
        self.file_path = file_path
        self.root = root
        # per-method usage rows
        self.filter_sites: list[dict[str, Any]] = []
        self.exclude_sites: list[dict[str, Any]] = []
        self.get_sites: list[dict[str, Any]] = []
        self.order_by_sites: list[dict[str, Any]] = []
        self.aggregate_sites: list[dict[str, Any]] = []
        # visited call-node ids so we don't double-count nested chain calls
        self._visited: set[int] = set()

    def visit_Call(self, node: ast.Call) -> None:
        if id(node) not in self._visited:
            self._maybe_process_chain(node)
        self.generic_visit(node)

    def _maybe_process_chain(self, outermost: ast.Call) -> None:
        root = _chain_root(outermost)
        if root is None:
            return
        model_name, _root_attr = root
        if model_name != self.target:
            return
        chain = _unwrap_call_chain(outermost)
        for call in chain:
            self._visited.add(id(call))
        for call in chain:
            self._record(call)

    def _record(self, call: ast.Call) -> None:
        func = call.func
        if not isinstance(func, ast.Attribute):
            return
        method = func.attr
        if method not in QS_METHODS:
            return
        site = _rel(self.root, self.file_path, call.lineno)

        if method in ("filter", "exclude", "get"):
            kwargs = _kwarg_names(call)
            fields = [_root_field(k) for k in kwargs]
            advanced = _has_positional_expr(call)
            row: dict[str, Any] = {
                "site": site,
                "fields": fields,
            }
            if advanced:
                row["advanced"] = True
            if method == "filter":
                self.filter_sites.append(row)
            elif method == "exclude":
                self.exclude_sites.append(row)
            else:
                self.get_sites.append(row)
        elif method == "order_by":
            strings, has_expr = _order_by_positionals(call)
            row = {
                "site": site,
                "fields": [_order_field(s) for s in strings],
            }
            if has_expr:
                row["advanced"] = True
            self.order_by_sites.append(row)
        elif method == "aggregate":
            kwargs = _kwarg_names(call)
            row = {
                "site": site,
                "fields": [_root_field(k) for k in kwargs if k],
            }
            if _has_positional_expr(call):
                row["advanced"] = True
            self.aggregate_sites.append(row)


def _summarise_filter_like(
    sites: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (single_field_usages, composite_usages) for filter/exclude/get.

    * single_field_usages: one row per distinct field, with occurrence count
      across all sites (each field counted once per site).
    * composite_usages: one row per distinct multi-field combo that appears
      in a single call, with occurrence count across sites.
    """
    single_counts: dict[str, int] = defaultdict(int)
    single_example: dict[str, str] = {}
    composite_counts: dict[tuple[str, ...], int] = defaultdict(int)
    composite_example: dict[tuple[str, ...], str] = {}

    for row in sites:
        fields = row["fields"]
        seen_this_site: set[str] = set()
        for f in fields:
            if f in seen_this_site:
                continue
            seen_this_site.add(f)
            single_counts[f] += 1
            single_example.setdefault(f, row["site"])
        if len(seen_this_site) >= 2:
            combo = tuple(sorted(seen_this_site))
            composite_counts[combo] += 1
            composite_example.setdefault(combo, row["site"])

    singles = [
        {"field": field, "sites": count, "example": single_example[field]}
        for field, count in sorted(
            single_counts.items(), key=lambda kv: (-kv[1], kv[0])
        )
    ]
    composites = [
        {
            "field": list(combo),
            "sites": count,
            "example": composite_example[combo],
            "composite": True,
        }
        for combo, count in sorted(
            composite_counts.items(), key=lambda kv: (-kv[1], kv[0])
        )
    ]
    return singles, composites


def _summarise_order_by(sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    example: dict[str, str] = {}
    for row in sites:
        for f in row["fields"]:
            counts[f] += 1
            example.setdefault(f, row["site"])
    return [
        {"field": f, "sites": c, "example": example[f]}
        for f, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _propose_indexes(
    filter_singles: list[dict[str, Any]],
    filter_composites: list[dict[str, Any]],
    order_by_summary: list[dict[str, Any]],
    existing: list[list[str]],
) -> list[dict[str, Any]]:
    """Turn the frequency tables into concrete ``Meta.indexes`` suggestions.

    Rules:
    * composite filter combos with >=2 sites take priority over their
      individual-field siblings (a composite index covers single-field
      lookups on the leading column too).
    * single-field filter usage needs >=2 sites to warrant its own index.
    * every order_by field with >=2 sites gets a proposal (unless already
      covered by an existing index whose leading field matches).

    Existing ``Meta.indexes`` are dedup'd by exact field-list match.
    """
    existing_set = {tuple(x) for x in existing}
    proposed: list[dict[str, Any]] = []
    covered_leaders: set[str] = set()

    for combo in filter_composites:
        if combo["sites"] < 2:
            continue
        fields = combo["field"]
        key = tuple(fields)
        if key in existing_set:
            continue
        proposed.append(
            {
                "fields": fields,
                "reason": f"{combo['sites']} composite filter sites",
            }
        )
        covered_leaders.add(fields[0])

    for single in filter_singles:
        if single["sites"] < 2:
            continue
        field = single["field"]
        key = (field,)
        if key in existing_set:
            continue
        if field in covered_leaders:
            continue
        proposed.append(
            {
                "fields": [field],
                "reason": f"{single['sites']} filter sites",
            }
        )

    for row in order_by_summary:
        if row["sites"] < 2:
            continue
        field = row["field"]
        key = (field,)
        if key in existing_set:
            continue
        # Don't duplicate an existing filter proposal on the same bare field
        if any(p["fields"] == [field] for p in proposed):
            continue
        proposed.append(
            {
                "fields": [field],
                "reason": f"{row['sites']} order_by sites",
            }
        )

    return proposed


def suggest_indexes(
    app_label: str,
    model_name: str,
    root: str,
    index: WorkspaceIndex | None = None,
) -> dict[str, Any]:
    """Analyse the workspace for QuerySet usage of ``app_label.model_name``.

    Returns the dict shape documented in the MCP tool spec. If the model
    isn't found in the parsed workspace, returns an ``error`` key rather
    than raising — matches the existing tool conventions.
    """
    from .parser import DEFAULT_EXCLUDES, scan_workspace

    if index is None:
        index = scan_workspace(root, DEFAULT_EXCLUDES)

    # Resolve target model (case-sensitive on class name, case-sensitive app).
    target_model = None
    for app in index.apps:
        if app.name != app_label:
            continue
        for m in app.models:
            if m.name == model_name:
                target_model = m
                break
        if target_model:
            break

    if target_model is None:
        return {
            "target": f"{app_label}.{model_name}",
            "error": "model not found in workspace",
        }

    root_path = Path(root).resolve()
    collector = None

    all_filter: list[dict[str, Any]] = []
    all_exclude: list[dict[str, Any]] = []
    all_get: list[dict[str, Any]] = []
    all_order_by: list[dict[str, Any]] = []
    all_aggregate: list[dict[str, Any]] = []

    for py in _iter_py_files(root_path):
        try:
            source = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Cheap textual pre-filter — skip files that don't mention the model
        # name at all. Massive speed-up on large workspaces.
        if model_name not in source:
            continue
        try:
            tree = ast.parse(source, filename=str(py))
        except SyntaxError:
            continue
        collector = _Collector(model_name, py, root_path)
        collector.visit(tree)
        all_filter.extend(collector.filter_sites)
        all_exclude.extend(collector.exclude_sites)
        all_get.extend(collector.get_sites)
        all_order_by.extend(collector.order_by_sites)
        all_aggregate.extend(collector.aggregate_sites)

    filter_singles, filter_composites = _summarise_filter_like(
        all_filter + all_exclude + all_get
    )
    order_by_summary = _summarise_order_by(all_order_by)
    aggregate_summary = _summarise_order_by(all_aggregate)  # same shape

    existing = _existing_meta_indexes(target_model.meta)
    proposed = _propose_indexes(
        filter_singles, filter_composites, order_by_summary, existing
    )

    filter_usages: list[dict[str, Any]] = list(filter_singles)
    filter_usages.extend(filter_composites)

    return {
        "target": f"{app_label}.{model_name}",
        "filter_usages": filter_usages,
        "exclude_usages": _sites_to_summary(all_exclude),
        "get_usages": _sites_to_summary(all_get),
        "order_by_usages": order_by_summary,
        "aggregate_usages": aggregate_summary,
        "proposed_indexes": proposed,
        "existing_meta_indexes": existing,
    }


def _sites_to_summary(sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact per-field summary of an exclude/get bucket."""
    counts: dict[str, int] = defaultdict(int)
    example: dict[str, str] = {}
    for row in sites:
        seen: set[str] = set()
        for f in row["fields"]:
            if f in seen:
                continue
            seen.add(f)
            counts[f] += 1
            example.setdefault(f, row["site"])
    return [
        {"field": f, "sites": c, "example": example[f]}
        for f, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


# ---------------------------------------------------------------------------
# N+1 detector
# ---------------------------------------------------------------------------
#
# The detector walks every ``.py`` file in the workspace (skipping the same
# directories the index analyzer skips), finds ``for ... in <queryset>:``
# loops, and flags attribute-chain accesses against the loop target that
# hit a related object (ForeignKey / OneToOne / ManyToMany / reverse FK)
# without a corresponding ``select_related`` / ``prefetch_related`` clause
# on the source queryset.
#
# Heuristic: if the schema is provided, only known relation attributes on
# the loop-target's model trigger high-confidence findings. Without a
# schema (or when the source model can't be resolved) the detector falls
# back to structural cues (``.all()`` / ``_set`` suffix / long attribute
# chains) at medium confidence.

# QuerySet source methods that (a) commonly return a lazily-evaluated
# queryset iterated in a for-loop, and (b) accept ``select_related`` /
# ``prefetch_related`` chains after them.
_QS_SOURCE_METHODS = frozenset({
    "all", "filter", "exclude", "annotate", "distinct", "order_by",
    "values", "values_list", "reverse", "none", "iterator",
    "only", "defer", "using",
})

# When the attribute name matches this suffix pattern we treat it as a
# reverse FK / M2M reverse manager (``post.comment_set.all()`` etc.) so
# even without a schema we can confidently flag it.
_REVERSE_MANAGER_SUFFIX = re.compile(r"_set$")


@dataclass
class NPlusOneFinding:
    """A single N+1 anti-pattern finding.

    All paths are project-root relative (POSIX separators) so tools can
    render clickable ``path:line`` links irrespective of the host OS.
    """

    file: str
    line: int
    loop_var: str
    queryset_var: str
    accessed: list[str]
    suggested_fix: str
    confidence: str  # "high" | "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rel_posix(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_py_files_broad(root: Path) -> Iterable[Path]:
    """Like :func:`_iter_py_files` but also skips ``site-packages`` and any
    directory named after a common vendored-dep root. Used by the N+1
    scanner which walks every ``.py`` file, not just ``models.py``.
    """
    from .parser import iter_workspace_py_files  # local to avoid cycles
    return iter_workspace_py_files(
        root, extra_skip=frozenset({"site-packages", "dist", "build", "eggs"})
    )


def _attr_chain(node: ast.AST) -> list[str] | None:
    """Flatten an ``ast.Attribute`` chain rooted at an ``ast.Name`` into a
    ``[name, attr1, attr2, ...]`` list. Returns ``None`` when the root
    isn't a plain ``ast.Name``.
    """
    parts: list[str] = []
    cursor: ast.AST = node
    while isinstance(cursor, ast.Attribute):
        parts.append(cursor.attr)
        cursor = cursor.value
    if not isinstance(cursor, ast.Name):
        return None
    parts.append(cursor.id)
    parts.reverse()
    return parts


def _call_method_name(node: ast.Call) -> str | None:
    """Return the method name of a method-call ``x.y(...)`` — i.e. the
    ``y``. Returns ``None`` for bare-function calls (``f(...)``).
    """
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _collect_call_chain_methods(node: ast.AST) -> list[tuple[str, ast.Call]]:
    """Walk backwards through a method-chain ``a.b().c().d()`` and yield
    ``(method_name, call_node)`` tuples in call order (innermost first).

    This is a superset of :func:`_unwrap_call_chain` — it handles chains
    where the root isn't a ``Call`` (e.g. ``qs.filter(x=1).all()`` where
    ``qs`` is a bare Name). Used by the N+1 scanner to walk any chain
    hanging off a queryset variable.
    """
    out: list[tuple[str, ast.Call]] = []
    cursor: ast.AST = node
    while isinstance(cursor, ast.Call):
        method = _call_method_name(cursor)
        if method is None:
            break
        out.append((method, cursor))
        func = cursor.func
        if isinstance(func, ast.Attribute):
            cursor = func.value
        else:
            break
    out.reverse()
    return out


def _chain_prefetch_args(
    chain: list[tuple[str, ast.Call]],
) -> tuple[set[str], set[str]]:
    """Collect all string literal args passed to ``select_related`` /
    ``prefetch_related`` calls in ``chain``. Returns ``(select, prefetch)``.

    ``.select_related()`` with no args is a "follow every FK" spanner —
    represented by the wildcard token ``"*"``. Same for ``.prefetch_related()``
    which is uncommon but valid.
    """
    select_set: set[str] = set()
    prefetch_set: set[str] = set()
    for method, call in chain:
        if method == "select_related":
            if not call.args and not call.keywords:
                select_set.add("*")
            for arg in call.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    select_set.add(arg.value.split("__", 1)[0])
        elif method == "prefetch_related":
            if not call.args and not call.keywords:
                prefetch_set.add("*")
            for arg in call.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    prefetch_set.add(arg.value.split("__", 1)[0])
                # Prefetch("comments", queryset=...) → first positional arg is the lookup
                elif isinstance(arg, ast.Call):
                    for inner in arg.args:
                        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                            prefetch_set.add(inner.value.split("__", 1)[0])
                            break
    return select_set, prefetch_set


def _chain_model_root(chain: list[tuple[str, ast.Call]]) -> str | None:
    """If the chain begins at ``<Model>.objects.<method>(...)`` return
    ``Model``, else ``None``.
    """
    if not chain:
        return None
    _method, first_call = chain[0]
    func = first_call.func
    if not isinstance(func, ast.Attribute):
        return None
    inner = func.value
    if (
        isinstance(inner, ast.Attribute)
        and inner.attr == "objects"
        and isinstance(inner.value, ast.Name)
    ):
        return inner.value.id
    return None


def _chain_source_method(chain: list[tuple[str, ast.Call]]) -> str | None:
    """First method name in the chain (``all`` / ``filter`` / ...)."""
    if not chain:
        return None
    return chain[0][0]


class _QuerySetTracker(ast.NodeVisitor):
    """Collects assignments of the form ``qs = <Model>.objects.<chain>``
    within a single AST. Later loops that iterate ``qs`` are cross-checked
    against the captured chain to see if it already has select/prefetch.

    Only the most recent binding of each name is kept — a simple
    approximation, but adequate for the common patterns this detector
    targets (view functions where each qs variable is a fresh assignment).
    """

    def __init__(self) -> None:
        # name -> (chain, model_root_name_or_None)
        self.bindings: dict[str, tuple[list[tuple[str, ast.Call]], str | None]] = {}

    def visit_Assign(self, node: ast.Assign) -> None:
        chain = _collect_call_chain_methods(node.value)
        if chain:
            model_root = _chain_model_root(chain)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.bindings[target.id] = (chain, model_root)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            chain = _collect_call_chain_methods(node.value)
            if chain and isinstance(node.target, ast.Name):
                model_root = _chain_model_root(chain)
                self.bindings[node.target.id] = (chain, model_root)
        self.generic_visit(node)


def _iter_returns(node: ast.AST) -> Iterable[ast.Return]:
    """Yield ``return`` statements belonging to *this* function only.

    ``ast.walk`` would happily hand back a nested helper's returns and
    attribute them to the outer function, which is exactly the sort of
    quietly-wrong resolution this detector must not do.
    """
    stack = list(getattr(node, "body", []))
    while stack:
        cur = stack.pop()
        if isinstance(
            cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        if isinstance(cur, ast.Return):
            yield cur
        for field_name in ("body", "orelse", "finalbody", "handlers"):
            stack.extend(getattr(cur, field_name, []) or [])


def _helper_call_name(node: ast.AST) -> tuple[str | None, bool]:
    """Innermost callee of a call chain, when it is a plain helper.

    Returns ``(name, already_in_chain)``:

    * ``recent()`` / ``recent().select_related(...)`` → ``("recent", False)``.
      A bare-``Name`` call has no attribute to name it, so
      :func:`_collect_call_chain_methods` never records it — the caller must
      not drop a chain element for it.
    * ``self.get_queryset()`` → ``("get_queryset", True)``. This one *is*
      recorded as the first chain element, so the caller drops it before
      splicing the helper's own chain in.
    * ``Post.objects.filter()`` → ``(None, False)``. Model-rooted chains are
      resolved the normal way and must not come through here.
    """
    cursor: ast.AST = node
    while isinstance(cursor, ast.Call):
        func = cursor.func
        if isinstance(func, ast.Name):
            return func.id, False
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id in ("self", "cls"):
                return func.attr, True
            cursor = func.value
            continue
        break
    return None, False


class _ReturnedQuerySetTracker(ast.NodeVisitor):
    """Maps a function or method name to the QuerySet chain it returns.

    This is what lifts the detector out of one function at a time. The shape
    it exists for is ordinary Django::

        def recent():
            return Post.objects.filter(published=True)

        for post in recent():          # <- source is a call, not a chain
            print(post.author.name)    # <- still an N+1

    Resolution is by bare name and deliberately shallow: one hop, same
    module, first return that yields a chain. ``self.get_queryset()`` matches
    a ``get_queryset`` defined anywhere in the file, which is right for the
    overwhelmingly common one-view-per-name case.
    """

    def __init__(self) -> None:
        # name -> (chain, model_root_name_or_None)
        self.returns: dict[str, tuple[list[tuple[str, ast.Call]], str | None]] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name not in self.returns:
            resolved = self._resolve(node)
            if resolved is not None:
                self.returns[node.name] = resolved
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    @staticmethod
    def _resolve(
        node: ast.FunctionDef,
    ) -> tuple[list[tuple[str, ast.Call]], str | None] | None:
        local = _QuerySetTracker()
        for stmt in getattr(node, "body", []):
            local.visit(stmt)
        for ret in _iter_returns(node):
            if ret.value is None:
                continue
            # `return Post.objects.filter(...)`
            chain = _collect_call_chain_methods(ret.value)
            model_root = _chain_model_root(chain)
            if chain and (
                model_root is not None
                or _chain_source_method(chain) in _QS_SOURCE_METHODS
            ):
                return (chain, model_root)
            # `qs = Post.objects.all(); ...; return qs`
            if isinstance(ret.value, ast.Name):
                binding = local.bindings.get(ret.value.id)
                if binding is not None:
                    return binding
        return None


class NPlusOneScanner(ast.NodeVisitor):
    """AST scanner that emits :class:`NPlusOneFinding` records for a file.

    Usage::

        scanner = NPlusOneScanner(file_path, project_root, models_schema)
        scanner.visit(tree)
        findings = scanner.findings

    ``models_schema``, when provided, is a mapping ``{ModelName: {attr: kind}}``
    where ``kind`` is one of ``"fk"``, ``"o2o"``, ``"m2m"``, ``"reverse"``,
    ``"scalar"``. Used to promote medium -> high confidence and to filter out
    scalar-attribute false positives.
    """

    def __init__(
        self,
        file_path: Path,
        project_root: Path,
        models_schema: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.file_path = file_path
        self.project_root = project_root
        self.models_schema = models_schema or {}
        self.findings: list[NPlusOneFinding] = []
        # QuerySet name bindings from the module scope. We refresh this at
        # every function/class boundary for a mild scope-awareness.
        self._tracker = _QuerySetTracker()
        # Module-wide map of helper name -> the QuerySet chain it returns, so
        # `for p in recent():` is analysable and not silently skipped.
        self._returns = _ReturnedQuerySetTracker()

    # -- entry points ------------------------------------------------------

    def visit_Module(self, node: ast.Module) -> None:
        self._tracker.visit(node)
        # Whole-module pass first: a loop may call a helper defined further
        # down the file, and textual order must not decide what we can see.
        self._returns.visit(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Track bindings that appear inside this function BEFORE we start
        # walking loops — otherwise a loop that precedes its ``qs = ...``
        # binding textually would miss the chain (rare, but the analysis
        # is cheap enough to do twice).
        local_tracker = _QuerySetTracker()
        local_tracker.bindings = dict(self._tracker.bindings)
        local_tracker.visit(node)
        prev = self._tracker
        self._tracker = local_tracker
        try:
            self.generic_visit(node)
        finally:
            self._tracker = prev

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_For(self, node: ast.For) -> None:
        self._process_loop(node)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._process_loop(node)
        self.generic_visit(node)

    # -- core --------------------------------------------------------------

    def _process_loop(self, loop: ast.For | ast.AsyncFor) -> None:
        target = getattr(loop, "target", None)
        iter_node = getattr(loop, "iter", None)
        body = getattr(loop, "body", [])
        if not isinstance(target, ast.Name) or iter_node is None:
            return
        loop_var = target.id

        # 1. Resolve the queryset source: either a bare Name (look up in
        #    tracker) or an inline chain (``for x in Foo.objects.all():``).
        chain: list[tuple[str, ast.Call]] = []
        qs_var = "<inline>"
        model_root: str | None = None
        if isinstance(iter_node, ast.Name):
            binding = self._tracker.bindings.get(iter_node.id)
            if binding is None:
                return
            chain, model_root = binding
            qs_var = iter_node.id
        elif isinstance(iter_node, ast.Call):
            chain = _collect_call_chain_methods(iter_node)
            model_root = _chain_model_root(chain)
            if model_root is None:
                # The chain does not root at a model, so it may be a call to a
                # helper that returns one: `for p in recent():` or
                # `for p in self.get_queryset():`. Splice the helper's chain in
                # front of whatever the caller appended, so a
                # `.select_related()` added on either side still counts and we
                # do not report an N+1 the caller already fixed.
                helper, in_chain = _helper_call_name(iter_node)
                resolved = self._returns.returns.get(helper) if helper else None
                if resolved is not None:
                    helper_chain, model_root = resolved
                    chain = helper_chain + (chain[1:] if in_chain else chain)
                    qs_var = f"{helper}()"
        else:
            return

        source_method = _chain_source_method(chain)
        # Only flag chains that actually root at ``<Model>.objects.<method>``
        # OR that begin with a queryset-producing method. Anything else
        # (dicts, lists, ranges) isn't in scope.
        if source_method is None:
            return
        if model_root is None and source_method not in _QS_SOURCE_METHODS:
            return

        select_set, prefetch_set = _chain_prefetch_args(chain)

        # 2. Collect attribute-chain accesses against ``loop_var`` in body.
        accesses = _collect_target_accesses(body, loop_var)
        if not accesses:
            return

        # 3. Classify each access: is it a relation? Is it already covered?
        uncovered_fk: list[str] = []
        uncovered_m2m: list[str] = []
        confidence = "medium"
        for attr, kind_hint in accesses:
            kind = self._classify(model_root, attr, kind_hint)
            if kind == "scalar":
                continue
            if kind in ("fk", "o2o"):
                if "*" in select_set or attr in select_set:
                    continue
                uncovered_fk.append(attr)
                if model_root is not None:
                    confidence = "high"
            elif kind in ("m2m", "reverse"):
                if "*" in prefetch_set or attr in prefetch_set:
                    continue
                uncovered_m2m.append(attr)
                if model_root is not None or kind_hint == "reverse":
                    confidence = "high"
            else:
                # unknown — treat as medium-confidence FK guess when the
                # access was ``target.attr.something`` (chain of length>=2)
                # or the ``.all()`` reverse-manager idiom.
                if kind_hint == "reverse":
                    if "*" not in prefetch_set and attr not in prefetch_set:
                        uncovered_m2m.append(attr)
                        confidence = "high"
                elif (
                    kind_hint == "chain"
                    and "*" not in select_set
                    and attr not in select_set
                ):
                    uncovered_fk.append(attr)

        if not uncovered_fk and not uncovered_m2m:
            return

        fix_parts: list[str] = []
        if uncovered_fk:
            fix_parts.append(
                ".select_related("
                + ", ".join(f'"{a}"' for a in _dedup_preserve(uncovered_fk))
                + ")"
            )
        if uncovered_m2m:
            fix_parts.append(
                ".prefetch_related("
                + ", ".join(f'"{a}"' for a in _dedup_preserve(uncovered_m2m))
                + ")"
            )
        suggested_fix = "".join(fix_parts)

        self.findings.append(
            NPlusOneFinding(
                file=_rel_posix(self.project_root, self.file_path),
                line=loop.lineno,
                loop_var=loop_var,
                queryset_var=qs_var,
                accessed=_dedup_preserve(uncovered_fk + uncovered_m2m),
                suggested_fix=suggested_fix,
                confidence=confidence,
            )
        )

    def _classify(
        self,
        model_root: str | None,
        attr: str,
        kind_hint: str | None,
    ) -> str | None:
        """Return ``"fk" | "o2o" | "m2m" | "reverse" | "scalar" | None``.

        Uses the parsed schema when the source model is known; falls back
        to ``kind_hint`` (from the access pattern) otherwise.
        """
        if model_root and model_root in self.models_schema:
            attrs = self.models_schema[model_root]
            if attr in attrs:
                return attrs[attr]
            # Attribute isn't declared on the model. Might still be a
            # reverse manager (``comment_set``, or an explicit
            # ``related_name`` we should have populated already). Fall
            # back to hint.
            if _REVERSE_MANAGER_SUFFIX.search(attr):
                return "reverse"
            # Unknown attribute on a known model — likely scalar (or a
            # property). Bail to avoid false positives.
            return "scalar"
        # No schema — hint drives the classification.
        return kind_hint


def _dedup_preserve(seq: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in seq:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _collect_target_accesses(
    body: Sequence[ast.stmt],
    loop_var: str,
) -> list[tuple[str, str | None]]:
    """Walk ``body`` and find every attribute-chain access rooted at the
    loop target ``loop_var``. Returns a list of ``(root_attr, kind_hint)``.

    * ``target.author.name`` -> ``("author", "chain")`` — chain of length >= 2
      strongly suggests FK traversal.
    * ``target.tags.all()`` -> ``("tags", "m2m")`` — reverse-manager idiom.
    * ``target.comment_set`` (or ``.all()``) -> ``("comment_set", "reverse")``.
    * ``target.author`` (single-attr access, no follow-up) -> ``("author", None)``.

    Nested for-loops are NOT descended into — a nested ``for tag in
    post.tags.all():`` is handled by a separate call from :meth:`visit_For`.
    """
    hits: list[tuple[str, str | None]] = []
    for stmt in body:
        _walk_for_accesses(stmt, loop_var, hits)
    return hits


def _walk_for_accesses(
    node: ast.AST,
    loop_var: str,
    hits: list[tuple[str, str | None]],
) -> None:
    # Don't recurse into nested for-loops — the outer walker handles them
    # as their own top-level loop. Nested functions and class defs are
    # also skipped to avoid crossing scopes.
    if isinstance(node, (ast.For, ast.AsyncFor, ast.FunctionDef,
                          ast.AsyncFunctionDef, ast.ClassDef)):
        # Still inspect the iter of a nested for — a nested
        # ``for tag in post.tags.all():`` counts as accessing ``tags``
        # on the outer loop_var.
        if isinstance(node, (ast.For, ast.AsyncFor)):
            _walk_for_accesses(node.iter, loop_var, hits)
        return

    if isinstance(node, ast.Call):
        # Method call: check if it's target.<attr>.<method>(...)
        method_name = _call_method_name(node)
        if method_name is not None and isinstance(node.func, ast.Attribute):
            chain = _attr_chain(node.func.value)
            if chain and chain[0] == loop_var and len(chain) >= 2:
                first_attr = chain[1]
                if method_name == "all" and _REVERSE_MANAGER_SUFFIX.search(first_attr):
                    hits.append((first_attr, "reverse"))
                elif method_name == "all":
                    hits.append((first_attr, "m2m"))
                elif method_name in ("filter", "exclude", "count", "exists"):
                    # target.related.filter(...) — related-manager idiom
                    if _REVERSE_MANAGER_SUFFIX.search(first_attr):
                        hits.append((first_attr, "reverse"))
                    else:
                        hits.append((first_attr, "m2m"))
        for child in ast.iter_child_nodes(node):
            _walk_for_accesses(child, loop_var, hits)
        return

    if isinstance(node, ast.Attribute):
        chain = _attr_chain(node)
        if chain and chain[0] == loop_var and len(chain) >= 2:
            first_attr = chain[1]
            if _REVERSE_MANAGER_SUFFIX.search(first_attr):
                hits.append((first_attr, "reverse"))
            elif len(chain) >= 3:
                # target.author.name — chain of length >=3 → FK traversal
                hits.append((first_attr, "chain"))
            else:
                # target.author — single attr, no follow-up. Ambiguous.
                hits.append((first_attr, None))
            # Don't descend further — we've captured the outermost chain.
            return

    for child in ast.iter_child_nodes(node):
        _walk_for_accesses(child, loop_var, hits)


def _build_schema_from_index(index: WorkspaceIndex) -> dict[str, dict[str, str]]:
    """Flatten a ``WorkspaceIndex`` into ``{ModelName: {attr: kind}}``.

    ``kind`` in ``{"fk", "o2o", "m2m", "reverse", "scalar"}``. Reverse
    relations (``<related_name>`` or default ``<model_lower>_set``) are
    computed by walking every FK/O2O/M2M in the workspace.
    """
    schema: dict[str, dict[str, str]] = {}
    for app in index.apps:
        for model in app.models:
            attrs = schema.setdefault(model.name, {})
            for f in model.fields:
                if not f.is_relation:
                    attrs[f.name] = "scalar"
                    continue
                kind = f.relation_kind
                if kind == "ForeignKey":
                    attrs[f.name] = "fk"
                elif kind == "OneToOneField":
                    attrs[f.name] = "o2o"
                elif kind == "ManyToManyField":
                    attrs[f.name] = "m2m"
                else:  # pragma: no cover
                    attrs[f.name] = "fk"
    user_model = find_user_model(index)
    user_model_name = user_model.name if user_model else None
    for app in index.apps:
        for model in app.models:
            for f in model.fields:
                if not f.is_relation or not f.related_model:
                    continue
                target = resolve_related_tail(f.related_model, user_model_name)
                if target == "self":
                    target = model.name
                if target not in schema:
                    continue
                reverse_name = f.related_name or f"{model.name.lower()}_set"
                schema[target].setdefault(reverse_name, "reverse")
    return schema


def scan_for_nplusone(
    project_root: str,
    models_schema: Any | None = None,
) -> list[NPlusOneFinding]:
    """Public entry point — walks ``project_root`` and returns findings.

    ``models_schema`` accepts either the flat ``{ModelName: {attr: kind}}``
    dict this module uses internally, OR the ``WorkspaceIndex.to_dict()``
    shape emitted by :func:`django_orm_lens.parser.scan_workspace`, OR a
    :class:`~django_orm_lens.models.WorkspaceIndex` instance. When
    ``None``, the scanner runs in schema-less heuristic mode.
    """
    root = Path(project_root).resolve()
    if not root.is_dir():
        return []

    flat_schema: dict[str, dict[str, str]] | None = None
    if models_schema is not None:
        flat_schema = _normalise_schema(models_schema)

    findings: list[NPlusOneFinding] = []
    for py in _iter_py_files_broad(root):
        try:
            source = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Cheap textual pre-filter — skip files with no ``for`` keyword.
        if "for " not in source and "for\t" not in source:
            continue
        try:
            tree = ast.parse(source, filename=str(py))
        except SyntaxError:
            continue
        scanner = NPlusOneScanner(py, root, flat_schema)
        try:
            scanner.visit(tree)
        except (AttributeError, TypeError, ValueError, RecursionError):  # pragma: no cover
            # Narrow to error classes the visitor might realistically raise on
            # malformed but valid-parse ASTs. Anything else (KeyboardInterrupt,
            # MemoryError, SystemExit, or unexpected security-sensitive
            # exception classes) must propagate — silently swallowing all
            # Exception hides bugs and masks abuse patterns.
            continue
        findings.extend(scanner.findings)
    return findings


def _normalise_schema(schema: Any) -> dict[str, dict[str, str]]:
    """Accept multiple schema shapes and return the flat internal shape."""
    if isinstance(schema, WorkspaceIndex):
        return _build_schema_from_index(schema)
    if isinstance(schema, dict) and "apps" in schema and isinstance(schema["apps"], list):
        return _build_schema_from_index_dict(schema)
    if isinstance(schema, dict):
        out: dict[str, dict[str, str]] = {}
        for model, attrs in schema.items():
            if isinstance(model, str) and isinstance(attrs, dict):
                out[model] = {
                    k: v for k, v in attrs.items()
                    if isinstance(k, str) and isinstance(v, str)
                }
        return out
    return {}


def _build_schema_from_index_dict(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Same as :func:`_build_schema_from_index` but for a raw dict payload
    (as emitted by ``WorkspaceIndex.to_dict()`` or ``scan --format json``).
    """
    schema: dict[str, dict[str, str]] = {}
    all_models: list[dict[str, Any]] = []
    for app in payload.get("apps", []):
        for model in app.get("models", []):
            all_models.append(model)
            attrs = schema.setdefault(model.get("name", ""), {})
            for f in model.get("fields", []):
                fname = f.get("name")
                if not fname:
                    continue
                if not f.get("isRelation"):
                    attrs[fname] = "scalar"
                    continue
                kind = f.get("relationKind")
                if kind == "ForeignKey":
                    attrs[fname] = "fk"
                elif kind == "OneToOneField":
                    attrs[fname] = "o2o"
                elif kind == "ManyToManyField":
                    attrs[fname] = "m2m"
                else:
                    attrs[fname] = "fk"
    user_model_dict = find_user_model_from_dict(payload)
    user_model_name = user_model_dict.get("name") if user_model_dict else None
    for model in all_models:
        model_name = model.get("name", "")
        for f in model.get("fields", []):
            if not f.get("isRelation"):
                continue
            related = f.get("relatedModel")
            if not related:
                continue
            target = resolve_related_tail(related, user_model_name)
            if target == "self":
                target = model_name
            if target not in schema:
                continue
            reverse_name = f.get("relatedName") or f"{model_name.lower()}_set"
            schema[target].setdefault(reverse_name, "reverse")
    return schema
