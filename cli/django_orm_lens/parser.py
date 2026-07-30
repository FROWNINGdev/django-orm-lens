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

import ast
import os
import re
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import replace
from fnmatch import fnmatch
from pathlib import Path

from .models import (
    ParsedApp,
    ParsedField,
    ParsedModel,
    WorkspaceIndex,
)

RELATION_TYPES: tuple[str, ...] = ("ForeignKey", "ManyToManyField", "OneToOneField")

# ``(?:\s*\[[^\]]*\])?`` — optional PEP-695 generic type parameter list
# introduced in Python 3.12, e.g. ``class Container[T](models.Model):``.
# Only handles a single-line, non-nested bracket group — nested brackets in
# class-header generics are vanishingly rare and don't warrant a full
# bracket matcher.
CLASS_RE = re.compile(
    r"^class\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*\[[^\]]*\])?\s*\(([^)]*)\)\s*:"
)
CLASS_START_RE = re.compile(
    r"^class\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*\[[^\]]*\])?\s*\("
)

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
    # ``(?:\s*:[^=]+)?`` — optional PEP-526 type annotation between the field
    # name and ``=``, e.g. ``jti: CharField[str] = models.CharField(...)``.
    # ``[^=]+`` is safe because ``=`` never appears inside a type expression
    # (subscripts, unions, dotted refs, and generics all use other punctuation).
    ann = r"(?:\s*:[^=]+)?"
    # ``(?:[A-Za-z_][A-Za-z0-9_]*\.)?`` — optional single-identifier prefix on
    # the RHS. Covers:
    #   * aliased models module — ``from django.db import models as m; x = m.CharField(...)``
    #   * third-party field packages — ``x = jsonfield.JSONField(default=dict)``
    #   * standard bare imports — ``from django.db.models import CharField; x = CharField(...)``
    # Safe against false positives because the type name is still restricted
    # to Django's known field whitelist (BARE_FIELD_TYPES).
    prefix_opt = r"(?:[A-Za-z_][A-Za-z0-9_]*\.)?"
    result = {
        "FIELD_RE": re.compile(
            rf"^{w}([a-zA-Z_][a-zA-Z0-9_]*){ann}\s*=\s*models\.([A-Za-z_][A-Za-z0-9_]*)\s*\("
        ),
        "BARE_FIELD_RE": re.compile(
            rf"^{w}([a-zA-Z_][a-zA-Z0-9_]*){ann}\s*=\s*{prefix_opt}({BARE_FIELD_TYPES})\s*\("
        ),
        "META_START_RE": re.compile(rf"^{w}class\s+Meta\s*(?:\([^)]*\))?\s*:"),
        "META_ITEM_RE": re.compile(
            rf"^{w2}([a-zA-Z_][a-zA-Z0-9_]*){ann}\s*=\s*(.+?)\s*(#.*)?$"
        ),
        "META_BODY_RE": re.compile(r"^\s{" + str(indent * 2) + r",}"),
    }
    _BODY_REGEX_CACHE[indent] = result
    return result


def _dotted_name(node: ast.AST) -> str | None:
    """Best-effort textual dotted name of a Name/Attribute AST node.

    Returns e.g. ``"models.CASCADE"`` for ``ast.Attribute(value=Name("models"),
    attr="CASCADE")``. Returns ``None`` for anything else (Call, Constant,
    Subscript, ...).
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _parse_call_args(args_block: str) -> tuple[list[ast.expr] | None, dict[str, ast.expr] | None]:
    """Parse a Django field's raw arg text via ``ast.parse``.

    ``args_block`` is the content returned by :func:`_read_balanced_args` —
    the substring between the opening ``(`` (already stripped) and the
    balanced closing ``)`` (still trailing). Wraps as ``_(<content>)`` and
    parses as an expression to extract positional args and keywords in a
    kwarg-order-independent way.

    Returns ``(posargs, kwargs)`` on success or ``(None, None)`` on
    :class:`SyntaxError`, so callers can fall back to the legacy regex path.
    """
    s = args_block.strip()
    # _read_balanced_args returns content ending in exactly one balanced ")".
    # Some call sites (e.g. line 331 `inner = args_block.rstrip(")")`) strip
    # it. Normalise: drop up to two trailing ")" then re-close for parsing.
    stripped_paren = False
    while s.endswith(")") and not stripped_paren:
        s = s[:-1].rstrip()
        stripped_paren = True
    if not s:
        return [], {}
    try:
        tree = ast.parse(f"_({s})", mode="eval")
    except SyntaxError:
        return None, None
    call = tree.body
    if not isinstance(call, ast.Call):
        return None, None
    posargs = [a for a in call.args if not isinstance(a, ast.Starred)]
    kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}
    return posargs, kwargs


def _node_to_str(node: ast.AST) -> str | None:
    """String-constant or dotted-name value of ``node``, else ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return _dotted_name(node)


def _extract_related(args_block: str) -> str | None:
    """Model reference from a FK/O2O/M2M field call.

    Recognises both positional (``ForeignKey('User', ...)``) and keyword
    (``ForeignKey(on_delete=..., to='User')``) forms — kwarg order does not
    matter. ``settings.AUTH_USER_MODEL``-style dotted refs are preserved
    as-is; downstream :func:`resolve_related_tail` normalises them.
    """
    posargs, kwargs = _parse_call_args(args_block)
    if posargs is None or kwargs is None:
        return _extract_related_regex(args_block)
    val = kwargs.get("to")
    if val is None and posargs:
        val = posargs[0]
    if val is None:
        return None
    raw = _node_to_str(val)
    if not raw:
        return None
    if raw == "self":
        return "self"
    return raw


def _extract_on_delete(args_block: str) -> str | None:
    """``on_delete`` policy tail (``CASCADE`` / ``SET_NULL`` / ...).

    Handles bare identifiers, ``models.`` prefixed forms, and the callable
    ``SET(default)`` form — all return the last dotted segment.
    """
    posargs, kwargs = _parse_call_args(args_block)
    if posargs is None or kwargs is None:
        return _extract_on_delete_regex(args_block)
    od = kwargs.get("on_delete")
    if od is None:
        return None
    if isinstance(od, ast.Call):
        callee = _dotted_name(od.func)
        if callee:
            return callee.rsplit(".", 1)[-1]
        return None
    name = _dotted_name(od)
    if name:
        return name.rsplit(".", 1)[-1]
    return None


def _extract_related_name(args_block: str) -> str | None:
    posargs, kwargs = _parse_call_args(args_block)
    if posargs is None or kwargs is None:
        return _extract_related_name_regex(args_block)
    val = kwargs.get("related_name")
    if isinstance(val, ast.Constant) and isinstance(val.value, str):
        return val.value
    return None


def _extract_through_model(args_block: str) -> str | None:
    posargs, kwargs = _parse_call_args(args_block)
    if posargs is None or kwargs is None:
        return _extract_through_model_regex(args_block)
    val = kwargs.get("through")
    if val is None:
        return None
    return _node_to_str(val)


# ---------------------------------------------------------------------------
# Regex fallbacks — used when ast.parse rejects the args block (rare: comments
# mid-expression, unbalanced quotes in string literals, etc.). Kept behaviour-
# compatible with pre-AST versions.
# ---------------------------------------------------------------------------


def _extract_related_regex(args_block: str) -> str | None:
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


def _extract_on_delete_regex(args_block: str) -> str | None:
    m = re.search(r"on_delete\s*=\s*(?:models\.)?([A-Z][A-Z_]+)", args_block)
    if m:
        return m.group(1)
    if re.search(r"on_delete\s*=\s*(?:models\.)?SET\s*\(", args_block):
        return "SET"
    return None


def _extract_related_name_regex(args_block: str) -> str | None:
    m = re.search(r"related_name\s*=\s*(?:'([^']+)'|\"([^\"]+)\")", args_block)
    if not m:
        return None
    return m.group(1) or m.group(2)


def _extract_through_model_regex(args_block: str) -> str | None:
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
    parts: list[str] = []
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


def _encloses_only_blocks(lines: Sequence[str], idx: int, indent: int) -> bool:
    """Is the indented statement at ``lines[idx]`` still at module level?

    Django's swappable-model convention wraps concrete models in a plain
    ``if``::

        if not is_model_registered("catalogue", "ProductClass"):

            class ProductClass(AbstractProductClass):
                pass

    That class is a module-level model in every sense that matters, but it is
    indented, and matching ``^class`` alone missed it — 21 of django-oscar's
    22 app ``models.py`` files parsed to nothing, losing catalogue, order,
    partner, payment, voucher and the rest of the framework.

    Walking outwards, every enclosing header must be a block statement
    (``if`` / ``try`` / ``with`` / ``for`` …). A ``def`` or ``class`` means
    the class is a local or a nested helper — ``class Meta`` is the common
    one — and must stay excluded.
    """
    want = indent
    for k in range(idx - 1, -1, -1):
        line = lines[k]
        if not line.strip():
            continue
        cur = len(line) - len(line.lstrip())
        if cur >= want:
            continue
        if line.lstrip().startswith(("def ", "async def ", "class ")):
            return False
        want = cur
        if want == 0:
            return True
    return True


def _looks_like_model(base_classes: list[str]) -> bool:
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


def parse_models_file(file_path: str, content: str) -> list[ParsedModel]:
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


def _collect_defs(file_path: str, content: str) -> list[ParsedModel]:
    """Pass 1 only: collect every class def (name, bases, fields, Meta).

    No transitive resolution or abstract filtering — callers combine the
    result with definitions from other files before calling
    ``_resolve_and_filter``.
    """
    # Strip leading BOM (U+FEFF) — Windows editors (Notepad, VS Code with
    # certain settings) save UTF-8 files with a byte-order mark. Without this
    # the first line becomes "﻿class Foo..." and CLASS_RE fails to match.
    if content.startswith("﻿"):
        content = content[1:]
    # Expand tab characters to 4 spaces so the ``\s{indent}`` prefix used in
    # FIELD_RE / BARE_FIELD_RE / META_ITEM_RE matches tab-indented code too.
    # A single ``\t`` character otherwise contributes 1 to ``\s`` even though
    # it's visually 4 columns — tab-indented models used to have zero fields
    # detected. Line numbers are preserved (per-line expansion only).
    lines = [line.expandtabs(4) for line in content.splitlines()]
    all_defs: list[ParsedModel] = []
    parent = os.path.basename(os.path.dirname(file_path))
    if parent == "models":
        app_name = os.path.basename(os.path.dirname(os.path.dirname(file_path)))
    else:
        app_name = parent or "app"

    i = 0
    while i < len(lines):
        line = lines[i]
        # A class indented inside a module-level ``if`` is still a model (see
        # _encloses_only_blocks). Match the dedented view so the ``^class``
        # anchor keeps meaning "start of the statement", not "column 0".
        class_indent = len(line) - len(line.lstrip())
        probe = line if class_indent == 0 else line.lstrip()
        class_match = CLASS_RE.match(probe)
        if class_match and class_indent and not _encloses_only_blocks(
            lines, i, class_indent
        ):
            i += 1
            continue
        class_header_end = i
        if not class_match and class_indent == 0 and CLASS_START_RE.match(line):
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
            # An indented class ends where the source dedents back out of it.
            # Column-0 classes keep the original terminator exactly, so files
            # without conditional models parse byte-for-byte as before.
            if (
                class_indent
                and inner.strip()
                and len(inner) - len(inner.lstrip()) <= class_indent
            ):
                break
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
                        value, k = _read_meta_value(lines, k, m2.group(2))
                        model.meta[m2.group(1)] = value
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


def _read_meta_value(
    lines: list[str], start: int, first_line: str
) -> tuple[str, int]:
    """Join a ``Meta`` entry that spans lines. Returns ``(value, last_index)``.

    ``Meta.indexes`` and ``Meta.constraints`` are almost always written one
    entry per line. The per-line regex captured only ``[`` for those, so every
    consumer saw an empty list and, in the case of ``suggest-index``, proposed
    indexes the model already had (#60). Continuation lines are pulled in
    until the brackets opened on the first line close again.

    A value that balances on its own first line is returned untouched, so
    every single-line ``Meta`` entry parses exactly as before.
    """
    def _depth(text: str) -> int:
        return (
            text.count("(") - text.count(")")
            + text.count("[") - text.count("]")
            + text.count("{") - text.count("}")
        )

    parts = [first_line.strip()]
    depth = _depth(parts[0])
    k = start
    # Bounded so an unclosed bracket cannot walk the rest of the file.
    while depth > 0 and k + 1 < len(lines) and k - start < 200:
        k += 1
        nxt = lines[k]
        if not nxt.strip():
            continue
        parts.append(nxt.strip())
        depth += _depth(nxt)
    return " ".join(parts).strip(), k


def _is_abstract(model: ParsedModel) -> bool:
    return model.meta.get("abstract", "").strip() in ("True", "1", "true")


def _abstract_bases_fields(
    model: ParsedModel,
    by_name: dict[str, ParsedModel],
    stack: tuple[str, ...] = (),
) -> list[ParsedField]:
    """Fields ``model`` inherits from its abstract bases, parent-first.

    Only *abstract* bases contribute. A concrete base is multi-table
    inheritance, where the parent keeps its own table and the child gains a
    ``parent_ptr`` rather than copies of the columns — counting those as the
    child's own would invent columns that no migration will ever create.

    Bases are walked in declaration order and the first declaration of a name
    wins, which is the direction Python's MRO resolves for the single-
    inheritance chains this actually matters for. ``stack`` breaks cycles in
    malformed source instead of recursing forever.
    """
    out: list[ParsedField] = []
    taken: set[str] = set()
    for base in model.base_classes:
        tail = base.split(".")[-1]
        if tail in stack:
            continue
        parent = by_name.get(tail)
        if parent is None or parent is model or not _is_abstract(parent):
            continue
        contributed = [
            *_abstract_bases_fields(parent, by_name, (*stack, tail)),
            *(
                replace(f, inherited_from=f.inherited_from or parent.name)
                for f in parent.fields
            ),
        ]
        for f in contributed:
            if f.name in taken:
                continue
            taken.add(f.name)
            out.append(f)
    return out


def _attach_inherited_fields(all_defs: list[ParsedModel]) -> None:
    """Populate ``inherited_fields`` on every def, in place.

    Runs before the abstract classes are dropped — they are the only source
    of inherited fields, so the merge has to happen while they are still in
    the list. A field the class declares itself shadows the inherited one of
    the same name, exactly as an override does in Django.
    """
    by_name: dict[str, ParsedModel] = {}
    for m in all_defs:
        # First definition wins when two files declare the same class name;
        # the parser has no import graph to disambiguate with.
        by_name.setdefault(m.name, m)
    for m in all_defs:
        own = {f.name for f in m.fields}
        m.inherited_fields = [
            f for f in _abstract_bases_fields(m, by_name) if f.name not in own
        ]


def _resolve_and_filter(all_defs: list[ParsedModel]) -> list[ParsedModel]:
    """Pass 2: transitive model resolution + abstract drop over ``all_defs``.

    ``all_defs`` may come from a single file (``parse_models_file``) or the
    union of every file in a scan (``scan_workspace``) — resolution matches
    each base's tail name against whatever definitions are present, so a
    base class defined in another file is found when the union is passed.
    """
    _attach_inherited_fields(all_defs)
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

    result: list[ParsedModel] = []
    for m in all_defs:
        if m.name not in is_model_name:
            continue
        abstract_val = m.meta.get("abstract", "").strip()
        if abstract_val in ("True", "1", "true"):
            continue
        result.append(m)
    return result


#: Files that declare models but are not named ``models.py``. Pluggable
#: Django frameworks keep their abstract bases here and leave ``models.py``
#: holding only the concrete subclasses — django-oscar does this in all 14 of
#: its apps. Without reading these, oscar's models parse as 82 classes with
#: zero fields between them: found, but empty, which reads as a schema that
#: lost its columns.
MODEL_SOURCE_FILES = frozenset({"models.py", "abstract_models.py"})


def _iter_python_files(root: Path, excludes: Sequence[str]) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name in MODEL_SOURCE_FILES or (
                os.path.basename(dirpath) == "models"
                and name.endswith(".py")
                and name != "__init__.py"
            ):
                full = Path(dirpath) / name
                rel_posix = full.relative_to(root).as_posix()
                if any(fnmatch(rel_posix, pat) for pat in excludes):
                    continue
                yield full


def _app_dir_for(fs_path: str) -> tuple[str, str]:
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

# Directory names skipped when walking a workspace for arbitrary ``.py`` files
# (n+1 scanner, signal graph). Kept broader than ``DEFAULT_EXCLUDES`` on purpose:
# those are glob patterns for the models.py walk, this is a dirname-based
# denylist for the whole-tree walk.
BROAD_SKIP_DIRS: frozenset = frozenset(
    {"migrations", "node_modules", "venv", ".venv", "env", ".git", "__pycache__"}
)


def iter_workspace_py_files(
    root: Path, extra_skip: frozenset = frozenset()
) -> Iterable[Path]:
    """Yield every ``.py`` file under ``root`` except vendored / VCS junk.

    Uses :data:`BROAD_SKIP_DIRS` plus ``extra_skip`` (e.g.
    ``{"site-packages", "dist"}`` for the n+1 scanner). Dot-prefixed
    directories are always skipped. Consolidates three earlier per-module
    copies of the same walk so a change to the skip list stays in one place.
    """
    skip = BROAD_SKIP_DIRS | extra_skip
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d not in skip
        ]
        for name in filenames:
            if name.endswith(".py"):
                yield Path(dirpath) / name


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
    all_defs: list[ParsedModel] = []
    scanned_files = 0
    for py in _iter_python_files(root_path, exclude_globs):
        scanned_files += 1
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
    return WorkspaceIndex(
        apps=sorted_apps,
        scanned_at=int(time.time() * 1000),
        scanned_files=scanned_files,
    )
