"""Blast radius — one review-time answer for "what does this schema change hit?"

Three analyzers already exist in this package and each answers a third of the
question:

* :func:`~.migrations_parser.analyze_migration_risks` — *is this migration
  dangerous on its own?*
* :func:`~.impact.scan_impact` — *what code still reads the thing it touches?*
* :func:`~.models.cascade_preview` — *what does deleting a row take down?*

Run separately they leave the reviewer to join the results by hand, which in
practice nobody does. This module joins them: every destructive migration
operation becomes a *target*, and each target carries its risks, the code that
still references it, and — for whole-model operations — the cascade fallout.

Deliberately git-free. The scan describes the workspace as it stands, so it
works on a cold clone, in a dirty tree, and in CI with a shallow checkout,
consistent with the rest of the tool. Narrowing to what a PR changed is the
caller's job: pass ``only_migrations`` with the changed migration paths.
"""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .impact import ImpactFinding, group_by_layer, scan_impact
from .migrations_parser import MigrationRisk, analyze_migration_risks
from .models import WorkspaceIndex, cascade_preview, find_model
from .stats import ProductionStats, TableStats

# Operations that can break running code. `AddField` is excluded on purpose:
# adding a column cannot orphan a reader, so its risks are reported without a
# reference scan. The migration-risk analyzer still flags it separately.
DESTRUCTIVE_OPERATIONS: frozenset[str] = frozenset(
    {"RemoveField", "DeleteModel", "RenameField", "RenameModel", "AlterField"}
)

# Operations that change a whole model rather than one column — only these get
# a cascade preview, since cascade is a per-model question.
MODEL_LEVEL_OPERATIONS: frozenset[str] = frozenset({"DeleteModel", "RenameModel"})

SEVERITY_ORDER: tuple[str, ...] = ("critical", "warning", "info")
_SEVERITY_RANK = {name: i for i, name in enumerate(SEVERITY_ORDER)}


@dataclass
class Target:
    """One thing a migration touches, with everything known about it."""

    app: str
    model: str | None
    field: str | None
    # Qualified `dataclasses.field` on purpose: the `field` attribute above
    # shadows a bare `field` import inside this class body.
    operations: set[str] = dataclasses.field(default_factory=set)
    risks: list[MigrationRisk] = dataclasses.field(default_factory=list)
    impact: list[ImpactFinding] = dataclasses.field(default_factory=list)
    cascade: dict[str, Any] | None = None
    table_stats: TableStats | None = None
    """Only set when the caller supplied a --stats file *and* the table
    appeared in it. Absent means unknown, never zero."""

    @property
    def label(self) -> str:
        """Human-readable name — ``blog.Post.author`` or ``blog.Post``."""
        parts = [self.app]
        if self.model:
            parts.append(self.model)
        if self.field:
            parts.append(self.field)
        return ".".join(parts)

    @property
    def needle(self) -> str | None:
        """The identifier to search the codebase for."""
        return self.field or self.model

    @property
    def worst_severity(self) -> str:
        if not self.risks:
            return "info"
        return min(
            (r.severity for r in self.risks),
            key=lambda s: _SEVERITY_RANK.get(s, len(SEVERITY_ORDER)),
        )

    def impact_counts(self) -> dict[str, int]:
        counts = {"certain": 0, "likely": 0, "possibly": 0}
        for f in self.impact:
            if f.confidence in counts:
                counts[f.confidence] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.label,
            "app": self.app,
            "model": self.model,
            "field": self.field,
            "operations": sorted(self.operations),
            "worstSeverity": self.worst_severity,
            "risks": [r.to_dict() for r in self.risks],
            "impact": {
                "counts": self.impact_counts(),
                "byLayer": {
                    layer: [f.to_dict() for f in items]
                    for layer, items in group_by_layer(self.impact).items()
                },
            },
            "cascade": self.cascade,
            "tableStats": self.table_stats.to_dict() if self.table_stats else None,
        }


@dataclass
class BlastRadiusReport:
    """The joined result for a whole workspace."""

    targets: list[Target] = dataclasses.field(default_factory=list)
    unscanned_risks: list[MigrationRisk] = dataclasses.field(default_factory=list)
    """Risks on non-destructive operations — reported, but no reference scan."""

    @property
    def critical_count(self) -> int:
        from_targets = sum(
            1 for t in self.targets for r in t.risks if r.severity == "critical"
        )
        from_rest = sum(
            1 for r in self.unscanned_risks if r.severity == "critical"
        )
        return from_targets + from_rest

    def to_dict(self) -> dict[str, Any]:
        return {
            "targets": [t.to_dict() for t in self.targets],
            "unscannedRisks": [r.to_dict() for r in self.unscanned_risks],
            "summary": {
                "targets": len(self.targets),
                "criticalRisks": self.critical_count,
                "certainReferences": sum(
                    t.impact_counts()["certain"] for t in self.targets
                ),
            },
        }


def _risk_sort_key(r: MigrationRisk) -> tuple[int, str, int]:
    return (
        _SEVERITY_RANK.get(r.severity, len(SEVERITY_ORDER)),
        r.file_path,
        r.line_number,
    )


def _target_sort_key(t: Target) -> tuple[int, int, str]:
    # Worst severity first, then most certain references, then name.
    return (
        _SEVERITY_RANK.get(t.worst_severity, len(SEVERITY_ORDER)),
        -t.impact_counts()["certain"],
        t.label,
    )


def _matches_filter(risk: MigrationRisk, only: set[str] | None) -> bool:
    if only is None:
        return True
    if risk.file_path in only:
        return True
    try:
        return str(Path(risk.file_path).resolve()) in only
    except OSError:
        return False


def analyze_blast_radius(
    root: str | Path,
    *,
    index: WorkspaceIndex | None = None,
    only_migrations: Sequence[str] | None = None,
    risks: Iterable[MigrationRisk] | None = None,
    stats: ProductionStats | None = None,
    cascade: bool = True,
) -> BlastRadiusReport:
    """Join migration risks, code references and cascade fallout.

    :param root: workspace root.
    :param index: parsed workspace, reused for cascade previews. When ``None``
        the cascade section is skipped rather than triggering a second scan —
        callers that want it pass the index they already have.
    :param only_migrations: restrict to these migration files (a PR's changed
        paths). ``None`` scans every migration in the workspace.
    :param risks: pre-computed risks, mostly for tests.
    :param stats: optional production table statistics. Turns "this table is
        probably populated" into an estimated row count. See :mod:`.stats`.
    :param cascade: set ``False`` to skip cascade previews while still using
        ``index`` for other lookups — ``--stats`` needs the index to resolve
        ``Meta.db_table``, but that must not silently re-enable cascade.
    """
    root_path = Path(root).resolve()
    all_risks = (
        list(risks) if risks is not None else analyze_migration_risks(str(root_path))
    )

    only: set[str] | None = None
    if only_migrations is not None:
        only = set()
        for p in only_migrations:
            # Both spellings: callers pass repo-relative paths (a PR diff) but
            # risks carry whatever form the scan produced.
            only.add(p)
            with contextlib.suppress(OSError):
                only.add(str(Path(p).resolve()))

    report = BlastRadiusReport()
    by_key: dict[tuple[str, str | None, str | None], Target] = {}

    for risk in all_risks:
        if not _matches_filter(risk, only):
            continue
        if risk.operation not in DESTRUCTIVE_OPERATIONS:
            report.unscanned_risks.append(risk)
            continue
        # A field-level operation keys on the field; a model-level one keys on
        # the model, so two RemoveFields on the same model stay distinct while
        # a DeleteModel collapses into one target.
        is_model_level = risk.operation in MODEL_LEVEL_OPERATIONS
        key = (risk.app, risk.model, None if is_model_level else risk.field)
        target = by_key.get(key)
        if target is None:
            target = Target(
                app=risk.app,
                model=risk.model,
                field=None if is_model_level else risk.field,
            )
            by_key[key] = target
        target.operations.add(risk.operation)
        target.risks.append(risk)

    # One workspace walk per distinct identifier, not per risk — several risks
    # on the same field share a single scan.
    scanned: dict[str, list[ImpactFinding]] = {}
    for target in by_key.values():
        needle = target.needle
        if not needle:
            continue
        if needle not in scanned:
            scanned[needle] = scan_impact(root_path, needle)
        target.impact = scanned[needle]
        if cascade and index is not None and target.model and not target.field:
            ref = f"{target.app}.{target.model}"
            preview = cascade_preview(index, ref)
            target.cascade = None if "error" in preview else preview
        if stats is not None and target.model:
            # Meta.db_table wins over Django's <app>_<model> default, so the
            # lookup needs the parsed model when we have one.
            meta = None
            if index is not None:
                parsed = find_model(index, f"{target.app}.{target.model}")
                meta = parsed.meta if parsed else None
            target.table_stats = stats.for_model(target.app, target.model, meta)

    for target in by_key.values():
        target.risks.sort(key=_risk_sort_key)
    report.targets = sorted(by_key.values(), key=_target_sort_key)
    report.unscanned_risks.sort(key=_risk_sort_key)
    return report


# ----------------------------  rendering  -------------------------------

_SEVERITY_MARK = {"critical": "!!", "warning": " !", "info": "  "}


def _rel(root: Path, path: str) -> str:
    """Repo-relative POSIX path — CI logs and PR comments read better."""
    try:
        return Path(path).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return path.replace("\\", "/")


def _cascade_line(cascade: dict[str, Any]) -> str:
    kills = len(cascade.get("cascade_kills", []))
    nulls = len(cascade.get("set_null", []))
    prot = len(cascade.get("protected", []))
    return f"cascade: {kills} deleted, {nulls} nulled, {prot} blocked by PROTECT"


def format_text(report: BlastRadiusReport, root: str | Path = ".") -> str:
    """Human-readable terminal output."""
    root_path = Path(root).resolve()
    out: list[str] = []
    if not report.targets and not report.unscanned_risks:
        return "no schema-changing operations found — nothing to review."

    for t in report.targets:
        counts = t.impact_counts()
        ops = "/".join(sorted(t.operations))
        out.append(
            f"{_SEVERITY_MARK.get(t.worst_severity, '  ')} {t.label}  [{ops}]"
        )
        for r in t.risks:
            loc = f"{_rel(root_path, r.file_path)}:{r.line_number}"
            out.append(f"     {r.severity}: {r.rule} ({r.confidence})  {loc}")
            out.append(f"       {r.description}")
            out.append(f"       fix: {r.mitigation}")
        if t.table_stats:
            out.append(f"     {t.table_stats.summary()}")
        if t.cascade:
            out.append(f"     {_cascade_line(t.cascade)}")
        total = counts["certain"] + counts["likely"] + counts["possibly"]
        if total:
            out.append(
                f"     still referenced in {total} place(s): "
                f"{counts['certain']} certain, {counts['likely']} likely, "
                f"{counts['possibly']} possibly"
            )
            for layer, items in group_by_layer(t.impact).items():
                shown = [f for f in items if f.confidence != "possibly"][:5]
                for f in shown:
                    loc = f"{_rel(root_path, f.file_path)}:{f.line + 1}"
                    out.append(f"       {layer}/{f.confidence}  {loc}  {f.snippet}")
        else:
            out.append("     no remaining references found in the workspace")
        out.append("")

    if report.unscanned_risks:
        out.append("other migration risks (no reference scan — nothing to orphan):")
        for r in report.unscanned_risks:
            loc = f"{_rel(root_path, r.file_path)}:{r.line_number}"
            out.append(f"  {r.severity}: {r.rule}  {loc}")
        out.append("")

    s = report.to_dict()["summary"]
    out.append(
        f"summary: {s['targets']} target(s), {s['criticalRisks']} critical risk(s), "
        f"{s['certainReferences']} certain reference(s)"
    )
    return "\n".join(out)


COMMENT_MARKER = "<!-- django-orm-lens: blast-radius -->"
"""Hidden anchor so CI can update its previous comment instead of posting a
new one on every push. Must be the first line of the rendered markdown —
the Action greps for it verbatim."""


def format_markdown(report: BlastRadiusReport, root: str | Path = ".") -> str:
    """PR-comment markdown. Collapsed detail so the comment stays scannable."""
    root_path = Path(root).resolve()
    if not report.targets and not report.unscanned_risks:
        return (
            f"{COMMENT_MARKER}\n"
            "### Django ORM Lens — blast radius\n\n"
            "No schema-changing operations found. Nothing to review here."
        )

    s = report.to_dict()["summary"]
    out: list[str] = [
        COMMENT_MARKER,
        "### Django ORM Lens — blast radius",
        "",
        f"**{s['targets']}** target(s) · **{s['criticalRisks']}** critical risk(s) · "
        f"**{s['certainReferences']}** certain reference(s) still in code",
        "",
    ]

    for t in report.targets:
        counts = t.impact_counts()
        ops = ", ".join(sorted(t.operations))
        badge = {"critical": "🔴", "warning": "🟡", "info": "⚪"}.get(
            t.worst_severity, "⚪"
        )
        out.append(f"#### {badge} `{t.label}` — {ops}")
        out.append("")
        for r in t.risks:
            loc = f"{_rel(root_path, r.file_path)}:{r.line_number}"
            out.append(f"- **{r.severity}** `{r.rule}` ({r.confidence}) — `{loc}`")
            out.append(f"  {r.description}")
            out.append(f"  _Fix:_ {r.mitigation}")
        if t.table_stats:
            ts = t.table_stats
            note = " — **this locks a large table**" if ts.is_large else ""
            note = " — table is empty in production" if ts.is_empty else note
            out.append(f"- {ts.summary()}{note}")
        if t.cascade:
            out.append(f"- {_cascade_line(t.cascade)}")
        total = counts["certain"] + counts["likely"] + counts["possibly"]
        out.append("")
        if total:
            out.append(
                f"<details><summary>Still referenced in {total} place(s) — "
                f"{counts['certain']} certain, {counts['likely']} likely, "
                f"{counts['possibly']} possibly</summary>\n"
            )
            out.append("| Layer | Confidence | Location | Code |")
            out.append("| --- | --- | --- | --- |")
            for layer, items in group_by_layer(t.impact).items():
                for f in items[:10]:
                    loc = f"{_rel(root_path, f.file_path)}:{f.line + 1}"
                    snippet = f.snippet.replace("|", "\\|")[:80]
                    out.append(
                        f"| {layer} | {f.confidence} | `{loc}` | `{snippet}` |"
                    )
            out.append("\n</details>")
        else:
            out.append("No remaining references found in the workspace.")
        out.append("")

    if report.unscanned_risks:
        out.append(
            f"<details><summary>{len(report.unscanned_risks)} other migration "
            "risk(s)</summary>\n"
        )
        for r in report.unscanned_risks:
            loc = f"{_rel(root_path, r.file_path)}:{r.line_number}"
            out.append(f"- **{r.severity}** `{r.rule}` — `{loc}` — {r.description}")
        out.append("\n</details>")
        out.append("")

    out.append(
        "<sub>Static analysis — no database, no Django boot. "
        "`possibly` findings are heuristic by design.</sub>"
    )
    return "\n".join(out)


def format_blast_radius(
    report: BlastRadiusReport, fmt: str = "text", root: str | Path = "."
) -> str:
    """Dispatch to the requested renderer. ``json`` is handled by the caller."""
    if fmt == "markdown":
        return format_markdown(report, root)
    if fmt == "github":
        from .ci_formats import blast_radius_github

        return blast_radius_github(report, str(Path(root).resolve()))
    return format_text(report, root)
