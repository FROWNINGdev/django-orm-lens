"""MCP (Model Context Protocol) stdio server for Django ORM Lens.

Exposes five read-only tools that any MCP-compatible AI agent can call:

* ``list_apps``       — list Django apps with model counts
* ``list_models``    — flat ``app.Model`` list, optional app filter
* ``describe_model`` — full field/relation/Meta detail for one model
* ``find_relations`` — inbound + outbound relations for one model
* ``er_diagram``     — Mermaid ER diagram string for the whole workspace

The ``mcp`` runtime package is loaded lazily so ``pip install django-orm-lens``
stays zero-dep. Install with the extras: ``pip install 'django-orm-lens[mcp]'``.

Config: workspace root taken from ``$DJANGO_ORM_LENS_ROOT`` if set, else ``cwd``.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

from .cli import _build_mermaid
from .parser import DEFAULT_EXCLUDES, scan_workspace


def _workspace_root() -> str:
    return os.environ.get("DJANGO_ORM_LENS_ROOT") or os.getcwd()


def _tool_list_apps(_args: Dict[str, Any]) -> str:
    idx = scan_workspace(_workspace_root(), DEFAULT_EXCLUDES)
    return json.dumps(
        [
            {"name": a.name, "path": a.path, "models": len(a.models)}
            for a in idx.apps
        ],
        indent=2,
    )


def _tool_list_models(args: Dict[str, Any]) -> str:
    idx = scan_workspace(_workspace_root(), DEFAULT_EXCLUDES)
    only_app = (args or {}).get("app")
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


def _tool_describe_model(args: Dict[str, Any]) -> str:
    idx = scan_workspace(_workspace_root(), DEFAULT_EXCLUDES)
    ref = (args or {}).get("model", "")
    m = _find(idx, ref)
    if not m:
        return f"error: model {ref!r} not found"
    return json.dumps(m.to_dict(), indent=2)


def _tool_find_relations(args: Dict[str, Any]) -> str:
    idx = scan_workspace(_workspace_root(), DEFAULT_EXCLUDES)
    ref = (args or {}).get("model", "")
    m = _find(idx, ref)
    if not m:
        return f"error: model {ref!r} not found"
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
    tail = m.name
    for app in idx.apps:
        for other in app.models:
            if other is m:
                continue
            for f in other.fields:
                if not f.is_relation or not f.related_model:
                    continue
                t = f.related_model.split(".")[-1]
                if t == tail:
                    out["inbound"].append(
                        {
                            "from": f"{app.name}.{other.name}",
                            "field": f.name,
                            "kind": f.relation_kind,
                        }
                    )
    return json.dumps(out, indent=2)


def _tool_er_diagram(_args: Dict[str, Any]) -> str:
    idx = scan_workspace(_workspace_root(), DEFAULT_EXCLUDES)
    return _build_mermaid(idx)


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
        "description": "Outbound (this model → others) and inbound (others → this) relations.",
    },
    "er_diagram": {
        "handler": _tool_er_diagram,
        "description": "Emit a Mermaid erDiagram for the whole workspace.",
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
        elif name == "er_diagram":
            @server.tool(name=name, description=description)
            def er_diagram() -> str:
                return handler({})

    for name, spec in TOOLS.items():
        _register(name, spec["description"], spec["handler"])

    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
