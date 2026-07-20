"""Output formatters for the CLI and MCP server.

Renders a :class:`WorkspaceIndex` (or a single :class:`ParsedModel`) as JSON,
GitHub-flavoured Markdown, or a plain ASCII table. Zero third-party deps.
"""

from __future__ import annotations

import json
from typing import List

from .models import ParsedModel, WorkspaceIndex


def format_index(index: WorkspaceIndex, fmt: str = "json") -> str:
    fmt = fmt.lower()
    if fmt == "json":
        return json.dumps(index.to_dict(), indent=2, ensure_ascii=False)
    if fmt == "markdown":
        return _index_markdown(index)
    if fmt == "table":
        return _index_table(index)
    raise ValueError(f"Unknown format: {fmt!r}. Use json | markdown | table.")


def format_model(model: ParsedModel, fmt: str = "markdown") -> str:
    fmt = fmt.lower()
    if fmt == "json":
        return json.dumps(model.to_dict(), indent=2, ensure_ascii=False)
    if fmt == "markdown":
        return _model_markdown(model)
    if fmt == "table":
        return _model_table(model)
    raise ValueError(f"Unknown format: {fmt!r}. Use json | markdown | table.")


def format_hover(model: ParsedModel) -> str:
    """Compact hover-card markdown — identical spirit to the VS Code hover."""
    lines: List[str] = []
    bases = ", ".join(model.base_classes) or "models.Model"
    lines.append(f"**{model.app_name}.{model.name}**")
    lines.append(f"_{bases}_")
    scalars = [f for f in model.fields if not f.is_relation]
    relations = [f for f in model.fields if f.is_relation]
    if scalars:
        lines.append("")
        lines.append("**Fields**")
        for f in scalars[:12]:
            lines.append(f"- `{f.name}` — {f.type}")
        if len(scalars) > 12:
            lines.append(f"- _…and {len(scalars) - 12} more_")
    if relations:
        lines.append("")
        lines.append("**Relations**")
        for f in relations:
            lines.append(
                f"- `{f.name}` → **{f.related_model or '?'}** _({f.relation_kind})_"
            )
    return "\n".join(lines)


def _index_markdown(index: WorkspaceIndex) -> str:
    if not index.apps:
        return "_No Django models found._"
    out: List[str] = ["# Django models\n"]
    for app in index.apps:
        out.append(
            f"## {app.name} ({len(app.models)} model{'s' if len(app.models) != 1 else ''})"
        )
        for m in app.models:
            out.append(_model_markdown(m))
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def _model_markdown(model: ParsedModel) -> str:
    bases = ", ".join(model.base_classes) or "models.Model"
    rows = [
        f"### `{model.app_name}.{model.name}`",
        f"_class {model.name}({bases})_",
        f"`{model.file_path}:{model.line_number + 1}`",
    ]
    scalars = [f for f in model.fields if not f.is_relation]
    relations = [f for f in model.fields if f.is_relation]
    if scalars:
        rows.append("\n**Fields**\n")
        rows.append("| Field | Type | Args |")
        rows.append("| --- | --- | --- |")
        for f in scalars:
            args = _truncate(f.args, 60).replace("|", r"\|")
            rows.append(f"| `{f.name}` | {f.type} | `{args}` |")
    if relations:
        rows.append("\n**Relations**\n")
        rows.append("| Field | Kind | Target |")
        rows.append("| --- | --- | --- |")
        for f in relations:
            rows.append(
                f"| `{f.name}` | {f.relation_kind} | **{f.related_model or '?'}** |"
            )
    if model.meta:
        rows.append("\n**Meta**\n")
        for k, v in model.meta.items():
            rows.append(f"- `{k}` = {_truncate(v, 80)}")
    return "\n".join(rows)


def _index_table(index: WorkspaceIndex) -> str:
    header = ("App", "Model", "Fields", "Rels", "File")
    rows: List[tuple] = []
    for app in index.apps:
        for m in app.models:
            scalars = sum(1 for f in m.fields if not f.is_relation)
            rels = sum(1 for f in m.fields if f.is_relation)
            rows.append(
                (
                    app.name,
                    m.name,
                    str(scalars),
                    str(rels),
                    f"{m.file_path}:{m.line_number + 1}",
                )
            )
    return _render_table(header, rows)


def _model_table(model: ParsedModel) -> str:
    header = ("Field", "Type", "Rel", "Target")
    rows: List[tuple] = []
    for f in model.fields:
        rows.append(
            (
                f.name,
                f.type,
                "yes" if f.is_relation else "",
                f.related_model or "",
            )
        )
    top = f"{model.app_name}.{model.name}  ({model.file_path}:{model.line_number + 1})\n"
    return top + _render_table(header, rows)


def _render_table(header: tuple, rows: List[tuple]) -> str:
    # Pad short rows with "" so callers that build partial tuples don't
    # trigger IndexError inside the width-computation genexpr.
    ncols = len(header)
    padded_rows = [tuple(r) + ("",) * max(0, ncols - len(r)) for r in rows]
    all_rows = [header] + padded_rows
    widths = [max(len(str(r[i])) for r in all_rows) for i in range(ncols)]
    sep = "  "

    def fmt(r):
        return sep.join(str(v).ljust(widths[i]) for i, v in enumerate(r[:ncols]))

    lines = [fmt(header), sep.join("-" * w for w in widths)]
    for r in padded_rows:
        lines.append(fmt(r))
    return "\n".join(lines)


def _truncate(s: str, n: int) -> str:
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"
