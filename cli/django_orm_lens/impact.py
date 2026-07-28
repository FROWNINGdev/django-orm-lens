"""Impact analysis — "what breaks if I remove this field or model?"

Python port of :mod:`src/impactAnalysis.ts`, which until now shipped only in
the VS Code extension. The CLI, the MCP server and CI had no way to answer the
question, so the same analysis is lifted here with the editor-specific parts
(``vscode.workspace.findFiles``, cancellation tokens) replaced by a plain
``os.walk``.

The classifier is a deliberate copy of the TypeScript one — same regexes, same
confidence tiers, same layer order — so the extension and the CLI cannot drift
into disagreeing about the same file. When one side changes, change both.

Design, unchanged from the original:

* Cheap literal candidate pass, then a precise classification pass.
* Per-framework layer buckets, confidence tag on every finding. A tool that
  admits uncertainty gets trusted; one that hides it does not.
* No type inference. That is Pyright's job and it already loses on Django's
  string-typed FK / ``related_name`` / template surface. We accept a
  ``possibly`` tier so the noise is visible rather than silently dropped.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .parser import BROAD_SKIP_DIRS

# Django layer names, in the order they are reported. Mirrors LAYER_ORDER in
# src/impactAnalysis.ts — models first because that is where the definition
# lives and where a reviewer looks first.
LAYER_ORDER: tuple[str, ...] = (
    "models",
    "serializers",
    "forms",
    "admin",
    "views",
    "urls",
    "templates",
    "tests",
    "migrations",
    "other",
)

CONFIDENCE_ORDER: tuple[str, ...] = ("certain", "likely", "possibly")

_LAYER_RANK = {name: i for i, name in enumerate(LAYER_ORDER)}
_CONFIDENCE_RANK = {name: i for i, name in enumerate(CONFIDENCE_ORDER)}

# Files worth opening at all. Templates are the only non-Python surface that
# references model fields by name.
_SCANNED_SUFFIXES = (".py", ".html")

# `migrations` sits in BROAD_SKIP_DIRS because every other analyzer wants it
# gone. Impact analysis explicitly wants it: a migration that still writes to
# a column you are dropping is exactly the finding a reviewer needs.
_SKIP_DIRS = BROAD_SKIP_DIRS - {"migrations"}


@dataclass(frozen=True)
class ImpactFinding:
    """One reference to the searched name, with a confidence tier."""

    layer: str
    confidence: str
    file_path: str
    line: int
    """Zero-based, matching the TypeScript implementation and the LSP."""
    column: int
    """Zero-based column of the match start."""
    snippet: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "confidence": self.confidence,
            "filePath": self.file_path,
            "line": self.line,
            "column": self.column,
            "snippet": self.snippet,
            "reason": self.reason,
        }


def detect_layer(file_path: str) -> str:
    """Classify a file into a Django layer from its path alone.

    Cheap — runs once per candidate file, before any content is read.
    """
    p = file_path.replace("\\", "/").lower()
    if re.search(r"/templates/.+\.html$", p) or re.search(r"/jinja2/.+\.html$", p):
        return "templates"
    if re.search(r"/migrations/[^/]+\.py$", p):
        return "migrations"
    if (
        re.search(r"/tests?\.py$", p)
        or re.search(r"/tests?/", p)
        or re.search(r"/test_[^/]+\.py$", p)
    ):
        return "tests"
    if re.search(r"/models(\.py|/[^/]+\.py)$", p):
        return "models"
    if re.search(r"/serializers?(\.py|/[^/]+\.py)$", p) or re.search(
        r"/api/[^/]+\.py$", p
    ):
        return "serializers"
    if re.search(r"/forms?(\.py|/[^/]+\.py)$", p):
        return "forms"
    if re.search(r"/admin(\.py|/[^/]+\.py)$", p):
        return "admin"
    if re.search(r"/views?(\.py|/[^/]+\.py)$", p) or re.search(r"/viewsets?\.py$", p):
        return "views"
    if re.search(r"/urls?\.py$", p):
        return "urls"
    return "other"


def classify_line(layer: str, line: str, needle: str) -> tuple[str, str] | None:
    """Classify one line's reference to ``needle``.

    :returns: ``(confidence, reason)``, or ``None`` when the line is
        definitely noise — a comment or a docstring opener.
    """
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return None
    if stripped.startswith('"""') or stripped.startswith("'''"):
        return None

    escaped = re.escape(needle)
    # Word boundary at the START only. Django lookups like `author__id` read
    # `author` as a field reference even though `\b` does not sit between the
    # `r` and the `_`.
    if not re.search(rf"\b{escaped}\b|\b{escaped}__", line):
        return None

    # A) Quoted string inside an ORM call — order_by("-author"), only("author").
    quoted_in_orm = (
        r"\b(?:F|Q|order_by|values|values_list|only|defer|select_related"
        rf"|prefetch_related|filter|exclude|annotate)\s*\([^)]*['\"][^'\"]*\b{escaped}\b"
    )
    # B) Keyword-argument reference, including the `field__lookup=` traversal.
    kwarg_in_orm = (
        r"\b(?:filter|exclude|get|annotate|update|create|values|values_list|Q)"
        rf"\s*\([^)]*\b{escaped}(?:__\w+)?\s*="
    )
    # C) Meta-config tuples: fields = [...], list_display = (...), ordering, ...
    fields_tuple = (
        r"\b(?:fields|list_display|search_fields|readonly_fields|list_filter"
        r"|ordering|filterset_fields|autocomplete_fields|exclude)\s*=\s*"
        rf"[\[(][^\])]*['\"]{escaped}['\"]"
    )
    # D) Template variable — {{ obj.author }} or {% for x in author %}
    template_var = (
        rf"\{{\{{[^}}]*\.{escaped}\b[^}}]*\}}\}}|\{{%[^%]*\b{escaped}\b[^%]*%\}}"
    )
    # E) Attribute access — obj.author
    attr_access = rf"\.{escaped}(?:__\w+)?\b"

    if re.search(quoted_in_orm, line):
        return ("certain", "ORM string reference")
    if re.search(kwarg_in_orm, line):
        return ("certain", "ORM keyword-arg reference")
    if re.search(fields_tuple, line):
        return ("certain", "declared in fields/list_display/search_fields tuple")
    if layer == "templates" and re.search(template_var, line):
        return ("likely", "template variable")

    if re.search(attr_access, line):
        if layer == "other":
            return ("possibly", "attribute access, layer unclear")
        return ("likely", f"{layer} attribute access")

    return ("possibly", "bare identifier match")


def scan_file_text(
    file_path: str,
    text: str,
    needle: str,
    layer: str | None = None,
) -> list[ImpactFinding]:
    """Scan one file's contents. Pure — no I/O, so tests can call it directly.

    :param layer: pre-computed layer. Pass it when the caller knows the
        workspace root, so classification runs on the repo-relative path —
        see :func:`scan_impact`.
    """
    if layer is None:
        layer = detect_layer(file_path)
    escaped = re.escape(needle)
    detect = re.compile(rf"\b{escaped}\b|\b{escaped}__")
    start_at = re.compile(rf"\b{escaped}")
    out: list[ImpactFinding] = []
    for i, line in enumerate(text.splitlines()):
        if not detect.search(line):
            continue
        cls = classify_line(layer, line, needle)
        if cls is None:
            continue
        confidence, reason = cls
        m = start_at.search(line)
        out.append(
            ImpactFinding(
                layer=layer,
                confidence=confidence,
                file_path=file_path,
                line=i,
                column=m.start() if m else 0,
                snippet=line.strip()[:200],
                reason=reason,
            )
        )
    return out


def sort_key(f: ImpactFinding) -> tuple[int, int, str, int]:
    """Layer, then confidence, then path, then line — most relevant first."""
    return (
        _LAYER_RANK.get(f.layer, len(LAYER_ORDER)),
        _CONFIDENCE_RANK.get(f.confidence, len(CONFIDENCE_ORDER)),
        f.file_path,
        f.line,
    )


def _iter_candidate_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS
        ]
        for name in filenames:
            if name.endswith(_SCANNED_SUFFIXES):
                yield Path(dirpath) / name


def scan_impact(
    root: str | Path,
    needle: str,
    skip_files: Sequence[str] = (),
) -> list[ImpactFinding]:
    """Walk ``root`` and return every reference to ``needle``, sorted.

    :param skip_files: absolute paths to ignore — normally the definition site
        itself, so a field does not report its own declaration as impact.
    """
    root_path = Path(root).resolve()
    skip = {str(Path(p).resolve()) for p in skip_files}
    findings: list[ImpactFinding] = []
    for path in _iter_candidate_files(root_path):
        if str(path.resolve()) in skip:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Unreadable file — skip it rather than failing the whole scan.
            continue
        findings.extend(
            scan_file_text(str(path), text, needle, layer=layer_of(root_path, path))
        )
    findings.sort(key=sort_key)
    return findings


def layer_of(root: Path, path: Path) -> str:
    """Classify ``path`` using its location *inside the workspace*.

    Absolute paths are the wrong input for :func:`detect_layer`: a project
    checked out under ``~/tests/shop/`` or ``services/tests/api/`` would see
    every one of its files classified as ``tests``, because the layer regexes
    match anywhere in the string. Everything above the workspace root is the
    developer's directory layout, not the project's, so it is stripped first.
    """
    try:
        rel = path.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return detect_layer(str(path))
    # Leading slash so the anchored `/models.py`-style patterns still match a
    # file that sits directly at the workspace root.
    return detect_layer(f"/{rel}")


def group_by_layer(
    findings: Iterable[ImpactFinding],
) -> dict[str, list[ImpactFinding]]:
    """Bucket findings by layer, preserving :data:`LAYER_ORDER`."""
    grouped: dict[str, list[ImpactFinding]] = {}
    for f in findings:
        grouped.setdefault(f.layer, []).append(f)
    return {layer: grouped[layer] for layer in LAYER_ORDER if layer in grouped}
