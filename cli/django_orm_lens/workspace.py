"""Workspace resolution + hardening + cache for the MCP server.

Motivation
==========
Before py-1.3.0 every tool called ``_workspace_root()`` which returned
``os.environ["DJANGO_ORM_LENS_ROOT"]`` or ``os.getcwd()``. Tool signatures
did not accept an explicit ``workspace_root`` argument, so an AI agent that
tried the intuitive ``list_apps(workspace_root="/repo")`` had that argument
silently dropped by FastMCP (unknown kwargs) — the agent then received an
empty ``[]`` back and assumed the tool was broken. This module fixes that.

Responsibilities
================
1. **Resolve** — priority: explicit argument > ``DJANGO_ORM_LENS_ROOT`` env
   var > current working directory. Matches the reference-server precedent
   (filesystem-server, git-mcp): explicit configuration outranks discovery.
2. **Harden** — expand ``~``/``$env``, ``.resolve()`` to collapse ``..`` and
   follow symlinks, enforce an optional allowlist via
   ``DJANGO_ORM_LENS_ALLOWED_ROOTS``, require a Django marker (``manage.py``,
   ``django`` in ``pyproject.toml``, or at least one ``models.py`` in the
   tree), reject Windows reserved names.
3. **Cache** — the workspace index is cached with a compound key of
   ``(resolved_path, manage_py_mtime)`` so an in-place edit to ``manage.py``
   invalidates automatically. The cache is LRU-capped at 8 workspaces to
   keep memory bounded when an agent hops between projects.

Failures produce structured :class:`WorkspaceError` objects. The MCP wrapper
serializes them as ``{"error": "...", "hint": "..."}`` envelopes instead of
returning empty results, giving agents an actionable message.

MCP ``roots/list``
==================
The MCP spec exposes a ``roots/list`` capability that some clients (Cursor,
Claude Desktop) advertise inconsistently — the request can deadlock (see
modelcontextprotocol/python-sdk#1097) and roots-only discovery breaks under
several tracked issues (aws-toolkit-jetbrains#6173, openai/codex#9989). For
py-1.3.0 we deliberately skip runtime roots negotiation in favour of the
three deterministic sources above; adding it would trade correctness for a
half-supported feature. A follow-up release may layer it in behind a
capability check without changing this module's sync API.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from .models import WorkspaceIndex
from .parser import DEFAULT_EXCLUDES, scan_workspace

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_CACHE_TTL_MS = 30_000
_CACHE_MAX = 8

DJANGO_MARKERS: Tuple[str, ...] = ("manage.py", "manage.pyw")

# Windows-reserved base names (case-insensitive). Reject when found as any
# path component — Windows treats ``C:\foo\CON\bar`` as opening the console
# device, which is never what the agent means.
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkspaceError:
    """Structured failure returned to the agent as a JSON envelope.

    Codes are stable strings that clients can pattern-match. ``hint`` should
    always tell the agent what to try next; ``path`` echoes the offending
    input (redacted-safe: it is what the agent already knows).
    """

    code: str
    message: str
    hint: str = ""
    path: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "error": self.code,
            "message": self.message,
            "hint": self.hint,
            "path": self.path,
        }


# ---------------------------------------------------------------------------
# Hardening
# ---------------------------------------------------------------------------


def _allowlist() -> List[Path]:
    """Return the (possibly empty) allowlist of root prefixes.

    Populate with a path-separator-delimited list in
    ``DJANGO_ORM_LENS_ALLOWED_ROOTS`` (``;`` on Windows, ``:`` elsewhere).
    An empty list means "no restriction" — the historical default and the
    only sane choice for a locally-launched developer tool.
    """
    raw = os.environ.get("DJANGO_ORM_LENS_ALLOWED_ROOTS", "").strip()
    if not raw:
        return []
    sep = ";" if os.name == "nt" else ":"
    out: List[Path] = []
    for chunk in raw.split(sep):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(Path(chunk).expanduser().resolve(strict=False))
        except OSError:
            continue
    return out


def _has_windows_reserved(p: Path) -> bool:
    """True if any path component matches a Windows reserved device name.

    Checked on all platforms — an allowlist should not depend on the host
    OS, since paths flow between machines (SSH, docker cp, cross-mount).
    """
    for part in p.parts:
        base = part.split(".", 1)[0].upper()
        if base in _WIN_RESERVED:
            return True
    return False


def _is_within(child: Path, parent: Path) -> bool:
    """Robust replacement for ``Path.is_relative_to`` (3.9 gained it, but
    it raises on cross-drive comparisons and is subtly picky about trailing
    separators). ``os.path.commonpath`` normalizes both sides and returns a
    single reliable equality check.
    """
    try:
        return child == parent or Path(
            os.path.commonpath([str(child), str(parent)])
        ) == parent
    except ValueError:
        # Cross-drive on Windows raises ValueError — obviously not contained.
        return False


def _has_django_marker(p: Path) -> bool:
    """Return True if the directory looks like a Django project.

    Three accepted shapes, in cheapest-first order:

    * ``manage.py`` / ``manage.pyw`` at the root — the canonical Django layout.
    * ``pyproject.toml`` naming ``django`` as a dep — modern Poetry / PEP-621
      projects that ship without ``manage.py`` (docker-first apps).
    * At least one ``models.py`` in the tree (bounded 4-level walk) — the
      original heuristic that the VS Code extension has always used, kept
      for weird nested layouts (mono-repos, split ``apps/`` folder, etc.).

    The walk is depth-capped to keep the check O(shallow) even when a user
    points us at ``/`` by accident.
    """
    if not p.is_dir():
        return False
    for marker in DJANGO_MARKERS:
        if (p / marker).exists():
            return True
    pyproj = p / "pyproject.toml"
    if pyproj.exists():
        try:
            text = pyproj.read_text(encoding="utf-8", errors="replace")
            # Match three shapes:
            #   ``django = "^5.1"``            (poetry [tool.poetry.dependencies])
            #   ``"django>=5.1"``, ``'django'`` (PEP-621 dependencies array item)
            #   ``Django``                       (bare requirements-like reference)
            if re.search(
                r"(?im)(?:^\s*django\s*[=~<>!]|['\"]django[^'\"\s]*['\"])",
                text,
            ):
                return True
        except OSError:
            pass
    for root, dirs, files in os.walk(p):
        if "models.py" in files:
            return True
        rel = Path(root).relative_to(p)
        if len(rel.parts) >= 4:
            dirs[:] = []
    return False


def harden_path(raw: str) -> Union[Path, WorkspaceError]:
    """Expand + resolve + validate a raw path from an untrusted source.

    Returns the resolved absolute ``Path`` on success, or a
    :class:`WorkspaceError` describing the exact failure otherwise.

    Semantics deliberately mirror the reference filesystem-server pattern:
    resolve first (collapsing ``..`` and symlinks), then validate the
    *resolved* path, never the raw input. This defeats path-traversal
    attacks that rely on the pre-resolution string looking benign.
    """
    if not raw:
        return WorkspaceError(
            code="WORKSPACE_EMPTY",
            message="No workspace root provided.",
            hint=(
                "Pass workspace_root argument, set DJANGO_ORM_LENS_ROOT env "
                "var, or launch the server from your Django project directory."
            ),
        )
    expanded = os.path.expandvars(os.path.expanduser(raw))
    try:
        resolved = Path(expanded).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        return WorkspaceError(
            code="WORKSPACE_RESOLVE_FAILED",
            message=f"Could not resolve path: {exc}",
            path=raw,
        )
    if _has_windows_reserved(resolved):
        return WorkspaceError(
            code="WORKSPACE_WINDOWS_RESERVED",
            message="Path contains a Windows reserved device name (CON/PRN/AUX/NUL/COMn/LPTn).",
            path=str(resolved),
        )
    if not resolved.exists():
        return WorkspaceError(
            code="WORKSPACE_NOT_FOUND",
            message=f"Path does not exist: {resolved}",
            hint="Check the workspace_root argument, or omit it to fall back to the current directory.",
            path=str(resolved),
        )
    if not resolved.is_dir():
        return WorkspaceError(
            code="WORKSPACE_NOT_A_DIRECTORY",
            message=f"Not a directory: {resolved}",
            path=str(resolved),
        )
    allowed = _allowlist()
    if allowed and not any(_is_within(resolved, a) for a in allowed):
        return WorkspaceError(
            code="WORKSPACE_NOT_ALLOWED",
            message=(
                f"Path {resolved} is not within any "
                "DJANGO_ORM_LENS_ALLOWED_ROOTS entry."
            ),
            hint=(
                "Add the parent directory to DJANGO_ORM_LENS_ALLOWED_ROOTS, "
                "or unset that env var to allow any path."
            ),
            path=str(resolved),
        )
    if not _has_django_marker(resolved):
        return WorkspaceError(
            code="WORKSPACE_NOT_DJANGO",
            message=(
                f"No Django project markers (manage.py, django dep in "
                f"pyproject.toml, or models.py) found under {resolved}."
            ),
            hint="Point workspace_root at your Django project root — the directory containing manage.py.",
            path=str(resolved),
        )
    return resolved


# ---------------------------------------------------------------------------
# Resolution priority chain
# ---------------------------------------------------------------------------


def resolve_workspace(explicit: Optional[str] = None) -> Union[Path, WorkspaceError]:
    """Resolve a workspace root using the sync priority chain.

    Priority (matches filesystem-server + git-mcp precedent):

    1. Explicit ``workspace_root`` argument passed to a tool.
    2. ``DJANGO_ORM_LENS_ROOT`` environment variable.
    3. Current working directory.

    A resolution *failure* at step 1 or 2 is returned immediately — we do not
    silently fall through, because the agent chose a source and getting no
    signal about why it failed is exactly the class of bug this module fixes.
    A resolution *miss* (source is empty / unset) does fall through.
    """
    if explicit:
        return harden_path(explicit)
    env_val = os.environ.get("DJANGO_ORM_LENS_ROOT", "").strip()
    if env_val:
        return harden_path(env_val)
    return harden_path(os.getcwd())


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


_INDEX_CACHE: Dict[Tuple[str, int], Tuple[WorkspaceIndex, int]] = {}


def _manage_py_mtime(p: Path) -> int:
    """Return manage.py mtime (int seconds) for cache salting, or 0 if absent."""
    for marker in DJANGO_MARKERS:
        try:
            return int((p / marker).stat().st_mtime)
        except OSError:
            continue
    return 0


def get_index(root: Path) -> WorkspaceIndex:
    """Return a cached :class:`WorkspaceIndex` for the given resolved root.

    Keyed by ``(str(root), manage.py mtime)``. Editing ``manage.py`` bumps
    the mtime, forcing a fresh scan on the next call — this catches the
    common "agent scaffolded a new app between tool calls" case without
    waiting for the TTL. Cache is LRU-capped to :data:`_CACHE_MAX` entries.
    """
    now_ms = int(time.time() * 1000)
    key = (str(root), _manage_py_mtime(root))
    entry = _INDEX_CACHE.get(key)
    if entry is not None and entry[1] > now_ms:
        return entry[0]
    idx = scan_workspace(str(root), DEFAULT_EXCLUDES)
    _INDEX_CACHE[key] = (idx, now_ms + _CACHE_TTL_MS)
    if len(_INDEX_CACHE) > _CACHE_MAX:
        # Evict the entry closest to expiry — a proxy for "least recently used"
        # since we bump the expiry on every fresh scan.
        oldest_key = min(_INDEX_CACHE, key=lambda k: _INDEX_CACHE[k][1])
        _INDEX_CACHE.pop(oldest_key, None)
    return idx


def clear_cache() -> None:
    """Test hook — drop every cached index."""
    _INDEX_CACHE.clear()
