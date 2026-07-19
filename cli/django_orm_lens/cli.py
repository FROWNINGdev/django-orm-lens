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
import json
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__
from .formatters import format_hover, format_index, format_model
from .models import ParsedModel, WorkspaceIndex
from .parser import DEFAULT_EXCLUDES, _iter_python_files, scan_workspace


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
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print scan timing + file/app/model counts to stderr",
    )


def _resolve_excludes(cli_excludes: Optional[Sequence[str]]) -> Sequence[str]:
    return tuple(cli_excludes) if cli_excludes else DEFAULT_EXCLUDES


def _load_index(args: argparse.Namespace) -> WorkspaceIndex:
    """Validate ``--path`` exists before scanning. Silent-empty result on a
    typo'd path is a common confusion — surface it as an error.
    """
    import os
    if not os.path.isdir(args.path):
        print(
            f"error: --path {args.path!r} is not a directory",
            file=sys.stderr,
        )
        raise SystemExit(2)
    excludes = _resolve_excludes(args.exclude)
    if not getattr(args, "verbose", False):
        return scan_workspace(args.path, excludes)

    start = time.perf_counter()
    index = scan_workspace(args.path, excludes)
    elapsed_ms = (time.perf_counter() - start) * 1000
    file_count = sum(1 for _ in _iter_python_files(Path(args.path).resolve(), excludes))
    print(
        f"scanned {file_count} files in {elapsed_ms:.0f}ms, "
        f"found {len(index.apps)} apps / {index.total_models()} models",
        file=sys.stderr,
    )
    return index


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
    idx = _load_index(args)
    print(format_index(idx, args.format))
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    idx = _load_index(args)
    model = _find_model(idx, args.model)
    if model is None:
        print(f"error: model {args.model!r} not found", file=sys.stderr)
        return 2
    print(format_model(model, args.format))
    return 0


def _cmd_hover(args: argparse.Namespace) -> int:
    idx = _load_index(args)
    model = _find_model(idx, args.model)
    if model is None:
        print(f"error: model {args.model!r} not found", file=sys.stderr)
        return 2
    print(format_hover(model))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    idx = _load_index(args)
    fmt = args.format.lower()
    if fmt == "json":
        payload = [{"app": app.name, "model": m.name} for app in idx.apps for m in app.models]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if fmt == "text":
        for app in idx.apps:
            for m in app.models:
                print(f"{app.name}.{m.name}")
        return 0
    raise ValueError(f"Unknown format: {fmt!r}. Use text | json.")


def _cmd_er(args: argparse.Namespace) -> int:
    idx = _load_index(args)
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

    def sanitize_label(s: str) -> str:
        return "".join(ch if (ch.isalnum() or ch in "_.- ") else "_" for ch in s)

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
                parts = [sanitize_label(f.name)]
                if f.on_delete:
                    parts.append(sanitize_label(f.on_delete))
                if f.through_model:
                    parts.append(f"through {sanitize_label(f.through_model)}")
                if f.related_name:
                    parts.append(f"as {sanitize_label(f.related_name)}")
                label = (
                    f"{parts[0]} [{', '.join(parts[1:])}]"
                    if len(parts) > 1
                    else parts[0]
                )
                lines.append(
                    f'  {safe(model.name)} {arrow} {safe(target)} : "{label}"'
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
    sub = p.add_subparsers(dest="command")
    p.set_defaults(func=_cmd_hello)

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
    lst.add_argument(
        "--format", "-f", choices=("text", "json"), default="text"
    )
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


def _cmd_hello(_args: argparse.Namespace) -> int:
    print("django-orm-lens — static analysis for Django models.")
    print()
    print("commands:")
    print("  scan               Scan the current directory for Django apps + models")
    print("  list               Flat app.Model list, pipes into shell")
    print("  describe <model>   Full field/relation/Meta detail for one model")
    print("  hover <model>      Compact hover-card markdown for a model")
    print("  er                 Emit Mermaid ER diagram (stdout or file)")
    print("  mcp                Run the MCP stdio server for AI coding agents")
    print()
    print("run `django-orm-lens <command> --help` for options.")
    print("docs: https://github.com/FROWNINGdev/django-orm-lens")
    print()
    print("if this saves you a search, star helps others find it:")
    print("  https://github.com/FROWNINGdev/django-orm-lens")
    return 0


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
