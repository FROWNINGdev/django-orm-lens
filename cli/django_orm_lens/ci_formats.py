"""CI-facing output formats — SARIF 2.1.0 and GitHub workflow commands.

Why a dedicated module
----------------------
``nplusone`` and ``migration-risk`` already exit ``1`` on findings, which
gates a pipeline — but a red ✗ with no annotations makes reviewers dig
through raw logs. These serializers turn findings into the two formats CI
platforms render natively:

* ``sarif``  — SARIF 2.1.0 for GitHub Code Scanning
  (``github/codeql-action/upload-sarif``) and any SARIF viewer. Findings
  show up in the repo Security tab and as PR annotations, with per-rule
  metadata and help links into ``docs/rules/``.
* ``github`` — GitHub Actions workflow commands
  (``::warning file=F,line=N::msg``). Zero-permission PR annotations: no
  upload step, no ``security-events: write`` scope — print and done.

Both are pure functions over the analyzer dataclasses (no filesystem, no
network) so they stay unit-testable and reusable from the MCP layer later.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import __version__
from .migrations_parser import MigrationRisk
from .query_analyzer import NPlusOneFinding

_SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/"
    "Schemata/sarif-schema-2.1.0.json"
)
_INFO_URI = "https://github.com/FROWNINGdev/django-orm-lens"
_RULES_DOCS = f"{_INFO_URI}/blob/main/docs/rules"

# migration-risk severity → SARIF result level
_SEVERITY_LEVEL = {"critical": "error", "warning": "warning", "info": "note"}
# nplusone confidence → SARIF result level
_CONFIDENCE_LEVEL = {"high": "warning", "medium": "note"}
# same mappings for workflow commands (GitHub calls "note" "notice")
_SEVERITY_CMD = {"critical": "error", "warning": "warning", "info": "notice"}
_CONFIDENCE_CMD = {"high": "warning", "medium": "notice"}


def _rel_posix(root: str | None, path: str) -> str:
    """Root-relative POSIX path for annotation URIs.

    ``NPlusOneFinding.file`` is already root-relative; migration-risk paths
    are whatever the walk produced (absolute root → absolute paths). GitHub
    matches annotations against checkout-relative paths, so strip the root
    when we can and never raise when we can't.
    """
    p = Path(path)
    if root is not None and p.is_absolute():
        try:
            return p.relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            pass
    return p.as_posix()


def _location(uri: str, line: int) -> dict[str, Any]:
    # Plain relative URIs — GitHub resolves them against the checkout root.
    # A uriBaseId reference without a matching run.originalUriBaseIds entry
    # is a SARIF 2.1.0 conformance gap, so we don't emit one.
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": uri},
            "region": {"startLine": max(1, int(line or 1))},
        }
    }


def _sarif_doc(
    rules: list[dict[str, Any]], results: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "django-orm-lens",
                        "informationUri": _INFO_URI,
                        "version": __version__,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def _nplusone_message(f: NPlusOneFinding) -> str:
    return (
        f"Possible N+1: loop over '{f.queryset_var}' accesses "
        f"{', '.join(f.accessed)} per iteration. Fix: {f.suggested_fix}"
    )


def nplusone_sarif(findings: Iterable[NPlusOneFinding]) -> dict[str, Any]:
    """SARIF 2.1.0 document for ``django-orm-lens nplusone`` findings."""
    rule = {
        "id": "nplusone",
        "name": "NPlusOneQuery",
        "shortDescription": {
            "text": (
                "Related-object access inside a loop without "
                "select_related/prefetch_related"
            )
        },
        "helpUri": f"{_RULES_DOCS}/nplusone.md",
        "defaultConfiguration": {"level": "warning"},
    }
    results = [
        {
            "ruleId": "nplusone",
            "level": _CONFIDENCE_LEVEL.get(f.confidence, "note"),
            "message": {"text": _nplusone_message(f)},
            "locations": [_location(f.file, f.line)],
            "properties": {
                "confidence": f.confidence,
                "loopVar": f.loop_var,
                "querysetVar": f.queryset_var,
            },
        }
        for f in findings
    ]
    return _sarif_doc([rule], results)


def migration_risks_sarif(
    findings: Iterable[MigrationRisk], root: str | None = None
) -> dict[str, Any]:
    """SARIF 2.1.0 document for ``django-orm-lens migration-risk`` findings."""
    findings = list(findings)
    rules: list[dict[str, Any]] = []
    seen: set = set()
    for f in findings:
        if f.rule in seen:
            continue
        seen.add(f.rule)
        rules.append(
            {
                "id": f.rule,
                "name": "".join(w.capitalize() for w in f.rule.split("_")),
                "shortDescription": {"text": f.rule.replace("_", " ")},
                "helpUri": f"{_RULES_DOCS}/migrations.md#{f.rule}",
                "defaultConfiguration": {
                    "level": _SEVERITY_LEVEL.get(f.severity, "warning")
                },
            }
        )
    results = [
        {
            "ruleId": f.rule,
            "level": _SEVERITY_LEVEL.get(f.severity, "warning"),
            "message": {"text": f"{f.description} Mitigation: {f.mitigation}"},
            "locations": [
                _location(_rel_posix(root, f.file_path), f.line_number)
            ],
            "properties": {
                "app": f.app,
                "migration": f.migration,
                "operation": f.operation,
                "confidence": f.confidence,
            },
        }
        for f in findings
    ]
    return _sarif_doc(rules, results)


def _esc_data(s: str) -> str:
    """Escape a workflow-command message per GitHub's escaping rules."""
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _esc_prop(s: str) -> str:
    """Escape a workflow-command property (file=, title=) value."""
    return _esc_data(s).replace(":", "%3A").replace(",", "%2C")


def nplusone_github(findings: Iterable[NPlusOneFinding]) -> str:
    """GitHub Actions ``::warning``/``::notice`` lines, one per finding."""
    lines = []
    for f in findings:
        cmd = _CONFIDENCE_CMD.get(f.confidence, "notice")
        lines.append(
            f"::{cmd} file={_esc_prop(f.file)},line={f.line},"
            f"title={_esc_prop('django-orm-lens: N+1 query')}"
            f"::{_esc_data(_nplusone_message(f))}"
        )
    return "\n".join(lines)


def migration_risks_github(
    findings: Iterable[MigrationRisk], root: str | None = None
) -> str:
    """GitHub Actions annotation lines for migration risks."""
    lines = []
    for f in findings:
        cmd = _SEVERITY_CMD.get(f.severity, "warning")
        path = _rel_posix(root, f.file_path)
        msg = f"{f.description} Mitigation: {f.mitigation}"
        lines.append(
            f"::{cmd} file={_esc_prop(path)},line={f.line_number},"
            f"title={_esc_prop('django-orm-lens: ' + f.rule)}"
            f"::{_esc_data(msg)}"
        )
    return "\n".join(lines)


def blast_radius_github(report: Any, root: str | None = None) -> str:
    """GitHub Actions annotations for a blast-radius report.

    Annotates the migration line itself — that is the line a reviewer can act
    on — and folds the reference count into the message so the consequence is
    visible without opening a second tab. ``certain`` references against a
    destructive operation are the signal worth interrupting for, so they are
    named in the annotation title too.

    ``report`` is typed ``Any`` to keep this module free of an import cycle:
    :mod:`.blast_radius` imports these emitters, never the other way round.
    """
    lines = []
    for target in report.targets:
        certain = target.impact_counts()["certain"]
        for r in target.risks:
            cmd = _SEVERITY_CMD.get(r.severity, "warning")
            path = _rel_posix(root, r.file_path)
            msg = f"{r.description} Mitigation: {r.mitigation}"
            title = f"django-orm-lens: {r.rule}"
            if certain:
                msg = (
                    f"{msg} Blast radius: {certain} certain reference(s) to "
                    f"{target.label} still in the codebase."
                )
                title = f"{title} ({certain} certain reference(s))"
            lines.append(
                f"::{cmd} file={_esc_prop(path)},line={r.line_number},"
                f"title={_esc_prop(title)}::{_esc_data(msg)}"
            )
    for r in report.unscanned_risks:
        cmd = _SEVERITY_CMD.get(r.severity, "warning")
        path = _rel_posix(root, r.file_path)
        msg = f"{r.description} Mitigation: {r.mitigation}"
        lines.append(
            f"::{cmd} file={_esc_prop(path)},line={r.line_number},"
            f"title={_esc_prop('django-orm-lens: ' + r.rule)}::{_esc_data(msg)}"
        )
    return "\n".join(lines)
