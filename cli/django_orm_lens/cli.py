"""Command-line entry point for ``django-orm-lens``.

Zero-dep argparse CLI. Commands mirror what the VS Code extension does:

  django-orm-lens scan       — walk workspace, list every model
  django-orm-lens describe   — one model in detail
  django-orm-lens er         — ER diagram: mermaid / dbml / d2 / plantuml
  django-orm-lens hover      — compact hover card for one model
  django-orm-lens list       — flat list ``app.Model`` for shell piping
  django-orm-lens diff       — compare two schema JSON dumps
  django-orm-lens nplusone   — static N+1 detector (text/json/sarif/github)
  django-orm-lens migration-risk  — flag risky migration operations
  django-orm-lens suggest-indexes — propose Meta.indexes from QuerySet usage
  django-orm-lens signals    — sender→signal→handler graph from @receiver
  django-orm-lens migration-deps  — per-app migration dependency DAG
  django-orm-lens cascade    — what delete() cascades to, by on_delete
  django-orm-lens mcp        — start the MCP stdio server (extras required)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .ci_formats import (
    migration_risks_github,
    migration_risks_sarif,
    nplusone_github,
    nplusone_sarif,
)
from .diff import diff_schemas, format_diff
from .er_formats import ER_BUILDERS
from .formatters import format_hover, format_index, format_model
from .migrations_parser import analyze_migration_risks, describe_migration_dependency
from .models import (
    ParsedModel,
    WorkspaceIndex,
    cascade_preview,
    find_model,
    find_user_model,
    resolve_related_tail,
)
from .parser import DEFAULT_EXCLUDES, _iter_python_files, scan_workspace
from .query_analyzer import scan_for_nplusone, suggest_indexes
from .signals_parser import signal_graph


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
    p.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        default=False,
        help="Suppress the 'no models.py found' hint on a zero-model scan",
    )


def _resolve_excludes(cli_excludes: Sequence[str] | None) -> Sequence[str]:
    return tuple(cli_excludes) if cli_excludes else DEFAULT_EXCLUDES


def _load_index(args: argparse.Namespace) -> WorkspaceIndex:
    """Validate ``--path`` exists before scanning. Silent-empty result on a
    typo'd path is a common confusion — surface it as an error.

    A zero-model result where no ``models.py`` was even walked is a second,
    quieter version of the same confusion (new users can't tell "it works,
    your app just has no models" from "the path is wrong"). Print a hint to
    stderr in that case, unless ``--quiet`` was passed. Exit code is
    untouched — an empty result is valid, not an error.
    """
    import os
    if not os.path.isdir(args.path):
        print(
            f"error: --path {args.path!r} is not a directory",
            file=sys.stderr,
        )
        raise SystemExit(2)
    excludes = _resolve_excludes(args.exclude)
    root = Path(args.path).resolve()
    verbose = getattr(args, "verbose", False)

    start = time.perf_counter() if verbose else 0.0
    index = scan_workspace(args.path, excludes)
    if verbose:
        elapsed_ms = (time.perf_counter() - start) * 1000
        # Read the count that scan_workspace already computed rather than
        # walking the tree a second time (matters on large monorepos).
        print(
            f"scanned {index.scanned_files} files in {elapsed_ms:.0f}ms, "
            f"found {len(index.apps)} apps / {index.total_models()} models",
            file=sys.stderr,
        )
    if index.total_models() == 0 and not getattr(args, "quiet", False):
        saw_models_file = any(_iter_python_files(root, excludes))
        if not saw_models_file:
            print(
                f"hint: no models.py found under {args.path}. Django apps typically have\n"
                "      <app>/models.py or <app>/models/*.py. Check the path or pass\n"
                "      --exclude to whitelist non-standard layouts.",
                file=sys.stderr,
            )
    return index


def _find_model(index: WorkspaceIndex, ref: str) -> ParsedModel | None:
    # Thin wrapper kept for local call sites; delegates to the shared helper
    # so lookup semantics match the MCP server.
    return find_model(index, ref)


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
    diagram = (
        _build_mermaid(idx)
        if args.format == "mermaid"
        else ER_BUILDERS[args.format](idx)
    )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(diagram)
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(diagram)
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    """Compare two schema JSON dumps and print the delta.

    Exit code: 0 when there is no diff (or ``--exit-zero`` was passed),
    1 when the schemas differ. This mirrors ``git diff --exit-code`` /
    ``diff -q`` conventions so it slots into CI without extra wiring.
    """
    try:
        with open(args.old, encoding="utf-8") as fh:
            old_schema = json.load(fh)
    except FileNotFoundError:
        print(f"error: {args.old!r} not found", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"error: {args.old!r} is not valid JSON: {e}", file=sys.stderr)
        return 2
    try:
        with open(args.new, encoding="utf-8") as fh:
            new_schema = json.load(fh)
    except FileNotFoundError:
        print(f"error: {args.new!r} not found", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"error: {args.new!r} is not valid JSON: {e}", file=sys.stderr)
        return 2

    result = diff_schemas(old_schema, new_schema)
    print(format_diff(result, args.format))
    if result.is_empty() or args.exit_zero:
        return 0
    return 1


def _cmd_nplusone(args: argparse.Namespace) -> int:
    """Static N+1 detector — flag FK/M2M access inside loops without select/prefetch."""
    idx = _load_index(args)
    # scan_for_nplusone accepts a WorkspaceIndex directly (see
    # query_analyzer._normalise_schema) — no need to pre-flatten. Passing idx
    # avoids importing the private _build_schema_from_index helper here.
    findings = scan_for_nplusone(args.path, idx)
    if args.confidence == "high":
        findings = [f for f in findings if f.confidence == "high"]
    elif args.confidence == "medium":
        findings = [f for f in findings if f.confidence in ("high", "medium")]
    if args.format == "json":
        print(json.dumps([f.to_dict() for f in findings], indent=2, ensure_ascii=False))
    elif args.format == "sarif":
        print(json.dumps(nplusone_sarif(findings), indent=2, ensure_ascii=False))
    elif args.format == "github":
        annotations = nplusone_github(findings)
        if annotations:
            print(annotations)
    else:
        if not findings:
            print("No N+1 anti-patterns detected.")
        for f in findings:
            print(f"{f.file}:{f.line}  [{f.confidence}]  loop={f.loop_var} qs={f.queryset_var}")
            print(f"  accessed: {', '.join(f.accessed)}")
            print(f"  fix:      {f.suggested_fix}")
    if not findings or args.exit_zero:
        return 0
    return 1


_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _cmd_migration_risk(args: argparse.Namespace) -> int:
    """Analyze <app>/migrations/*.py for operations dangerous in production."""
    findings = analyze_migration_risks(args.path)
    if args.severity != "all":
        threshold = _SEVERITY_ORDER[args.severity]
        findings = [
            f for f in findings
            if _SEVERITY_ORDER.get(f.severity, 99) <= threshold
        ]
    if args.format == "json":
        print(json.dumps(
            {"findings": [f.to_dict() for f in findings]},
            indent=2,
            ensure_ascii=False,
        ))
    elif args.format == "sarif":
        print(json.dumps(
            migration_risks_sarif(findings, root=args.path),
            indent=2,
            ensure_ascii=False,
        ))
    elif args.format == "github":
        annotations = migration_risks_github(findings, root=args.path)
        if annotations:
            print(annotations)
    else:
        if not findings:
            print("No risky migration operations found.")
        for f in findings:
            print(
                f"{f.file_path}:{f.line_number}  [{f.severity}/{f.confidence}]  "
                f"{f.operation} {f.app}.{f.model}"
                + (f".{f.field}" if f.field else "")
            )
            print(f"  rule:      {f.rule}")
            print(f"  risk:      {f.description}")
            print(f"  mitigate:  {f.mitigation}")
    # Exit 1 only when critical findings remain (matches severity=critical default)
    has_critical = any(f.severity == "critical" for f in findings)
    if not has_critical or args.exit_zero:
        return 0
    return 1


def _cmd_suggest_indexes(args: argparse.Namespace) -> int:
    """Propose ``Meta.indexes`` entries from observed QuerySet usage."""
    idx = _load_index(args)
    model = _find_model(idx, args.model)
    if model is None:
        print(f"error: model {args.model!r} not found", file=sys.stderr)
        return 2
    app_label = next((a.name for a in idx.apps if model in a.models), "")
    result = suggest_indexes(app_label, model.name, args.path, index=idx)
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(f"target: {result['target']}")
    proposed = result.get("proposed_indexes", [])
    if not proposed:
        print(
            "no new indexes proposed — observed query patterns are already "
            "covered by Meta.indexes (or usage is below the 2-site threshold)."
        )
    else:
        print(f"proposed Meta.indexes ({len(proposed)}):")
        for p in proposed:
            print(f"  models.Index(fields={p['fields']!r}),  # {p['reason']}")
    usages = result.get("filter_usages", [])
    if usages:
        print("\nobserved filter/get/exclude usage:")
        for u in usages[:10]:
            fld = u["field"]
            fld_txt = " + ".join(fld) if isinstance(fld, list) else fld
            print(f"  {fld_txt:<28} {u['sites']} sites   e.g. {u['example']}")
    return 0


def _cmd_signals(args: argparse.Namespace) -> int:
    """Print the sender→signal→handler graph from ``@receiver`` decorators."""
    idx = _load_index(args)
    result = signal_graph(args.path, idx)
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    edges = result.get("edges", [])
    if not edges:
        print("No signal receivers found.")
    for e in edges:
        marker = "" if e.get("builtin") else " [custom]"
        note = f"   ({e['note']})" if e.get("note") else ""
        print(
            f"{e.get('sender') or '<any>'} --{e.get('signal', '?')}{marker}--> "
            f"{e.get('handler', '?')}   {e.get('file', '')}{note}"
        )
    customs = result.get("custom_signals", [])
    if customs:
        print(f"\ncustom signals ({len(customs)}):")
        for c in customs:
            print(f"  {c.get('fqn') or c.get('name', '?')}")
    orphans = result.get("orphan_handlers", [])
    if orphans:
        print(f"\norphan handlers ({len(orphans)}):")
        for o in orphans:
            print(f"  {o.get('handler', '?')} — {o.get('reason', '')}")
    return 0


def _cmd_migration_deps(args: argparse.Namespace) -> int:
    """Print the migration dependency DAG for one app (text/json/mermaid)."""
    import os
    if not os.path.isdir(args.path):
        print(
            f"error: --path {args.path!r} is not a directory",
            file=sys.stderr,
        )
        return 2
    result = describe_migration_dependency(args.app, args.path)
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if "error" not in result else 2
    if "error" in result:
        print(
            f"error: {result['error']} for app {args.app!r} under {args.path}",
            file=sys.stderr,
        )
        return 2
    if args.format == "mermaid":
        print(_migration_deps_mermaid(result))
        return 0
    migs = result["migrations"]
    print(f"app: {result['app_label']}  ({len(migs)} migrations)")
    print(f"roots:  {', '.join(result['roots']) or '-'}")
    print(f"leaves: {', '.join(result['leaves']) or '-'}")
    if result["cross_app_deps"]:
        print("cross-app deps:")
        for dep in result["cross_app_deps"]:
            print(f"  -> {dep[0]}.{dep[1]}")
    print("chain:")
    for m in migs:
        deps = ", ".join(f"{d[0]}.{d[1]}" for d in m["dependencies"]) or "-"
        print(f"  {m['name']}")
        print(f"    deps: {deps}")
        if m["operations"]:
            ops = ", ".join(m["operations"][:4])
            if len(m["operations"]) > 4:
                ops += f", … +{len(m['operations']) - 4}"
            print(f"    ops:  {ops}")
    return 0


def _migration_deps_mermaid(result: dict) -> str:
    """Render the migration DAG as a Mermaid ``graph TD`` flowchart."""

    def nid(name: str) -> str:
        return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in name)

    app = result["app_label"]
    lines: list[str] = ["graph TD"]
    for m in result["migrations"]:
        lines.append(f'  {nid(m["name"])}["{m["name"]}"]')
    externals: set = set()
    for m in result["migrations"]:
        for dep in m["dependencies"]:
            if dep[0] == app:
                lines.append(f'  {nid(dep[1])} --> {nid(m["name"])}')
            else:
                ext = nid(f"{dep[0]}__{dep[1]}")
                if ext not in externals:
                    externals.add(ext)
                    lines.append(f'  {ext}(["{dep[0]}.{dep[1]}"]):::external')
                lines.append(f'  {ext} --> {nid(m["name"])}')
    if externals:
        lines.append("  classDef external stroke-dasharray: 5 5;")
    return "\n".join(lines)


def _cmd_cascade(args: argparse.Namespace) -> int:
    """Show what deleting one row of a model does to every related table."""
    idx = _load_index(args)
    result = cascade_preview(idx, args.model)
    if "error" in result:
        print(f"error: model {args.model!r} not found", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    kills = result["cascade_kills"]
    nulls = result["set_null"]
    prot = result["protected"]
    print(f"deleting one {result['target']} row:")
    if kills:
        print(f"  CASCADE-deletes rows in ({len(kills)}):")
        for e in kills:
            print(f"    - {e['model']}  via {e['via_field']}")
    if nulls:
        print(f"  sets FK to NULL/default in ({len(nulls)}):")
        for e in nulls:
            print(f"    - {e['model']}  via {e['via_field']}")
    if prot:
        print(f"  BLOCKED by PROTECT/RESTRICT from ({len(prot)}):")
        for e in prot:
            print(f"    - {e['model']}  via {e['via_field']}")
    if not (kills or nulls or prot):
        print("  no inbound relations — the delete is isolated.")
    return 0


def _build_mermaid(index: WorkspaceIndex) -> str:
    lines: list[str] = ["erDiagram"]
    model_names = {m.name for app in index.apps for m in app.models}
    user_model = find_user_model(index)
    user_model_name = user_model.name if user_model else None

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
                    else resolve_related_tail(f.related_model, user_model_name)
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

    er = sub.add_parser(
        "er",
        help="Emit an ER diagram — Mermaid, DBML, D2, or PlantUML (stdout or file)",
    )
    _add_scan_flags(er)
    er.add_argument(
        "--format", "-f",
        choices=("mermaid", "dbml", "d2", "plantuml"),
        default="mermaid",
        help=(
            "Diagram language. mermaid renders natively on GitHub; dbml "
            "pastes into dbdiagram.io; d2 renders via the d2 CLI; plantuml "
            "via any PlantUML server or IDE plugin"
        ),
    )
    er.add_argument(
        "--output", "-o", default=None, help="Write diagram to file instead of stdout"
    )
    er.set_defaults(func=_cmd_er)

    diff = sub.add_parser(
        "diff",
        help="Compare two schema JSON dumps (list/scan --format=json) and print the delta",
    )
    diff.add_argument("old", help="Path to the baseline JSON schema dump")
    diff.add_argument("new", help="Path to the updated JSON schema dump")
    diff.add_argument(
        "--format", "-f", choices=("text", "json"), default="text"
    )
    diff.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always exit 0 even when the schemas differ (default exits 1 on any diff)",
    )
    diff.set_defaults(func=_cmd_diff)

    npo = sub.add_parser(
        "nplusone",
        aliases=["n-plus-one"],
        help="Detect N+1 anti-patterns in views/tasks (FK/M2M access without select/prefetch)",
    )
    _add_scan_flags(npo)
    npo.add_argument(
        "--format", "-f",
        choices=("text", "json", "sarif", "github"),
        default="text",
        help=(
            "Output format. 'sarif' emits SARIF 2.1.0 for GitHub Code "
            "Scanning; 'github' emits ::warning workflow commands for "
            "zero-setup PR annotations"
        ),
    )
    npo.add_argument(
        "--confidence",
        choices=("high", "medium", "all"),
        default="all",
        help="Filter findings by minimum confidence (default: all)",
    )
    npo.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always exit 0 even when findings are present",
    )
    npo.set_defaults(func=_cmd_nplusone)

    mrisk = sub.add_parser(
        "migration-risk",
        help="Flag risky migration operations (NOT NULL without default, missing CONCURRENTLY, etc.)",
    )
    _add_scan_flags(mrisk)
    mrisk.add_argument(
        "--format", "-f",
        choices=("text", "json", "sarif", "github"),
        default="text",
        help=(
            "Output format. 'sarif' emits SARIF 2.1.0 for GitHub Code "
            "Scanning; 'github' emits ::error/::warning workflow commands "
            "for zero-setup PR annotations"
        ),
    )
    mrisk.add_argument(
        "--severity",
        choices=("critical", "warning", "info", "all"),
        default="critical",
        help="Minimum severity to report (default: critical)",
    )
    mrisk.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always exit 0 even when critical findings are present",
    )
    mrisk.set_defaults(func=_cmd_migration_risk)

    sidx = sub.add_parser(
        "suggest-indexes",
        aliases=["indexes"],
        help="Propose Meta.indexes from observed QuerySet usage (static)",
    )
    _add_scan_flags(sidx)
    sidx.add_argument("model", help="Model reference, e.g. blog.Post or Post")
    sidx.add_argument(
        "--format", "-f", choices=("text", "json"), default="text"
    )
    sidx.set_defaults(func=_cmd_suggest_indexes)

    signals = sub.add_parser(
        "signals",
        aliases=["signal-graph"],
        help="Sender→signal→handler graph from @receiver decorators",
    )
    _add_scan_flags(signals)
    signals.add_argument(
        "--format", "-f", choices=("text", "json"), default="text"
    )
    signals.set_defaults(func=_cmd_signals)

    mdeps = sub.add_parser(
        "migration-deps",
        aliases=["migration-dependencies"],
        help="Per-app migration dependency DAG (text, json, or mermaid)",
    )
    mdeps.add_argument(
        "app", help="Django app label (the folder containing migrations/)"
    )
    mdeps.add_argument(
        "--path", "-p", default=".",
        help="Workspace root to scan (default: current directory)",
    )
    mdeps.add_argument(
        "--format", "-f", choices=("text", "json", "mermaid"), default="text"
    )
    mdeps.set_defaults(func=_cmd_migration_deps)

    casc = sub.add_parser(
        "cascade",
        aliases=["cascade-preview"],
        help="What deleting one row cascades to, grouped by on_delete",
    )
    _add_scan_flags(casc)
    casc.add_argument("model", help="Model reference, e.g. blog.Post or Post")
    casc.add_argument(
        "--format", "-f", choices=("text", "json"), default="text"
    )
    casc.set_defaults(func=_cmd_cascade)

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
    print("  er                 ER diagram: mermaid / dbml / d2 / plantuml")
    print("  diff <old> <new>   Compare two schema JSON dumps and print the delta")
    print("  nplusone           Detect N+1 anti-patterns in views/tasks")
    print("  migration-risk     Flag risky migration operations")
    print("  suggest-indexes <model>   Propose Meta.indexes from QuerySet usage")
    print("  signals            Sender→signal→handler graph from @receiver")
    print("  migration-deps <app>      Migration dependency DAG (text/json/mermaid)")
    print("  cascade <model>    What delete() cascades to, grouped by on_delete")
    print("  mcp                Run the MCP stdio server for AI coding agents")
    print()
    print("run `django-orm-lens <command> --help` for options.")
    print("docs: https://github.com/FROWNINGdev/django-orm-lens")
    print()
    print("prefer a visual sidebar + ER diagram in your editor?")
    print("  VS Code / Cursor / Windsurf:  code --install-extension frowningdev.django-orm-lens")
    print("  VSCodium / code-server:       codium --install-extension frowningdev.django-orm-lens")
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
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except SystemExit as e:
        # Legacy validators (e.g. _load_index) raise SystemExit; translate to
        # a return code so in-process callers of main() get an int back
        # instead of the interpreter dying under them.
        code = e.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
