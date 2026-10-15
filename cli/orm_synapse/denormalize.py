"""Denormalization smells.

Review hints, not a proof that a table violates 2NF or 3NF. A functional
dependency is a business fact and is not written in the model source, so this
module never claims a normal form. It also stays quiet about
``company_id = IntegerField()``: a scalar id with no ``ForeignKey`` is a
common convention, not evidence that a column was copied.

Three smells, all on columns the model declares:

* ``DOL018`` — a text or JSON column whose name ends in ``_ids``
* ``DOL019`` — three or more columns ``stem_1``, ``stem_2``, ``stem_3``
* ``DOL020`` — a scalar ``customer_name`` beside a ``customer`` foreign key,
  for a small set of descriptive suffixes

Mirrors ``src/rules/denormalize.ts``. The two must stay in step.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .models import ParsedField, ParsedModel

COPIED_SUFFIXES = frozenset(
    {"name", "title", "email", "slug", "code", "label", "phone", "address"}
)
_REPEATED = re.compile(r"^([A-Za-z][A-Za-z0-9]*)_(\d+)$")
_DISABLE_NEXT = re.compile(
    r"#\s*orm-synapse-disable-next-line(?:\s+([A-Z0-9,\s]+))?", re.IGNORECASE
)
_DISABLE_LINE = re.compile(
    r"#\s*orm-synapse-disable-line(?:\s+([A-Z0-9,\s]+))?", re.IGNORECASE
)
_DISABLE_FILE = re.compile(
    r"#\s*orm-synapse-disable(?:\s+([A-Z0-9,\s]+))?", re.IGNORECASE
)


@dataclass(frozen=True)
class DenormFinding:
    code: str
    file_path: str
    line_number: int
    """0-based, matching the parser. GitHub annotations add one."""
    model: str
    field: str
    message: str
    lines: tuple[int, ...] = ()
    """0-based lines that make this smell. A pull request keeps the smell when it adds one of them, or the whole model."""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "filePath": self.file_path,
            "lineNumber": self.line_number,
            "model": self.model,
            "field": self.field,
            "message": self.message,
        }


def _is_proxy(model: ParsedModel) -> bool:
    return model.meta.get("proxy", "").strip().rstrip(",") in ("True", "1", "true")


def _textish(type_name: str) -> bool:
    return type_name.endswith(("CharField", "TextField", "JSONField"))


def _relations(model: ParsedModel) -> list[ParsedField]:
    return [
        field
        for field in model.all_fields()
        if field.is_relation and field.relation_kind in ("ForeignKey", "OneToOneField")
    ]


def _id_list(model: ParsedModel, field: ParsedField) -> DenormFinding | None:
    if field.is_relation or not field.name.endswith("_ids") or not _textish(field.type):
        return None
    return DenormFinding(
        code="DOL018",
        file_path=model.file_path,
        line_number=field.line_number,
        model=model.name,
        field=field.name,
        message=(
            f"{field.name} stores several ids in one {field.type}. "
            "A child row per id stays indexable. This is a review hint, "
            "not a proof the column is wrong."
        ),
        lines=(field.line_number,),
    )


def _repeated(model: ParsedModel, declared: list[ParsedField]) -> list[DenormFinding]:
    groups: dict[str, list[ParsedField]] = {}
    for field in declared:
        match = _REPEATED.match(field.name)
        if not match or len(match.group(1)) < 2:
            continue
        groups.setdefault(match.group(1), []).append(field)
    out: list[DenormFinding] = []
    for stem, fields in groups.items():
        numbers = {int(_REPEATED.match(field.name).group(2)) for field in fields}  # type: ignore[union-attr]
        if len(numbers) < 3:
            continue
        first = min(fields, key=lambda field: (field.line_number, field.name))
        names = ", ".join(field.name for field in sorted(fields, key=lambda field: field.name))
        out.append(
            DenormFinding(
                code="DOL019",
                file_path=model.file_path,
                line_number=first.line_number,
                model=model.name,
                field=first.name,
                message=(
                    f"{names} repeat `{stem}`. A child table is the normalized form. "
                    "Keep the columns when the group is a fixed set of values."
                ),
                lines=tuple(field.line_number for field in fields),
            )
        )
    return out


def _copied(model: ParsedModel, declared: list[ParsedField]) -> list[DenormFinding]:
    relations = {field.name: field for field in _relations(model)}
    declared_names = {field.name for field in declared}
    out: list[DenormFinding] = []
    for field in declared:
        if field.is_relation or field.name not in declared_names:
            continue
        for relation, suffix in (
            (name, field.name[len(name) + 1 :])
            for name in relations
            if field.name.startswith(name + "_")
        ):
            if suffix not in COPIED_SUFFIXES:
                continue
            out.append(
                DenormFinding(
                    code="DOL020",
                    file_path=model.file_path,
                    line_number=field.line_number,
                    model=model.name,
                    field=field.name,
                    message=(
                        f"{field.name} copies {relation} onto this table ({suffix}). "
                        "Keep it when it is a snapshot or a cache; otherwise it belongs "
                        f"on {relation}."
                    ),
                    lines=(field.line_number,),
                )
            )
            break
    return out


def _anchor(model: ParsedModel, field: ParsedField) -> tuple[str, int]:
    """Point a finding at the line that actually declares the field.

    An inherited column's line number belongs to the abstract base. When that
    base lives in this file the number is already right; otherwise the finding
    sits on the concrete class, which is the table the column lands on.
    """
    path = model.file_path
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return path, model.line_number
    line = field.line_number
    if 0 <= line < len(lines) and re.search(rf"\b{re.escape(field.name)}\b", lines[line]):
        return path, line
    return path, model.line_number


def analyze_models(models: list[ParsedModel]) -> list[DenormFinding]:
    """Smells on concrete tables. Proxy models are skipped; they have no table."""
    found: list[DenormFinding] = []
    seen: set[tuple[str, ...]] = set()
    for model in models:
        if _is_proxy(model):
            continue
        owned = [field for field in model.fields if not field.inherited_from]
        inherited = [field for field in model.inherited_fields if field.inherited_from]
        candidates = [*_repeated(model, owned), *_copied(model, owned)]
        for field in [*owned, *inherited]:
            smell = _id_list(model, field)
            if smell is not None:
                candidates.append(smell)
        for smell in candidates:
            origin = next(
                (
                    field.inherited_from
                    for field in inherited
                    if field.name == smell.field and field.inherited_from
                ),
                "",
            )
            path, line = _anchor(
                model,
                ParsedField(
                    name=smell.field,
                    type="",
                    args="",
                    is_relation=False,
                    line_number=smell.line_number,
                ),
            )
            smell = DenormFinding(
                smell.code,
                path,
                line,
                smell.model,
                smell.field,
                smell.message,
                lines=tuple(dict.fromkeys((*smell.lines, line))),
            )
            # An inherited id list is one column, even when several children copy it.
            key: tuple[str, ...] = (
                (smell.code, smell.field, origin)
                if origin and smell.code == "DOL018"
                else (smell.code, smell.file_path, str(smell.line_number), smell.field)
            )
            if key in seen:
                continue
            seen.add(key)
            found.append(smell)
    found.sort(key=lambda item: (item.file_path, item.line_number, item.code, item.field))
    return _drop_suppressed(found)


def _parse_codes(raw: str | None) -> set[str]:
    if not raw or not raw.strip():
        return {"*"}
    return {part.strip().upper() for part in re.split(r"[\s,]+", raw) if part.strip()} or {"*"}


def _suppressed(lines: list[str], line: int, code: str) -> bool:
    file_wide: set[str] = set()
    per_line: dict[int, set[str]] = {}
    for index, text in enumerate(lines):
        match = _DISABLE_NEXT.search(text)
        if match:
            per_line.setdefault(index + 1, set()).update(_parse_codes(match.group(1)))
            continue
        match = _DISABLE_LINE.search(text)
        if match:
            per_line.setdefault(index, set()).update(_parse_codes(match.group(1)))
            continue
        if text.strip().startswith("#"):
            match = _DISABLE_FILE.search(text)
            if match:
                codes = _parse_codes(match.group(1))
                if "*" in codes:
                    return True
                file_wide.update(codes)
    if code in file_wide:
        return True
    codes = per_line.get(line, set())
    return "*" in codes or code in codes


def _drop_suppressed(findings: list[DenormFinding]) -> list[DenormFinding]:
    cache: dict[str, list[str]] = {}
    kept: list[DenormFinding] = []
    for finding in findings:
        if finding.file_path not in cache:
            try:
                cache[finding.file_path] = Path(finding.file_path).read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except OSError:
                cache[finding.file_path] = []
        if not _suppressed(cache[finding.file_path], finding.line_number, finding.code):
            kept.append(finding)
    return kept


def parse_unified_diff(diff: str) -> dict[str, set[int]]:
    """Added line numbers, 0-based, keyed by the path in the new file.

    Accepts a git unified diff. A GitHub pull-request ``patch`` needs a
    ``+++ b/<path>`` header in front of its hunks; the Action adds that.
    """
    added: dict[str, set[int]] = {}
    current: str | None = None
    new_line = 0
    expect_plus = False
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            current = None
            expect_plus = False
            continue
        if raw.startswith("--- "):
            expect_plus = True
            continue
        if expect_plus and raw.startswith("+++ "):
            expect_plus = False
            name = raw[4:].strip()
            if name == "/dev/null":
                current = None
                continue
            if name.startswith("b/"):
                name = name[2:]
            current = name.replace("\\", "/")
            added.setdefault(current, set())
            continue
        if raw.startswith("@@"):
            expect_plus = False
            match = re.search(r"\+(\d+)", raw)
            new_line = int(match.group(1)) if match else 1
            continue
        if current is None or raw.startswith("\\"):
            continue
        if raw.startswith("+"):
            added[current].add(new_line - 1)
            new_line += 1
        elif raw.startswith("-"):
            continue
        else:
            new_line += 1
    return added


def _relative(path: str, root: str) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix().replace("\\", "/")


def limit_to_changes(
    findings: list[DenormFinding],
    models: list[ParsedModel],
    added: dict[str, set[int]],
    root: str,
) -> list[DenormFinding]:
    """Keep smells on a new table, or on a column this diff adds.

    A new table is a model whose ``class`` line is added. Every smell on that
    table is in scope, including a column inherited from an abstract base.
    A new column is an added field line. An existing column is left alone.
    """
    new_models: set[tuple[str, str]] = set()
    for model in models:
        rel = _relative(model.file_path, root)
        if model.line_number in added.get(rel, ()):
            new_models.add((rel, model.name))
    kept: list[DenormFinding] = []
    for finding in findings:
        rel = _relative(finding.file_path, root)
        if (rel, finding.model) in new_models:
            kept.append(finding)
            continue
        if any(line in added.get(rel, ()) for line in finding.lines):
            kept.append(finding)
    return kept


def format_text(findings: list[DenormFinding]) -> str:
    if not findings:
        return "No denormalization smells.\n"
    lines = [
        f"{item.file_path}:{item.line_number + 1} {item.code} {item.model}.{item.field} — {item.message}"
        for item in findings
    ]
    return "\n".join(lines) + "\n"


def format_github(findings: list[DenormFinding], root: str | None = None) -> str:
    """``::warning`` annotations. Never ``::error`` — this check does not fail a build."""
    lines = []
    for item in findings:
        path = item.file_path
        if root:
            try:
                path = Path(item.file_path).resolve().relative_to(Path(root).resolve()).as_posix()
            except ValueError:
                path = item.file_path
        message = item.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        prop = path.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A").replace(":", "%3A").replace(",", "%2C")
        title = f"orm-synapse: {item.code}".replace("%", "%25").replace(":", "%3A").replace(",", "%2C")
        lines.append(
            f"::warning file={prop},line={item.line_number + 1},title={title}::{message}"
        )
    return "\n".join(lines)


def write_step_summary(findings: list[DenormFinding], *, limited: bool = False) -> None:
    """Append a markdown report when running inside GitHub Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    if not findings:
        note = (
            "No new tables or columns to review."
            if limited
            else "No smells. This check does not prove 2NF or 3NF, and it does not fail the build."
        )
        body = f"## Denormalization review\n\n{note}\n"
    else:
        rows = "\n".join(
            f"| `{item.code}` | `{item.model}.{item.field}` | {item.message} |"
            for item in findings
        )
        body = (
            "## Denormalization review\n\n"
            "Smells for review. Not a 2NF/3NF proof, and not a failing check.\n\n"
            "| Code | Column | Note |\n|---|---|---|\n"
            f"{rows}\n"
        )
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(body)
