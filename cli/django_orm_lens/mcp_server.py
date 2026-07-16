"""MCP (Model Context Protocol) stdio server for Django ORM Lens.

Exposes nine read-only tools that any MCP-compatible AI agent can call:

* ``list_apps``       — list Django apps with model counts
* ``list_models``    — flat ``app.Model`` list, optional app filter
* ``describe_model`` — full field/relation/Meta detail for one model
* ``find_relations`` — inbound + outbound relations for one model
* ``cascade_preview`` — group inbound relations by on_delete behavior
* ``er_diagram``     — Mermaid ER diagram string for the whole workspace
* ``describe_migration_dependency`` — per-app migration DAG from static AST parse
* ``suggest_indexes`` — proposed ``Meta.indexes`` from workspace QuerySet usage
* ``signal_graph``   — sender→signal→handler DAG from ``@receiver`` decorators

The ``mcp`` runtime package is loaded lazily so ``pip install django-orm-lens``
stays zero-dep. Install with the extras: ``pip install 'django-orm-lens[mcp]'``.

Config: workspace root taken from ``$DJANGO_ORM_LENS_ROOT`` if set, else ``cwd``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Tuple

from .cli import _build_mermaid
from .migrations_parser import describe_migration_dependency
from .models import WorkspaceIndex
from .parser import DEFAULT_EXCLUDES, scan_workspace
from .query_analyzer import suggest_indexes as _suggest_indexes
from .signals_parser import signal_graph as _signal_graph


def _workspace_root() -> str:
    return os.environ.get("DJANGO_ORM_LENS_ROOT") or os.getcwd()


_INDEX_CACHE: Dict[str, Tuple[WorkspaceIndex, int]] = {}
_CACHE_TTL_MS = 30_000


def _get_index() -> WorkspaceIndex:
    """Cache-backed workspace index — 30s TTL, keyed by workspace root.

    Agents typically fire multiple MCP tool calls back-to-back (list_apps →
    describe_model → find_relations). Without a cache each call re-walked the
    filesystem and re-parsed every models.py. TTL is short enough that manual
    edits between calls still pick up on the next scan.
    """
    root = _workspace_root()
    now_ms = int(time.time() * 1000)
    entry = _INDEX_CACHE.get(root)
    if entry is not None and entry[1] > now_ms:
        return entry[0]
    idx = scan_workspace(root, DEFAULT_EXCLUDES)
    _INDEX_CACHE[root] = (idx, now_ms + _CACHE_TTL_MS)
    return idx


def _tool_list_apps(_args: Dict[str, Any]) -> str:
    idx = _get_index()
    return json.dumps(
        [
            {"name": a.name, "path": a.path, "models": len(a.models)}
            for a in idx.apps
        ],
        indent=2,
    )


def _tool_list_models(args: Dict[str, Any]) -> str:
    idx = _get_index()
    only_app = (args or {}).get("app")
    if only_app and not any(a.name == only_app for a in idx.apps):
        available = ", ".join(sorted(a.name for a in idx.apps)) or "(none)"
        return (
            f"(app '{only_app}' not found in workspace; "
            f"available apps: {available})"
        )
    rows: List[str] = []
    for app in idx.apps:
        if only_app and app.name != only_app:
            continue
        for m in app.models:
            rows.append(f"{app.name}.{m.name}")
    return "\n".join(rows) if rows else "(no models)"


def _find(idx, ref: str):
    if "." in ref:
        an, mn = ref.split(".", 1)
        for app in idx.apps:
            if app.name == an:
                for m in app.models:
                    if m.name == mn:
                        return m
    for app in idx.apps:
        for m in app.models:
            if m.name == ref:
                return m
    return None


_USER_BASE_MARKERS = ("AbstractUser", "AbstractBaseUser")


def _workspace_user_model(idx):
    """Return (app_name, model) for the workspace's Django User model.

    Used to resolve ``settings.AUTH_USER_MODEL`` references. Heuristic:
    1) first model whose bases include ``AbstractUser`` / ``AbstractBaseUser``,
    2) else first model literally named ``User``, 3) else ``(None, None)``.
    """
    for app in idx.apps:
        for m in app.models:
            for b in m.base_classes:
                tail = b.split(".")[-1]
                if tail in _USER_BASE_MARKERS:
                    return app.name, m
    for app in idx.apps:
        for m in app.models:
            if m.name == "User":
                return app.name, m
    return None, None


def _rel_matches_target(related_model, target_name, user_model):
    """True iff ``related_model`` string points at ``target_name``. Handles
    ``settings.AUTH_USER_MODEL`` by resolving to the workspace user model."""
    if not related_model:
        return False
    tail = related_model.split(".")[-1]
    if tail == target_name:
        return True
    if tail == "AUTH_USER_MODEL" and user_model is not None:
        return user_model.name == target_name
    return False


def _tool_describe_model(args: Dict[str, Any]) -> str:
    idx = _get_index()
    ref = (args or {}).get("model", "")
    m = _find(idx, ref)
    if not m:
        raise ValueError(f"model {ref!r} not found")
    return json.dumps(m.to_dict(), indent=2)


def _tool_find_relations(args: Dict[str, Any]) -> str:
    idx = _get_index()
    ref = (args or {}).get("model", "")
    m = _find(idx, ref)
    if not m:
        raise ValueError(f"model {ref!r} not found")
    out: Dict[str, Any] = {"outbound": [], "inbound": []}
    for f in m.fields:
        if f.is_relation:
            out["outbound"].append(
                {
                    "field": f.name,
                    "kind": f.relation_kind,
                    "target": f.related_model,
                }
            )
    _, user_model = _workspace_user_model(idx)
    for app in idx.apps:
        for other in app.models:
            if other is m:
                continue
            for f in other.fields:
                if not f.is_relation:
                    continue
                if not _rel_matches_target(f.related_model, m.name, user_model):
                    continue
                out["inbound"].append(
                    {
                        "from": f"{app.name}.{other.name}",
                        "field": f.name,
                        "kind": f.relation_kind,
                        "on_delete": f.on_delete or "unknown",
                    }
                )
    return json.dumps(out, indent=2)


def _tool_cascade_preview(args: Dict[str, Any]) -> str:
    idx = _get_index()
    app_label = (args or {}).get("app_label", "")
    model_name = (args or {}).get("model_name", "")
    ref = f"{app_label}.{model_name}" if app_label else model_name
    m = _find(idx, ref)
    if not m:
        raise ValueError(f"model {ref!r} not found")
    target_app = None
    for app in idx.apps:
        if m in app.models:
            target_app = app.name
            break
    out: Dict[str, Any] = {
        "target": f"{target_app}.{m.name}" if target_app else m.name,
        "cascade_kills": [],
        "set_null": [],
        "protected": [],
    }
    _, user_model = _workspace_user_model(idx)
    for app in idx.apps:
        for other in app.models:
            if other is m:
                continue
            for f in other.fields:
                if not f.is_relation:
                    continue
                if not _rel_matches_target(f.related_model, m.name, user_model):
                    continue
                on_delete = (f.on_delete or "").upper()
                entry = {
                    "model": f"{app.name}.{other.name}",
                    "via_field": f.name,
                }
                if on_delete == "CASCADE":
                    entry["count_hint"] = "unknown"
                    out["cascade_kills"].append(entry)
                elif on_delete in ("SET_NULL", "SET_DEFAULT", "SET"):
                    out["set_null"].append(entry)
                elif on_delete in ("PROTECT", "RESTRICT"):
                    out["protected"].append(entry)
    return json.dumps(out, indent=2)


def _tool_er_diagram(_args: Dict[str, Any]) -> str:
    idx = _get_index()
    return _build_mermaid(idx)


def _tool_describe_migration_dependency(args: Dict[str, Any]) -> str:
    """Return migration DAG for one Django app.

    Static AST parse of ``<app>/migrations/*.py`` — no Django boot, no DB.
    Unique to django-orm-lens across the MCP + Django-graph tool ecosystem
    (competitors require a running Django process).
    """
    app_label = (args or {}).get("app_label", "")
    if not app_label:
        raise ValueError("app_label is required")
    result = describe_migration_dependency(app_label, _workspace_root())
    return json.dumps(result, indent=2)


def _tool_suggest_indexes(args: Dict[str, Any]) -> str:
    """Static analysis of QuerySet usage → proposed ``Meta.indexes`` entries.

    Walks the workspace, captures every ``<Model>.objects.filter/.exclude/
    .get/.order_by/.aggregate`` call, groups by field frequency and
    co-occurrence, then proposes single-field and composite indexes.
    Cross-references with the model's existing ``Meta.indexes`` so
    already-covered combos are not re-proposed.
    """
    app_label = (args or {}).get("app_label", "")
    model_name = (args or {}).get("model_name", "")
    if not app_label or not model_name:
        raise ValueError("app_label and model_name are required")
    index = _get_index()
    result = _suggest_indexes(app_label, model_name, _workspace_root(), index=index)
    return json.dumps(result, indent=2)


def _tool_signal_graph(_args: Dict[str, Any]) -> str:
    """Return the sender→signal→handler DAG for the workspace.

    Static AST parse of every ``@receiver(...)`` decorator plus every
    module-level ``x = Signal(...)`` custom-signal definition and its
    ``.send(...)`` call-sites. Surfaces cross-model side effects and
    orphan handlers whose sender model isn't in the workspace.
    """
    index = _get_index()
    result = _signal_graph(_workspace_root(), index=index)
    return json.dumps(result, indent=2)


TOOLS = {
    "list_apps": {
        "handler": _tool_list_apps,
        "description": "List every Django app in the workspace with model counts.",
    },
    "list_models": {
        "handler": _tool_list_models,
        "description": "Flat list of app.Model. Optional 'app' filter.",
    },
    "describe_model": {
        "handler": _tool_describe_model,
        "description": "Full JSON detail for one model: fields, relations, Meta, base classes, file path.",
    },
    "find_relations": {
        "handler": _tool_find_relations,
        "description": "Outbound (this model → others) and inbound (others → this) relations. Inbound entries include on_delete behavior.",
    },
    "cascade_preview": {
        "handler": _tool_cascade_preview,
        "description": "Blast radius of deleting a row: inbound relations grouped by on_delete behavior (cascade_kills, set_null, protected).",
    },
    "er_diagram": {
        "handler": _tool_er_diagram,
        "description": "Emit a Mermaid erDiagram for the whole workspace.",
    },
    "describe_migration_dependency": {
        "handler": _tool_describe_migration_dependency,
        "description": "Return per-app migration DAG (dependencies, roots, leaves, cross-app deps) from static AST parse of migrations/*.py. No Django boot, no DB. Lets agents debug migration conflicts safely.",
    },
    "suggest_indexes": {
        "handler": _tool_suggest_indexes,
        "description": "Static analysis of every filter/exclude/get/order_by/aggregate usage of a model across the workspace. Returns field-usage frequency and proposes Meta.indexes covering entries. Zero-runtime, no DB, no Django boot.",
    },
    "signal_graph": {
        "handler": _tool_signal_graph,
        "description": "Parse every @receiver() decorator and Signal() definition in the workspace. Returns sender→signal→handler DAG plus custom-signal send-sites and orphan handlers. Zero-runtime, no DB, no Django boot.",
    },
}


def main() -> int:
    """Start the MCP stdio server. Lazy-imports the ``mcp`` package."""
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore
    except ImportError:
        print(
            "django-orm-lens MCP requires the 'mcp' package.\n"
            "install with: pip install 'django-orm-lens[mcp]'",
            file=sys.stderr,
        )
        return 3

    server = FastMCP("django-orm-lens")

    # Subtle star-ask on startup (stderr — stdout is reserved for JSON-RPC).
    # Mirrors the CLI welcome convention from py-1.0.9. MCP clients that
    # surface server stderr (Cursor, Aider, mcp-inspector) show this once
    # per session; silent clients ignore it. Zero effect on tool protocol.
    print(
        "django-orm-lens MCP ready — "
        "if it saves your agent time, a star helps: "
        "https://github.com/FROWNINGdev/django-orm-lens",
        file=sys.stderr,
    )

    def _register(name: str, description: str, handler):
        if name == "list_apps":
            @server.tool(name=name, description=description)
            def list_apps() -> str:
                return handler({})
        elif name == "list_models":
            @server.tool(name=name, description=description)
            def list_models(app: str = "") -> str:
                return handler({"app": app} if app else {})
        elif name == "describe_model":
            @server.tool(name=name, description=description)
            def describe_model(model: str) -> str:
                return handler({"model": model})
        elif name == "find_relations":
            @server.tool(name=name, description=description)
            def find_relations(model: str) -> str:
                return handler({"model": model})
        elif name == "cascade_preview":
            @server.tool(name=name, description=description)
            def cascade_preview(app_label: str, model_name: str) -> str:
                return handler({"app_label": app_label, "model_name": model_name})
        elif name == "er_diagram":
            @server.tool(name=name, description=description)
            def er_diagram() -> str:
                return handler({})
        elif name == "describe_migration_dependency":
            @server.tool(name=name, description=description)
            def describe_migration_dependency(app_label: str) -> str:
                return handler({"app_label": app_label})
        elif name == "suggest_indexes":
            @server.tool(name=name, description=description)
            def suggest_indexes(app_label: str, model_name: str) -> str:
                return handler({"app_label": app_label, "model_name": model_name})
        elif name == "signal_graph":
            @server.tool(name=name, description=description)
            def signal_graph() -> str:
                return handler({})

    for name, spec in TOOLS.items():
        _register(name, spec["description"], spec["handler"])

    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
