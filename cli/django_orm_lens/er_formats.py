"""Alternative ER-diagram serializers — DBML, D2, PlantUML, Graphviz DOT.

``er --format mermaid`` stays the default (GitHub renders Mermaid inline in
READMEs, issues, and PRs). These four cover the interchange formats the
wider database-tooling community actually shares diagrams in:

* **DBML** — the dbdiagram.io / dbdocs.io language. Paste the output into
  https://dbdiagram.io/d and you get an interactive, drag-to-arrange,
  shareable diagram. ``on_delete`` policies map onto DBML ref settings.
* **D2** — Terrastruct's declarative diagram language with a first-class
  ``sql_table`` shape. Render locally: ``d2 schema.d2 schema.svg``.
  Apps become nested containers, so big schemas stay readable.
* **PlantUML** — the long-standing IDE/enterprise staple with crow's-foot
  notation via the ``entity`` syntax.
* **Graphviz DOT** — the established graph interchange language emitted by
  ``django-extensions graph_models``. Render locally with ``dot -Tsvg``.

All four emitters walk the same :class:`~django_orm_lens.models.WorkspaceIndex`
the Mermaid builder uses, resolve ``settings.AUTH_USER_MODEL`` identically,
and skip relations whose target model lives outside the workspace — every
format draws the same graph.

Primary keys: Django adds an implicit ``id`` when no field declares
``primary_key=True``. The emitters mirror that — an explicit PK field is
used when present, otherwise an ``id (AutoField)`` row is synthesized so
refs always point at a declared column.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .models import (
    ParsedField,
    ParsedModel,
    WorkspaceIndex,
    find_user_model,
    resolve_related_tail,
)


@dataclass
class _Edge:
    """One resolved relation between two in-workspace models."""

    src: str  # "app.Model"
    field: str
    kind: str  # ForeignKey | OneToOneField | ManyToManyField
    target: str  # "app.Model"
    target_pk: str  # column name refs point at (explicit PK or "id")
    on_delete: str | None
    through: str | None


def _short_source(app_path: str, app_name: str, model: ParsedModel) -> str:
    """Workspace-relative source pointer for diagram notes.

    Absolute paths would leak the maintainer's machine layout into shared
    diagrams and make output non-reproducible across checkouts.
    """
    p = Path(model.file_path)
    try:
        return p.relative_to(Path(app_path).parent).as_posix()
    except ValueError:
        return f"{app_name}/{p.name}"


# ``f.args`` is raw source text, so tolerate any spacing around ``=``
# (black-formatted and hand-written styles alike).
_PK_RE = re.compile(r"\bprimary_key\s*=\s*True\b")


def _pk_field(model: ParsedModel) -> ParsedField | None:
    """Field declaring ``primary_key=True``, else ``None`` (implicit id)."""
    for f in model.fields:
        if _PK_RE.search(f.args or ""):
            return f
    return None


def _qualified_names(index: WorkspaceIndex) -> dict[str, str]:
    """Map bare model name → ``app.Model`` (first definition wins,
    matching the Mermaid builder's lookup semantics)."""
    out: dict[str, str] = {}
    for app in index.apps:
        for m in app.models:
            out.setdefault(m.name, f"{app.name}.{m.name}")
    return out


def _collect_edges(index: WorkspaceIndex) -> list[_Edge]:
    qualified = _qualified_names(index)
    # Refs must point at a column that actually exists on the target table —
    # the explicit PK when one is declared, Django's implicit "id" otherwise.
    pk_by_qualified: dict[str, str] = {}
    for app in index.apps:
        for m in app.models:
            pk = _pk_field(m)
            pk_by_qualified[f"{app.name}.{m.name}"] = (
                pk.name if pk is not None else "id"
            )
    user_model = find_user_model(index)
    user_name = user_model.name if user_model is not None else None
    edges: list[_Edge] = []
    for app in index.apps:
        for model in app.models:
            for f in model.fields:
                if not f.is_relation or not f.related_model:
                    continue
                tail = (
                    model.name
                    if f.related_model == "self"
                    else resolve_related_tail(f.related_model, user_name)
                )
                if tail is None or tail not in qualified:
                    continue
                target = qualified[tail]
                edges.append(
                    _Edge(
                        src=f"{app.name}.{model.name}",
                        field=f.name,
                        kind=f.relation_kind or "ForeignKey",
                        target=target,
                        target_pk=pk_by_qualified.get(target, "id"),
                        on_delete=f.on_delete,
                        through=f.through_model,
                    )
                )
    return edges


# ---------------------------------------------------------------------------
# DBML
# ---------------------------------------------------------------------------

# Django on_delete → DBML ref setting (https://dbml.dbdiagram.io/docs/#ref)
_DBML_ON_DELETE = {
    "CASCADE": "cascade",
    "SET_NULL": "set null",
    "SET_DEFAULT": "set default",
    "PROTECT": "restrict",
    "RESTRICT": "restrict",
    "DO_NOTHING": "no action",
}


def build_dbml(index: WorkspaceIndex) -> str:
    """DBML document — paste into https://dbdiagram.io/d."""
    lines: list[str] = [
        "// Django schema exported by django-orm-lens",
        "// Paste into https://dbdiagram.io/d — apps map to DBML schemas.",
        "",
    ]
    for app in index.apps:
        for model in app.models:
            pk = _pk_field(model)
            lines.append(f"Table {app.name}.{model.name} {{")
            if pk is None:
                lines.append("  id AutoField [pk]")
            for f in model.fields:
                if f.is_relation:
                    continue
                marker = " [pk]" if pk is not None and f.name == pk.name else ""
                lines.append(f"  {f.name} {f.type}{marker}")
            for f in model.fields:
                if f.is_relation:
                    lines.append(f"  {f.name} {f.relation_kind or 'ForeignKey'}")
            src = _short_source(app.path, app.name, model).replace("'", "\\'")
            lines.append(f"  Note: 'line {model.line_number} of {src}'")
            lines.append("}")
            lines.append("")

    for e in _collect_edges(index):
        if e.kind == "ManyToManyField":
            arrow = "<>"
        elif e.kind == "OneToOneField":
            arrow = "-"
        else:
            arrow = ">"
        settings = []
        if e.on_delete and e.on_delete.upper() in _DBML_ON_DELETE:
            settings.append(f"delete: {_DBML_ON_DELETE[e.on_delete.upper()]}")
        suffix = f" [{', '.join(settings)}]" if settings else ""
        lines.append(
            f"Ref: {e.src}.{e.field} {arrow} {e.target}.{e.target_pk}{suffix}"
        )
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# D2
# ---------------------------------------------------------------------------


def build_d2(index: WorkspaceIndex) -> str:
    """D2 document with ``sql_table`` shapes — render via ``d2 in.d2 out.svg``.

    Dotted keys nest models inside their app container automatically, which
    keeps multi-app schemas legible without manual layout.
    """
    lines: list[str] = [
        "# Django schema exported by django-orm-lens",
        "# Render: d2 schema.d2 schema.svg   (https://d2lang.com)",
        "",
        "direction: right",
        "",
    ]
    for app in index.apps:
        for model in app.models:
            pk = _pk_field(model)
            lines.append(f"{app.name}.{model.name}: {{")
            lines.append("  shape: sql_table")
            if pk is None:
                lines.append("  id: AutoField {constraint: primary_key}")
            for f in model.fields:
                if f.is_relation:
                    continue
                constraint = (
                    " {constraint: primary_key}"
                    if pk is not None and f.name == pk.name
                    else ""
                )
                lines.append(f"  {f.name}: {f.type}{constraint}")
            for f in model.fields:
                if f.is_relation:
                    lines.append(
                        f"  {f.name}: {f.relation_kind or 'ForeignKey'} "
                        "{constraint: foreign_key}"
                    )
            lines.append("}")
            lines.append("")

    for e in _collect_edges(index):
        label_parts = [e.kind]
        if e.on_delete:
            label_parts.append(e.on_delete)
        if e.through:
            label_parts.append(f"through {e.through}")
        label = " · ".join(label_parts)
        lines.append(f'{e.src}.{e.field} -> {e.target}.{e.target_pk}: "{label}"')
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# PlantUML
# ---------------------------------------------------------------------------


def _puml_alias(qualified: str) -> str:
    return qualified.replace(".", "_")


def build_plantuml(index: WorkspaceIndex) -> str:
    """PlantUML entity diagram with crow's-foot cardinality."""
    lines: list[str] = [
        "@startuml",
        "' Django schema exported by django-orm-lens",
        "hide circle",
        "skinparam linetype ortho",
        "skinparam roundCorner 8",
        "skinparam shadowing false",
        "",
    ]
    for app in index.apps:
        for model in app.models:
            qualified = f"{app.name}.{model.name}"
            pk = _pk_field(model)
            lines.append(f'entity "{qualified}" as {_puml_alias(qualified)} {{')
            if pk is None:
                lines.append("  * id : AutoField")
            else:
                lines.append(f"  * {pk.name} : {pk.type}")
            lines.append("  --")
            for f in model.fields:
                if f.is_relation:
                    continue
                if pk is not None and f.name == pk.name:
                    continue
                lines.append(f"  {f.name} : {f.type}")
            for f in model.fields:
                if f.is_relation:
                    lines.append(f"  {f.name} : {f.relation_kind or 'ForeignKey'}")
            lines.append("}")
            lines.append("")

    for e in _collect_edges(index):
        if e.kind == "ManyToManyField":
            arrow = "}o--o{"
        elif e.kind == "OneToOneField":
            arrow = "||--||"
        else:
            arrow = "}o--||"
        label_parts = [e.field]
        if e.on_delete:
            label_parts.append(e.on_delete)
        if e.through:
            label_parts.append(f"through {e.through}")
        lines.append(
            f"{_puml_alias(e.src)} {arrow} {_puml_alias(e.target)} : "
            f"{' / '.join(label_parts)}"
        )
    lines.append("")
    lines.append("@enduml")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Graphviz DOT
# ---------------------------------------------------------------------------


def _dot_quote(value: str) -> str:
    """Return a quoted DOT string with JSON-compatible escaping."""
    return json.dumps(value, ensure_ascii=False)


def _dot_table(model: ParsedModel) -> str:
    """Graphviz HTML label for one model and its fields."""
    pk = _pk_field(model)
    rows = [
        '<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4">',
        (
            '<TR><TD COLSPAN="2" BGCOLOR="#e8eef7">'
            f"<B>{html.escape(model.name)}</B></TD></TR>"
        ),
    ]
    if pk is None:
        rows.append("<TR><TD ALIGN=\"LEFT\"><B>id</B></TD><TD>AutoField · PK</TD></TR>")
    for field in model.fields:
        if field.is_relation:
            continue
        name = html.escape(field.name)
        field_type = html.escape(field.type)
        if pk is not None and field.name == pk.name:
            name = f"<B>{name}</B>"
            field_type += " · PK"
        rows.append(
            f'<TR><TD ALIGN="LEFT">{name}</TD><TD>{field_type}</TD></TR>'
        )
    for field in model.fields:
        if not field.is_relation:
            continue
        rows.append(
            '<TR><TD ALIGN="LEFT">'
            f"{html.escape(field.name)}</TD><TD>"
            f"{html.escape(field.relation_kind or 'ForeignKey')} · FK</TD></TR>"
        )
    rows.append("</TABLE>")
    return "<" + "".join(rows) + ">"


def build_dot(index: WorkspaceIndex) -> str:
    """Graphviz DOT diagram with app clusters and crow's-foot-style edges."""
    lines: list[str] = [
        "digraph django_orm_lens {",
        '  graph [rankdir="LR", compound="true", fontname="Helvetica"];',
        '  node [shape="plain", fontname="Helvetica"];',
        '  edge [fontname="Helvetica", fontsize="10"];',
        "",
    ]
    for app in index.apps:
        lines.append(f"  subgraph {_dot_quote(f'cluster_{app.name}')} {{")
        lines.append(f"    label={_dot_quote(app.name)};")
        lines.append('    color="#b8c2cc";')
        lines.append('    style="rounded";')
        for model in app.models:
            qualified = f"{app.name}.{model.name}"
            lines.append(
                f"    {_dot_quote(qualified)} [label={_dot_table(model)}];"
            )
        lines.append("  }")
        lines.append("")

    for edge in _collect_edges(index):
        if edge.kind == "ManyToManyField":
            arrowtail, arrowhead = "crow", "crow"
        elif edge.kind == "OneToOneField":
            arrowtail, arrowhead = "tee", "tee"
        else:
            arrowtail, arrowhead = "crow", "tee"
        label_parts = [f"{edge.field} → {edge.target_pk}", edge.kind]
        if edge.on_delete:
            label_parts.append(edge.on_delete)
        if edge.through:
            label_parts.append(f"through {edge.through}")
        lines.append(
            f"  {_dot_quote(edge.src)} -> {_dot_quote(edge.target)} "
            f"[label={_dot_quote(' / '.join(label_parts))}, dir=\"both\", "
            f"arrowtail={_dot_quote(arrowtail)}, "
            f"arrowhead={_dot_quote(arrowhead)}];"
        )

    lines.append("}")
    return "\n".join(lines) + "\n"


# Registry used by the CLI and the MCP server — mermaid is handled by the
# original builder in cli.py and stays the default.
ER_BUILDERS = {
    "dbml": build_dbml,
    "d2": build_d2,
    "plantuml": build_plantuml,
    "dot": build_dot,
}
