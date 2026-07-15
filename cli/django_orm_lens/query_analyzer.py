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
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .models import WorkspaceIndex

QS_METHODS = frozenset({"filter", "exclude", "get", "order_by", "aggregate"})

# Directories that are never source-under-test.
_SKIP_DIRS = frozenset(
    {"migrations", "node_modules", "venv", ".venv", "env", ".git", "__pycache__"}
)


def _iter_py_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in _SKIP_DIRS
        ]
        for name in filenames:
            if name.endswith(".py"):
                yield Path(dirpath) / name


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


def _unwrap_call_chain(node: ast.Call) -> List[ast.Call]:
    """For ``Foo.objects.filter(a=1).filter(b=2).order_by('c')`` return every
    Call node in the chain, outermost last. The receiver root (``Foo.objects``)
    must be identified separately via :func:`_chain_root`.
    """
    chain: List[ast.Call] = []
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


def _chain_root(outermost: ast.Call) -> Optional[Tuple[str, ast.Attribute]]:
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


def _kwarg_names(call: ast.Call) -> List[str]:
    return [kw.arg for kw in call.keywords if kw.arg is not None]


def _order_by_positionals(call: ast.Call) -> Tuple[List[str], bool]:
    """Return (list of order_by strings, has_non_string_positional)."""
    strings: List[str] = []
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


def _existing_meta_indexes(meta: Dict[str, str]) -> List[List[str]]:
    """Best-effort parse of ``Meta.indexes = [models.Index(fields=[...]), ...]``.

    ``meta`` values are raw source snippets (see parser). We regex the
    ``fields=[...]`` bit and pull each quoted field name. Returns a list of
    field-name lists (order preserved). Non-parseable entries are skipped.
    """
    raw = meta.get("indexes")
    if not raw:
        return []
    out: List[List[str]] = []
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
        self.filter_sites: List[Dict[str, Any]] = []
        self.exclude_sites: List[Dict[str, Any]] = []
        self.get_sites: List[Dict[str, Any]] = []
        self.order_by_sites: List[Dict[str, Any]] = []
        self.aggregate_sites: List[Dict[str, Any]] = []
        # visited call-node ids so we don't double-count nested chain calls
        self._visited: Set[int] = set()

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
            row: Dict[str, Any] = {
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
    sites: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (single_field_usages, composite_usages) for filter/exclude/get.

    * single_field_usages: one row per distinct field, with occurrence count
      across all sites (each field counted once per site).
    * composite_usages: one row per distinct multi-field combo that appears
      in a single call, with occurrence count across sites.
    """
    single_counts: Dict[str, int] = defaultdict(int)
    single_example: Dict[str, str] = {}
    composite_counts: Dict[Tuple[str, ...], int] = defaultdict(int)
    composite_example: Dict[Tuple[str, ...], str] = {}

    for row in sites:
        fields = row["fields"]
        seen_this_site: Set[str] = set()
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


def _summarise_order_by(sites: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = defaultdict(int)
    example: Dict[str, str] = {}
    for row in sites:
        for f in row["fields"]:
            counts[f] += 1
            example.setdefault(f, row["site"])
    return [
        {"field": f, "sites": c, "example": example[f]}
        for f, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _propose_indexes(
    filter_singles: List[Dict[str, Any]],
    filter_composites: List[Dict[str, Any]],
    order_by_summary: List[Dict[str, Any]],
    existing: List[List[str]],
) -> List[Dict[str, Any]]:
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
    proposed: List[Dict[str, Any]] = []
    covered_leaders: Set[str] = set()

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
    index: Optional[WorkspaceIndex] = None,
) -> Dict[str, Any]:
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

    all_filter: List[Dict[str, Any]] = []
    all_exclude: List[Dict[str, Any]] = []
    all_get: List[Dict[str, Any]] = []
    all_order_by: List[Dict[str, Any]] = []
    all_aggregate: List[Dict[str, Any]] = []

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

    filter_usages: List[Dict[str, Any]] = list(filter_singles)
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


def _sites_to_summary(sites: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compact per-field summary of an exclude/get bucket."""
    counts: Dict[str, int] = defaultdict(int)
    example: Dict[str, str] = {}
    for row in sites:
        seen: Set[str] = set()
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
