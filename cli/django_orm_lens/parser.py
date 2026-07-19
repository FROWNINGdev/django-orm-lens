"""Django models.py parser — Python port of the VS Code extension parser.

Static regex-based parser. Zero third-party deps. Produces a structurally
compatible schema with the TypeScript ``src/parser.ts`` (fields, relations,
Meta) — the cross-language golden fixture under ``test/`` pins the shared
shape. Note: indent detection on the Python side expands tabs to width 4
and clamps to 32 (ReDoS mitigation); the TypeScript side reports raw
character width. Both agree on the common 4-space case.

Key semantics preserved from the TS parser:
* multi-line ``class X(A, B):`` inheritance;
* non-model class filter (``ModelAdmin`` / ``ModelForm`` / ``Serializer`` etc.);
* per-class indent width detection (2/4/tab all work);
* both ``models.CharField(...)`` and bare ``CharField(...)`` imports;
* balanced-paren reader for multi-line field arg blocks;
* first-arg extraction for FK/O2O/M2M ``related_model``;
* ``class Meta:`` attribute capture.
"""

from __future__ import annotations

import os
import re
import sys
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from .models import (
    ParsedApp,
    ParsedField,
    ParsedModel,
    WorkspaceIndex,
)

RELATION_TYPES: Tuple[str, ...] = ("ForeignKey", "ManyToManyField", "OneToOneField")

CLASS_RE = re.compile(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*:")
CLASS_START_RE = re.compile(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")

NON_MODEL_TAIL = re.compile(
    r"^(ModelAdmin|ModelForm|ModelSerializer|ModelChoiceField|"
    r"ModelMultipleChoiceField|Serializer|Form|Admin|View|ViewSet|"
    r"Manager|QuerySet|Config|AppConfig|Response|Handler|Middleware|"
    r"Backend|Command)$"
)

BARE_FIELD_TYPES = "|".join(
    [
        "CharField", "TextField", "SlugField", "EmailField", "URLField", "UUIDField",
        "IntegerField", "BigIntegerField", "SmallIntegerField",
        "PositiveIntegerField", "PositiveSmallIntegerField", "PositiveBigIntegerField",
        "FloatField", "DecimalField",
        "BooleanField", "NullBooleanField",
        "DateTimeField", "DateField", "TimeField", "DurationField",
        "JSONField", "BinaryField",
        "FileField", "ImageField", "FilePathField",
        "GenericIPAddressField",
        "AutoField", "BigAutoField", "SmallAutoField",
        "ForeignKey", "OneToOneField", "ManyToManyField",
    ]
)


def _read_multiline_class(lines: Sequence[str], start: int):
    """Read a possibly-multi-line ``class Foo(Bar,\n    Baz):`` header.

    Returns ``(match, end_line_idx)`` on success, ``(None, end_line_idx)``
    when the parens closed but the joined buffer did not match a class
    signature, and ``(None, start)`` when the wrap never closes (truncated
    or malformed file). Always a tuple.

    Advance semantics for the caller:
    * closed-but-no-match: use ``end_line_idx`` to skip past the whole
      wrapped section without re-scanning each continuation line;
    * never-closes: advance one line past ``start`` so the outer loop
      keeps making progress on the rest of the file instead of jumping
      to EOF (which used to drop any valid models below the malformed
      header).
    """
    buffer = lines[start]
    depth = 0
    saw_open = False
    for i in range(start, len(lines)):
        src = lines[i] if i == start else lines[i].lstrip()
        for ch in src:
            if ch == "(":
                depth += 1
                saw_open = True
            elif ch == ")":
                depth -= 1
        if i > start:
            buffer += " " + src
        if saw_open and depth == 0:
            m = CLASS_RE.match(buffer)
            if m:
                return m, i
            return None, i
    return None, start


def _detect_class_indent(lines: Sequence[str], class_line_idx: int) -> int:
    end = min(class_line_idx + 30, len(lines))
    for i in range(class_line_idx + 1, end):
        m = re.match(r"^([\t ]+)\S", lines[i])
        if m:
            raw = m.group(1)
            width = sum(4 if ch == "\t" else 1 for ch in raw)
            return min(width, 32)
    return 4


_BODY_REGEX_CACHE: dict = {}


def _build_body_regexes(indent: int):
    cached = _BODY_REGEX_CACHE.get(indent)
    if cached is not None:
        return cached
    w = r"\s{" + str(indent) + r"}"
    w2 = r"\s{" + str(indent * 2) + r"}"
    result = {
        "FIELD_RE": re.compile(
            rf"^{w}([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*models\.([A-Za-z_][A-Za-z0-9_]*)\s*\("
        ),
        "BARE_FIELD_RE": re.compile(
            rf"^{w}([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*({BARE_FIELD_TYPES})\s*\("
        ),
        "META_START_RE": re.compile(rf"^{w}class\s+Meta\s*(?:\([^)]*\))?\s*:"),
        "META_ITEM_RE": re.compile(
            rf"^{w2}([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+?)\s*(#.*)?$"
        ),
        "META_BODY_RE": re.compile(r"^\s{" + str(indent * 2) + r",}"),
    }
    _BODY_REGEX_CACHE[indent] = result
    return result


def _extract_related(args_block: str):
    stripped = args_block.strip()
    m = re.match(
        r"^(?:to\s*=\s*)?(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_.]*))",
        stripped,
    )
    if not m:
        return None
    raw = m.group(1) or m.group(2) or m.group(3)
    if not raw:
        return None
    if raw == "self":
        return "self"
    return raw.strip("'\"")


def _extract_on_delete(args_block: str):
    m = re.search(r"on_delete\s*=\s*(?:models\.)?([A-Z][A-Z_]+)", args_block)
    if m:
        return m.group(1)
    if re.search(r"on_delete\s*=\s*(?:models\.)?SET\s*\(", args_block):
        return "SET"
    return None


def _extract_related_name(args_block: str):
    m = re.search(r"related_name\s*=\s*(?:'([^']+)'|\"([^\"]+)\")", args_block)
    if not m:
        return None
    return m.group(1) or m.group(2)


def _extract_through_model(args_block: str):
    m = re.search(
        r"\bthrough\s*=\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_.]*))",
        args_block,
    )
    if not m:
        return None
    return m.group(1) or m.group(2) or m.group(3)


def _read_balanced_args(lines: Sequence[str], start: int):
    if "(" not in lines[start]:
        return "", start
    open_idx = lines[start].index("(")
    depth = 0
    parts: List[str] = []
    for i in range(start, len(lines)):
        src = lines[i][open_idx:] if i == start else lines[i]
        for ch in src:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    parts.append(")")
                    return "".join(parts).lstrip("("), i
            parts.append(ch)
        parts.append("\n")
    return "".join(parts).lstrip("("), len(lines) - 1


def _looks_like_model(base_classes: List[str]) -> bool:
    for b in base_classes:
        tail = b.split(".")[-1]
        if NON_MODEL_TAIL.match(tail):
            return False
        if re.search(r"models\.Model$", b):
            return True
        if re.match(
            r"^(Model|AbstractModel|AbstractBaseModel|TimeStampedModel|PolymorphicModel)$",
            tail,
        ):
            return True
        if re.match(r"^Abstract[A-Z]", tail):
            return True
        if re.search(r"Mixin$", tail):
            return True
    return False


def parse_models_file(file_path: str, content: str) -> List[ParsedModel]:
    """Parse a single models.py-style file. Returns 0..N Django model classes.

    Two-pass: (1) collect every class def with base classes + Meta,
    (2) resolve transitive inheritance via fixed-point so ``Profile(TimeStamped)``
    where ``TimeStamped(models.Model)`` sits in the same file is correctly
    identified as a model. Classes with ``Meta.abstract = True`` are dropped.

    Resolution here is scoped to this single file's definitions. Use
    ``scan_workspace`` when bases may live in another parsed module (a
    shared abstract base imported from elsewhere in the project) — it
    collects definitions across every file first and resolves the union
    once, so a base defined outside this file is still found.
    """
    return _resolve_and_filter(_collect_defs(file_path, content))


def _collect_defs(file_path: str, content: str) -> List[ParsedModel]:
    """Pass 1 only: collect every class def (name, bases, fields, Meta).

    No transitive resolution or abstract filtering — callers combine the
    result with definitions from other files before calling
    ``_resolve_and_filter``.
    """
    lines = content.splitlines()
    all_defs: List[ParsedModel] = []
    parent = os.path.basename(os.path.dirname(file_path))
    if parent == "models":
        app_name = os.path.basename(os.path.dirname(os.path.dirname(file_path)))
    else:
        app_name = parent or "app"

    i = 0
    while i < len(lines):
        line = lines[i]
        class_match = CLASS_RE.match(line)
        class_header_end = i
        if not class_match and CLASS_START_RE.match(line):
            joined_match, joined_end = _read_multiline_class(lines, i)
            if joined_match is not None:
                class_match = joined_match
                class_header_end = joined_end
            else:
                i = joined_end + 1
                continue
        if not class_match:
            i += 1
            continue

        model_name = class_match.group(1)
        base_classes = [
            s.strip() for s in class_match.group(2).split(",") if s.strip()
        ]
        # Drop classes whose ALL bases are known non-model tails
        # (ModelAdmin, Serializer, Manager, etc.) — they can't participate
        # in a model inheritance chain.
        if base_classes and all(
            NON_MODEL_TAIL.match(b.split(".")[-1]) for b in base_classes
        ):
            i += 1
            continue

        model = ParsedModel(
            name=model_name,
            app_name=app_name,
            file_path=file_path,
            line_number=i,
            base_classes=base_classes,
        )

        indent = _detect_class_indent(lines, class_header_end)
        rx = _build_body_regexes(indent)

        j = class_header_end + 1
        while j < len(lines):
            inner = lines[j]
            if re.match(r"^class\s+", inner) and not re.match(r"^\s+class", inner):
                break
            if not inner.strip():
                j += 1
                continue

            if rx["META_START_RE"].match(inner):
                k = j + 1
                while k < len(lines):
                    ml = lines[k]
                    if ml and not rx["META_BODY_RE"].match(ml) and ml.strip():
                        break
                    m2 = rx["META_ITEM_RE"].match(ml)
                    if m2:
                        model.meta[m2.group(1)] = m2.group(2).strip()
                    k += 1
                j = k
                continue

            fm = rx["FIELD_RE"].match(inner) or rx["BARE_FIELD_RE"].match(inner)
            if fm:
                fname, ftype = fm.group(1), fm.group(2)
                args_block, end_idx = _read_balanced_args(lines, j)
                is_rel = ftype in RELATION_TYPES
                field = ParsedField(
                    name=fname,
                    type=ftype,
                    args=args_block.rstrip(")").strip(),
                    is_relation=is_rel,
                    line_number=j,
                )
                if is_rel:
                    field.relation_kind = ftype  # type: ignore[assignment]
                    inner = args_block.rstrip(")")
                    field.related_model = _extract_related(inner)
                    field.on_delete = _extract_on_delete(inner)
                    field.related_name = _extract_related_name(inner)
                    if ftype == "ManyToManyField":
                        field.through_model = _extract_through_model(inner)
                model.fields.append(field)
                j = end_idx + 1
                continue

            j += 1

        all_defs.append(model)
        i = j

    return all_defs


def _resolve_and_filter(all_defs: List[ParsedModel]) -> List[ParsedModel]:
    """Pass 2: transitive model resolution + abstract drop over ``all_defs``.

    ``all_defs`` may come from a single file (``parse_models_file``) or the
    union of every file in a scan (``scan_workspace``) — resolution matches
    each base's tail name against whatever definitions are present, so a
    base class defined in another file is found when the union is passed.
    """
    is_model_name = {m.name for m in all_defs if _looks_like_model(m.base_classes)}
    changed = True
    while changed:
        changed = False
        for m in all_defs:
            if m.name in is_model_name:
                continue
            for b in m.base_classes:
                tail = b.split(".")[-1]
                if tail in is_model_name:
                    is_model_name.add(m.name)
                    changed = True
                    break

    result: List[ParsedModel] = []
    for m in all_defs:
        if m.name not in is_model_name:
            continue
        abstract_val = m.meta.get("abstract", "").strip()
        if abstract_val in ("True", "1", "true"):
            continue
        result.append(m)
    return result


def _iter_python_files(root: Path, excludes: Sequence[str]) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name == "models.py" or (
                os.path.basename(dirpath) == "models"
                and name.endswith(".py")
                and name != "__init__.py"
            ):
                full = Path(dirpath) / name
                rel_posix = full.relative_to(root).as_posix()
                if any(fnmatch(rel_posix, pat) for pat in excludes):
                    continue
                yield full


def _app_dir_for(fs_path: str) -> Tuple[str, str]:
    parent = os.path.dirname(fs_path)
    parent_name = os.path.basename(parent)
    if parent_name == "models":
        grand = os.path.dirname(parent)
        return grand, os.path.basename(grand)
    return parent, parent_name


DEFAULT_EXCLUDES = (
    "**/migrations/**",
    "**/node_modules/**",
    "**/venv/**",
    "**/.venv/**",
    "**/env/**",
)


def scan_workspace(
    root: str, exclude_globs: Sequence[str] = DEFAULT_EXCLUDES
) -> WorkspaceIndex:
    """Walk ``root``, parse every ``models.py`` (or ``models/*.py``), return an index.

    Collects class definitions from every file first, then resolves
    transitive model inheritance once over that union — so a model whose
    base class is defined in a *different* scanned file (e.g. a shared
    abstract base in ``common/models.py``) is still recognized, instead of
    only bases found within the same file (see issue #20).
    """
    root_path = Path(root).resolve()
    all_defs: List[ParsedModel] = []
    for py in _iter_python_files(root_path, exclude_globs):
        try:
            content = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            all_defs.extend(_collect_defs(str(py), content))
        except Exception as exc:
            print(
                f"warning: skipping {py}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            continue

    apps: dict = {}
    for model in _resolve_and_filter(all_defs):
        app_dir, app_name = _app_dir_for(model.file_path)
        app = apps.get(app_dir)
        if app is None:
            app = ParsedApp(name=app_name, path=app_dir)
            apps[app_dir] = app
        app.models.append(model)

    sorted_apps = sorted(apps.values(), key=lambda a: a.name)
    return WorkspaceIndex(apps=sorted_apps, scanned_at=int(time.time() * 1000))
