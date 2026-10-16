"""Index suggestions — propose ``Meta.indexes`` from observed QuerySet usage.

See ``query_analyzer`` for the shared overview; this module holds the
suggest_indexes half of it.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .models import (
    WorkspaceIndex,
)

QS_METHODS = frozenset({"filter", "exclude", "get", "order_by", "aggregate"})


def _iter_py_files(root: Path) -> Iterable[Path]:
    from .parser import iter_workspace_py_files  # local to avoid cycles
    return iter_workspace_py_files(root)


def _root_field(kwarg: str) -> str:
    """``user__email__iexact`` → ``user``. Plain ``user`` stays ``user``."""
    return kwarg.split("__", 1)[0]


def _canonical_pk(field: str, pk_name: str) -> str:
    """Fold the ``pk`` alias onto the real primary-key field name.

    Keeps any ``-`` prefix so ``order_by("-pk")`` stays a descending sort.
    """
    prefix, body = ("-", field[1:]) if field.startswith("-") else ("", field)
    return prefix + (pk_name if body == "pk" else body)


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

    ``fields`` may be written as a list or a tuple, and both forms appear in
    real code — ``models.Index(fields=("a", "b"))`` is as common as the list.
    """
    raw = meta.get("indexes")
    if not raw:
        return []
    return _field_tuples(raw)


def _field_tuples(raw: str) -> list[list[str]]:
    """Every ``fields=[...]`` / ``fields=(...)`` group in a source snippet."""
    out: list[list[str]] = []
    for m in re.finditer(r"fields\s*=\s*[\[(]([^\])]*)[\])]", raw):
        fields = re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))
        if fields:
            out.append(fields)
    return out


def _unique_constraint_tuples(meta: dict[str, str]) -> list[list[str]]:
    """Field groups from ``Meta.constraints`` that create a unique index.

    Only ``UniqueConstraint`` is counted. ``CheckConstraint`` creates no index,
    and a ``UniqueConstraint`` carrying ``expressions=`` indexes an expression
    rather than the bare columns, so it cannot satisfy a column lookup either.
    """
    raw = meta.get("constraints")
    if not raw:
        return []
    out: list[list[str]] = []
    for m in re.finditer(r"UniqueConstraint\s*\(", raw):
        out.extend(_field_tuples(_balanced_call_args(raw, m.end() - 1)))
    return out


def _balanced_call_args(raw: str, open_paren: int) -> str:
    """Text between ``raw[open_paren]`` and its matching ``)``.

    A regex cannot do this: a constraint's arguments contain their own
    parentheses (``fields=("a", "b")``, ``condition=Q(x=1)``), so any
    ``\\(.*?\\)`` stops at the first inner close and truncates the very
    ``fields=`` group we are here to read.
    """
    depth = 0
    for i in range(open_paren, len(raw)):
        ch = raw[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return raw[open_paren + 1 : i]
    return raw[open_paren + 1 :]


def _innermost_bracket_spans(raw: str) -> list[str]:
    """Contents of every bracket group that holds no further bracket.

    ``(("a", "b"), ("c",))`` yields the two inner groups; ``("a", "b")``
    yields itself. Written as a single left-to-right scan rather than a
    regex on purpose: the pattern this replaces nested a quantifier inside a
    quantifier and CodeQL flagged it as a ReDoS (alert #35, high). A scan is
    linear in the input no matter how the snippet is shaped.
    """
    spans: list[str] = []
    stack: list[tuple[int, bool]] = []  # (content start, saw a nested group)
    for i, ch in enumerate(raw):
        if ch in "([":
            for j in range(len(stack)):
                stack[j] = (stack[j][0], True)
            stack.append((i + 1, False))
        elif ch in ")]" and stack:
            start, had_child = stack.pop()
            if not had_child:
                spans.append(raw[start:i])
    return spans


def _unique_together_tuples(meta: dict[str, str]) -> list[list[str]]:
    """``Meta.unique_together`` groups — each one is backed by a unique index.

    Accepts both the single-group shorthand (``("a", "b")``) and the nested
    form (``(("a", "b"), ("c",))``) Django also allows.
    """
    raw = meta.get("unique_together")
    if not raw:
        return []
    out: list[list[str]] = []
    for span in _innermost_bracket_spans(raw):
        names = re.findall(r"['\"]([^'\"]+)['\"]", span)
        if names:
            out.append(names)
    if out:
        return out
    flat = re.findall(r"['\"]([^'\"]+)['\"]", raw)
    return [flat] if flat else []


_PK_TRUE_RE = re.compile(r"\bprimary_key\s*=\s*True\b")
_UNIQUE_TRUE_RE = re.compile(r"\bunique\s*=\s*True\b")
_DB_INDEX_TRUE_RE = re.compile(r"\bdb_index\s*=\s*True\b")
_DB_INDEX_FALSE_RE = re.compile(r"\bdb_index\s*=\s*False\b")

#: Django gives these their own index on the referencing column unless the
#: field explicitly opts out with ``db_index=False``. ManyToManyField is absent
#: on purpose — its indexes live on the through table, not on this model.
_SELF_INDEXED_RELATIONS = frozenset({"ForeignKey", "OneToOneField"})


def primary_key_field(model: Any) -> str:
    """The model's primary-key field name — the explicit one, or ``id``."""
    for f in model.all_fields():
        if _PK_TRUE_RE.search(f.args or ""):
            return f.name
    return "id"


def _indexed_single_fields(model: Any) -> set[str]:
    """Field names that already sit behind an index, so needing no proposal.

    Covers what Django indexes without being asked (#60): the primary key,
    ``db_index=True``, ``unique=True``, and the referencing column of a
    ForeignKey / OneToOneField. Leading columns of a composite index count
    too — a B-tree on ``(a, b)`` answers a lookup on ``a`` alone.
    """
    pk = primary_key_field(model)
    # ``pk`` is an alias Django resolves to whatever the primary key is, so a
    # filter written either way hits the same already-indexed column.
    out: set[str] = {pk, "pk"}
    for f in model.all_fields():
        args = f.args or ""
        has_own_index = (
            _PK_TRUE_RE.search(args)
            or _UNIQUE_TRUE_RE.search(args)
            or _DB_INDEX_TRUE_RE.search(args)
            or (
                f.relation_kind in _SELF_INDEXED_RELATIONS
                and not _DB_INDEX_FALSE_RE.search(args)
            )
        )
        if has_own_index:
            out.add(f.name)
    for group in _covered_field_groups(model):
        if group:
            out.add(group[0])
    return out


def _covered_field_groups(model: Any) -> list[list[str]]:
    """Every multi-column index the model already declares, in Meta."""
    meta = model.meta
    return [
        *_existing_meta_indexes(meta),
        *_unique_together_tuples(meta),
        *_unique_constraint_tuples(meta),
    ]


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
    already_indexed: set[str] | None = None,
    covered_groups: list[list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Turn the frequency tables into concrete ``Meta.indexes`` suggestions.

    Rules:
    * composite filter combos with >=2 sites take priority over their
      individual-field siblings (a composite index covers single-field
      lookups on the leading column too).
    * single-field filter usage needs >=2 sites to warrant its own index.
    * every order_by field with >=2 sites gets a proposal (unless already
      covered by an existing index whose leading field matches).

    Existing ``Meta.indexes`` are dedup'd by exact field-list match, and
    ``already_indexed`` drops anything Django indexes on its own — primary
    key, ``db_index=True``, ``unique=True``, foreign keys, unique constraints
    (#60). Suggesting an index that exists is worse than silence: it teaches
    people the tool has not read their model.
    """
    covered = already_indexed or set()
    existing_set = {tuple(x) for x in existing}
    # Every column group already backed by an index, whichever Meta option
    # declared it — indexes, unique_together or a UniqueConstraint.
    existing_sets = [set(x) for x in (covered_groups or existing)]
    proposed: list[dict[str, Any]] = []
    covered_leaders: set[str] = set()

    for combo in filter_composites:
        if combo["sites"] < 2:
            continue
        fields = combo["field"]
        key = tuple(fields)
        if key in existing_set:
            continue
        # An existing index over the same columns answers this combo whatever
        # order it was declared in.
        if any(set(fields) == grp for grp in existing_sets):
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
        if field in covered_leaders or field in covered:
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
        # order_by keeps its ``-`` prefix; the index behind it is the same one
        # either direction, so strip it before asking whether it exists.
        if field.lstrip("-") in covered:
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

    # ``pk`` is an alias for the real primary-key column, so ``filter(pk=…)``
    # and ``filter(id=…)`` are the same lookup and must not be counted as two
    # different fields (#60).
    pk_name = primary_key_field(target_model)
    for bucket in (all_filter, all_exclude, all_get, all_order_by, all_aggregate):
        for row in bucket:
            row["fields"] = [_canonical_pk(f, pk_name) for f in row["fields"]]

    filter_singles, filter_composites = _summarise_filter_like(
        all_filter + all_exclude + all_get
    )
    order_by_summary = _summarise_order_by(all_order_by)
    aggregate_summary = _summarise_order_by(all_aggregate)  # same shape

    existing = _existing_meta_indexes(target_model.meta)
    already_indexed = _indexed_single_fields(target_model)
    proposed = _propose_indexes(
        filter_singles,
        filter_composites,
        order_by_summary,
        existing,
        already_indexed,
        _covered_field_groups(target_model),
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
        # Why a hot field may carry no proposal. Without this the output is
        # indistinguishable from the analyzer having missed the usage.
        "already_indexed": sorted(already_indexed),
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


