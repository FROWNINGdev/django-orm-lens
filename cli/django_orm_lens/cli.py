"""Command-line entry point for ``django-orm-lens``.

Zero-dep argparse CLI. Commands mirror what the VS Code extension does:

  django-orm-lens scan       — walk workspace, list every model
  django-orm-lens describe   — one model in detail
  django-orm-lens er         — Mermaid ER diagram (stdout or file)
  django-orm-lens hover      — compact hover card for one model
  django-orm-lens list       — flat list ``app.Model`` for shell piping
  django-orm-lens mcp        — start the MCP stdio server (extras required)
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Sequence

from . import __version__
from .formatters import format_hover, format_index, format_model
from .models import ParsedModel, WorkspaceIndex
from .parser import DEFAULT_EXCLUDES, scan_workspace


def _add_scan_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--path",
        "-p",
        default=".",
        help="Workspace root to scan (default: current directory)",
    )
    p.add_argument(
        "--exclude",
        "-x",
        action="append",
        default=None,
        help="Glob to exclude, repeatable (default: migrations/, venv/, node_modules/)",
    )


def _resolve_excludes(cli_excludes: Optional[Sequence[str]]) -> Sequence[str]:
    return tuple(cli_excludes) if cli_excludes else DEFAULT_EXCLUDES


def _find_model(index: WorkspaceIndex, ref: str) -> Optional[ParsedModel]:
    if "." in ref:
        app_name, model_name = ref.split(".", 1)
        for app in index.apps:
            if app.name == app_name:
                for m in app.models:
                    if m.name == model_name:
                        return m
    for app in index.apps:
        for m in app.models:
            if m.name == ref:
                return m
    return None


def _cmd_scan(args: argparse.Namespace) -> int:
    idx = scan_workspace(args.path, _resolve_excludes(args.exclude))
    print(format_index(idx, args.format))
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    idx = scan_workspace(args.path, _resolve_excludes(args.exclude))
    model = _find_model(idx, args.model)
    if model is None:
        print(f"error: model {args.model!r} not found", file=sys.stderr)
        return 2
    print(format_model(model, args.format))
    return 0


def _cmd_hover(args: argparse.Namespace) -> int:
    idx = scan_workspace(args.path, _resolve_excludes(args.exclude))
    model = _find_model(idx, args.model)
    if model is None:
        print(f"error: model {args.model!r} not found", file=sys.stderr)
        return 2
    print(format_hover(model))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    idx = scan_workspace(args.path, _resolve_excludes(args.exclude))
    for app in idx.apps:
        for m in app.models:
            print(f"{app.name}.{m.name}")
    return 0


def _cmd_er(args: argparse.Namespace) -> int:
    idx = scan_workspace(args.path, _resolve_excludes(args.exclude))
    mermaid = _build_mermaid(idx)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(mermaid)
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(mermaid)
    return 0


def _build_mermaid(index: WorkspaceIndex) -> str:
    lines: List[str] = ["erDiagram"]
    model_names = {m.name for app in index.apps for m in app.models}

    def safe(s: str) -> str:
        return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in s)

    for app in index.apps:
        for model in app.models:
            lines.append(f"  {safe(model.name)} {{")
            for f in model.fields:
                if f.is_relation:
                    continue
                type_safe = "".join(ch for ch in f.type if ch.isalnum())
                name_safe = safe(f.name)
                lines.append(f"    {type_safe} {name_safe}")
            lines.append("  }")

    for app in index.apps:
        for model in app.models:
            for f in model.fields:
                if not f.is_relation or not f.related_model:
                    continue
                target = (
                    model.name
                    if f.related_model == "self"
                    else f.related_model.split(".")[-1]
                )
                if target not in model_names:
                    continue
                if f.relation_kind == "ManyToManyField":
                    arrow = "}o--o{"
                elif f.relation_kind == "OneToOneField":
                    arrow = "||--||"
                else:
                    arrow = "}o--||"
                lines.append(
                    f'  {safe(model.name)} {arrow} {safe(target)} : "{f.name}"'
                )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="django-orm-lens",
        description="Static analysis for Django models. Terminal + AI agent friendly.",
    )
    p.add_argument(
        "--version", action="version", version=f"django-orm-lens {__version__}"
    )
    sub = p.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan a workspace for Django models")
    _add_scan_flags(scan)
    scan.add_argument(
        "--format", "-f", choices=("json", "markdown", "table"), default="json"
    )
    scan.set_defaults(func=_cmd_scan)

    describe = sub.add_parser(
        "describe", help="Describe a single model (app.Model or Model)"
    )
    _add_scan_flags(describe)
    describe.add_argument("model", help="Model reference, e.g. blog.Post or Post")
    describe.add_argument(
        "--format", "-f", choices=("json", "markdown", "table"), default="markdown"
    )
    describe.set_defaults(func=_cmd_describe)

    hover = sub.add_parser("hover", help="Compact hover-card markdown for a model")
    _add_scan_flags(hover)
    hover.add_argument("model", help="Model reference, e.g. blog.Post or Post")
    hover.set_defaults(func=_cmd_hover)

    lst = sub.add_parser("list", help="Flat list of app.Model — pipes well into shell")
    _add_scan_flags(lst)
    lst.set_defaults(func=_cmd_list)

    er = sub.add_parser("er", help="Emit a Mermaid ER diagram (stdout or file)")
    _add_scan_flags(er)
    er.add_argument(
        "--output", "-o", default=None, help="Write diagram to file instead of stdout"
    )
    er.set_defaults(func=_cmd_er)

    mcp = sub.add_parser(
        "mcp",
        help="Run the MCP stdio server (requires 'pip install django-orm-lens[mcp]')",
    )
    mcp.set_defaults(func=_cmd_mcp)

    return p


def _cmd_mcp(_args: argparse.Namespace) -> int:
    try:
        from . import mcp_server
    except ImportError as e:
        print(
            "error: MCP server dependencies not installed.\n"
            "install with: pip install 'django-orm-lens[mcp]'\n"
            f"({e})",
            file=sys.stderr,
        )
        return 3
    return mcp_server.main()


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
