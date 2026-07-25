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

Workspace discovery (py-1.3.0+)
-------------------------------
Every tool accepts an optional ``workspace_root`` argument. Resolution
priority — explicit arg, then ``$DJANGO_ORM_LENS_ROOT`` env var, then ``cwd``
— is implemented once in :mod:`django_orm_lens.workspace`. Before py-1.3.0
the argument was silently dropped by FastMCP because the tool signatures did
not declare it; the fix is to declare the argument on every tool and delegate
resolution to a single hardened helper. On failure the tool returns a JSON
envelope ``{"error": "...", "hint": "..."}`` so the agent gets an actionable
message instead of an empty list.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Union

from .cli import _build_mermaid
from .migrations_parser import describe_migration_dependency
from .models import WorkspaceIndex, find_model, find_user_model, resolve_related_tail
from .query_analyzer import scan_for_nplusone as _scan_for_nplusone
from .query_analyzer import suggest_indexes as _suggest_indexes
from .signals_parser import signal_graph as _signal_graph
from .workspace import WorkspaceError, get_index, resolve_workspace


# ---------------------------------------------------------------------------
# Resolution helper — every tool starts here
# ---------------------------------------------------------------------------


def _resolve(args: Dict[str, Any]) -> Union[Path, WorkspaceError]:
    """Extract ``workspace_root`` from tool args and delegate to workspace.py.

    Centralised so every tool has identical resolution semantics. Empty string,
    missing key, and ``None`` all fall through to env var / cwd — same as
    calling the tool with no argument at all.
    """
    raw = (args or {}).get("workspace_root") or ""
    return resolve_workspace(raw)


def _error_json(err: WorkspaceError) -> str:
    """Serialize a :class:`WorkspaceError` as an indent-2 JSON envelope."""
    return json.dumps(err.to_dict(), indent=2)


# ---------------------------------------------------------------------------
# Model lookup helpers — shared by describe_model / find_relations / cascade
# ---------------------------------------------------------------------------


def _find(idx: WorkspaceIndex, ref: str):
    """Delegate to shared ``find_model`` so MCP and CLI lookup semantics stay
    in sync (they previously drifted — hence the shared helper)."""
    return find_model(idx, ref)


def _workspace_user_model(idx: WorkspaceIndex):
    """Return ``(app_name, model)`` for the workspace's Django User model.

    Thin wrapper around :func:`models.find_user_model` that preserves the
    ``(app_name, model)`` tuple this MCP layer historically returned. New
    callers should prefer ``find_user_model`` directly.
    """
    user_model = find_user_model(idx)
    if user_model is None:
        return None, None
    for app in idx.apps:
        if user_model in app.models:
            return app.name, user_model
    return None, user_model


def _rel_matches_target(related_model, target_name, user_model) -> bool:
    """True iff ``related_model`` string points at ``target_name``. Handles
    ``settings.AUTH_USER_MODEL`` via :func:`models.resolve_related_tail`."""
    if not related_model:
        return False
    user_name = user_model.name if user_model is not None else None
    return resolve_related_tail(related_model, user_name) == target_name


# ---------------------------------------------------------------------------
# Nine tool handlers
# ---------------------------------------------------------------------------


def _tool_list_apps(args: Dict[str, Any]) -> str:
    ws = _resolve(args)
    if isinstance(ws, WorkspaceError):
        return _error_json(ws)
    idx = get_index(ws)
    return json.dumps(
        [
            {"name": a.name, "path": a.path, "models": len(a.models)}
            for a in idx.apps
        ],
        indent=2,
    )


def _tool_list_models(args: Dict[str, Any]) -> str:
    ws = _resolve(args)
    if isinstance(ws, WorkspaceError):
        return _error_json(ws)
    idx = get_index(ws)
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


def _tool_describe_model(args: Dict[str, Any]) -> str:
    ws = _resolve(args)
    if isinstance(ws, WorkspaceError):
        return _error_json(ws)
    idx = get_index(ws)
    ref = (args or {}).get("model", "")
    m = _find(idx, ref)
    if not m:
        raise ValueError(f"model {ref!r} not found")
    return json.dumps(m.to_dict(), indent=2)


def _tool_find_relations(args: Dict[str, Any]) -> str:
    ws = _resolve(args)
    if isinstance(ws, WorkspaceError):
        return _error_json(ws)
    idx = get_index(ws)
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
    ws = _resolve(args)
    if isinstance(ws, WorkspaceError):
        return _error_json(ws)
    idx = get_index(ws)
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


def _tool_er_diagram(args: Dict[str, Any]) -> str:
    ws = _resolve(args)
    if isinstance(ws, WorkspaceError):
        return _error_json(ws)
    idx = get_index(ws)
    return _build_mermaid(idx)


def _tool_describe_migration_dependency(args: Dict[str, Any]) -> str:
    """Return migration DAG for one Django app.

    Static AST parse of ``<app>/migrations/*.py`` — no Django boot, no DB.
    Unique to django-orm-lens across the MCP + Django-graph tool ecosystem
    (competitors require a running Django process).
    """
    ws = _resolve(args)
    if isinstance(ws, WorkspaceError):
        return _error_json(ws)
    app_label = (args or {}).get("app_label", "")
    if not app_label:
        raise ValueError("app_label is required")
    result = describe_migration_dependency(app_label, str(ws))
    return json.dumps(result, indent=2)


def _tool_suggest_indexes(args: Dict[str, Any]) -> str:
    """Static analysis of QuerySet usage → proposed ``Meta.indexes`` entries.

    Walks the workspace, captures every ``<Model>.objects.filter/.exclude/
    .get/.order_by/.aggregate`` call, groups by field frequency and
    co-occurrence, then proposes single-field and composite indexes.
    Cross-references with the model's existing ``Meta.indexes`` so
    already-covered combos are not re-proposed.
    """
    ws = _resolve(args)
    if isinstance(ws, WorkspaceError):
        return _error_json(ws)
    app_label = (args or {}).get("app_label", "")
    model_name = (args or {}).get("model_name", "")
    if not app_label or not model_name:
        raise ValueError("app_label and model_name are required")
    index = get_index(ws)
    result = _suggest_indexes(app_label, model_name, str(ws), index=index)
    return json.dumps(result, indent=2)


def _tool_signal_graph(args: Dict[str, Any]) -> str:
    """Return the sender→signal→handler DAG for the workspace.

    Static AST parse of every ``@receiver(...)`` decorator plus every
    module-level ``x = Signal(...)`` custom-signal definition and its
    ``.send(...)`` call-sites. Surfaces cross-model side effects and
    orphan handlers whose sender model isn't in the workspace.
    """
    ws = _resolve(args)
    if isinstance(ws, WorkspaceError):
        return _error_json(ws)
    index = get_index(ws)
    result = _signal_graph(str(ws), index=index)
    return json.dumps(result, indent=2)


def _tool_nplusone_scan(args: Dict[str, Any]) -> str:
    """Static scan for Django ORM N+1 anti-patterns across the workspace.

    Walks every ``.py`` file, finds ``for ... in <queryset>:`` loops, and
    flags attribute-chain accesses against the loop target that touch a
    related object (FK / O2O / M2M / reverse FK) without a matching
    ``select_related`` / ``prefetch_related`` clause on the source queryset.
    Uses the parsed WorkspaceIndex to classify relations; falls back to
    a schema-less heuristic when a model is unknown. Zero-runtime, no DB.
    """
    ws = _resolve(args)
    if isinstance(ws, WorkspaceError):
        return _error_json(ws)
    index = get_index(ws)
    findings = _scan_for_nplusone(str(ws), index)
    return json.dumps([f.to_dict() for f in findings], indent=2)


# ---------------------------------------------------------------------------
# Tool registry — descriptions ship in tools/list so agents see them
# ---------------------------------------------------------------------------

_WORKSPACE_HINT = (
    " Optional 'workspace_root' argument overrides the DJANGO_ORM_LENS_ROOT "
    "env var and current directory — pass the absolute path to your Django "
    "project root (the directory containing manage.py)."
)

TOOLS = {
    "list_apps": {
        "handler": _tool_list_apps,
        "description": (
            "List every Django app in the workspace with model counts." + _WORKSPACE_HINT
        ),
    },
    "list_models": {
        "handler": _tool_list_models,
        "description": (
            "Flat list of app.Model. Optional 'app' filter." + _WORKSPACE_HINT
        ),
    },
    "describe_model": {
        "handler": _tool_describe_model,
        "description": (
            "Full JSON detail for one model: fields, relations, Meta, base "
            "classes, file path." + _WORKSPACE_HINT
        ),
    },
    "find_relations": {
        "handler": _tool_find_relations,
        "description": (
            "Outbound (this model -> others) and inbound (others -> this) "
            "relations. Inbound entries include on_delete behavior." + _WORKSPACE_HINT
        ),
    },
    "cascade_preview": {
        "handler": _tool_cascade_preview,
        "description": (
            "Blast radius of deleting a row: inbound relations grouped by "
            "on_delete behavior (cascade_kills, set_null, protected)." + _WORKSPACE_HINT
        ),
    },
    "er_diagram": {
        "handler": _tool_er_diagram,
        "description": (
            "Emit a Mermaid erDiagram for the whole workspace." + _WORKSPACE_HINT
        ),
    },
    "describe_migration_dependency": {
        "handler": _tool_describe_migration_dependency,
        "description": (
            "Return per-app migration DAG (dependencies, roots, leaves, "
            "cross-app deps) from static AST parse of migrations/*.py. No "
            "Django boot, no DB. Lets agents debug migration conflicts "
            "safely." + _WORKSPACE_HINT
        ),
    },
    "suggest_indexes": {
        "handler": _tool_suggest_indexes,
        "description": (
            "Static analysis of every filter/exclude/get/order_by/aggregate "
            "usage of a model across the workspace. Returns field-usage "
            "frequency and proposes Meta.indexes covering entries. "
            "Zero-runtime, no DB, no Django boot." + _WORKSPACE_HINT
        ),
    },
    "signal_graph": {
        "handler": _tool_signal_graph,
        "description": (
            "Parse every @receiver() decorator and Signal() definition in "
            "the workspace. Returns sender->signal->handler DAG plus custom-"
            "signal send-sites and orphan handlers. Zero-runtime, no DB, no "
            "Django boot." + _WORKSPACE_HINT
        ),
    },
    "nplusone_scan": {
        "handler": _tool_nplusone_scan,
        "description": (
            "Static scan for Django ORM N+1 anti-patterns. Walks every .py "
            "file, finds 'for x in <queryset>:' loops that touch related "
            "objects (FK/O2O/M2M/reverse) without matching select_related "
            "or prefetch_related. Returns findings with file, line, "
            "queryset_var, accessed relations, suggested_fix, and confidence "
            "(high/medium). Zero-runtime, no DB, no Django boot." + _WORKSPACE_HINT
        ),
    },
}


# ---------------------------------------------------------------------------
# Server bootstrap — lazy-imports mcp so the base install stays zero-dep
# ---------------------------------------------------------------------------


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
        "django-orm-lens MCP ready - "
        "if it saves your agent time, a star helps: "
        "https://github.com/FROWNINGdev/django-orm-lens",
        file=sys.stderr,
    )

    def _register(name: str, description: str, handler):
        """Register one tool.

        Every tool declares ``workspace_root: str = ""`` in its Python
        signature so FastMCP includes it in the ``inputSchema`` served to
        ``tools/list``. Agents that pass the argument reach the handler with
        the value; agents that omit it fall through to env var / cwd via the
        resolution chain in :mod:`django_orm_lens.workspace`.
        """
        if name == "list_apps":
            @server.tool(name=name, description=description)
            def list_apps(workspace_root: str = "") -> str:
                return handler({"workspace_root": workspace_root})
        elif name == "list_models":
            @server.tool(name=name, description=description)
            def list_models(app: str = "", workspace_root: str = "") -> str:
                args: Dict[str, Any] = {"workspace_root": workspace_root}
                if app:
                    args["app"] = app
                return handler(args)
        elif name == "describe_model":
            @server.tool(name=name, description=description)
            def describe_model(model: str, workspace_root: str = "") -> str:
                return handler({"model": model, "workspace_root": workspace_root})
        elif name == "find_relations":
            @server.tool(name=name, description=description)
            def find_relations(model: str, workspace_root: str = "") -> str:
                return handler({"model": model, "workspace_root": workspace_root})
        elif name == "cascade_preview":
            @server.tool(name=name, description=description)
            def cascade_preview(
                app_label: str, model_name: str, workspace_root: str = ""
            ) -> str:
                return handler(
                    {
                        "app_label": app_label,
                        "model_name": model_name,
                        "workspace_root": workspace_root,
                    }
                )
        elif name == "er_diagram":
            @server.tool(name=name, description=description)
            def er_diagram(workspace_root: str = "") -> str:
                return handler({"workspace_root": workspace_root})
        elif name == "describe_migration_dependency":
            @server.tool(name=name, description=description)
            def describe_migration_dependency(
                app_label: str, workspace_root: str = ""
            ) -> str:
                return handler(
                    {"app_label": app_label, "workspace_root": workspace_root}
                )
        elif name == "suggest_indexes":
            @server.tool(name=name, description=description)
            def suggest_indexes(
                app_label: str, model_name: str, workspace_root: str = ""
            ) -> str:
                return handler(
                    {
                        "app_label": app_label,
                        "model_name": model_name,
                        "workspace_root": workspace_root,
                    }
                )
        elif name == "signal_graph":
            @server.tool(name=name, description=description)
            def signal_graph(workspace_root: str = "") -> str:
                return handler({"workspace_root": workspace_root})
        elif name == "nplusone_scan":
            @server.tool(name=name, description=description)
            def nplusone_scan(workspace_root: str = "") -> str:
                return handler({"workspace_root": workspace_root})

    for name, spec in TOOLS.items():
        _register(name, spec["description"], spec["handler"])

    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
