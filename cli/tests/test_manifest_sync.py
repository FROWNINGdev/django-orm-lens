"""Guards against version / tool-count drift across the release manifests.

The same class of release bug keeps recurring: ``cli/pyproject.toml`` gets
bumped while ``cli/server.json`` (MCP registry) or the repo-root
``smithery.yaml`` (Smithery deployment) keeps the old version, or a new
MCP tool lands without the mcp_server module docstring's tool count moving.
Each drift ships a manifest that lies to a registry. These tests compare
the files against each other — no version is hardcoded, so a routine bump
touching all files stays green.

Parsing is regex/json only (zero new dependencies: no toml/yaml libs —
tomllib is 3.11+ and this package supports 3.9). Every check skips (not
fails) when its file is absent, because the PyPI sdist ships neither
``smithery.yaml`` nor anything above ``cli/``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

CLI_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CLI_DIR.parent

PYPROJECT = CLI_DIR / "pyproject.toml"
SERVER_JSON = CLI_DIR / "server.json"
SMITHERY_YAML = REPO_ROOT / "smithery.yaml"
MCP_SERVER_PY = CLI_DIR / "django_orm_lens" / "mcp_server.py"

# Written-out numerals for the docstring phrase "Exposes <word> read-only
# tools". Extend if the registry ever grows past fifteen.
_INT_WORDS = {
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
}


def _pyproject_version() -> str:
    if not PYPROJECT.is_file():
        pytest.skip("pyproject.toml not present (installed-package run)")
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    assert m, "could not find a version = \"...\" line in pyproject.toml"
    return m.group(1)


def test_server_json_versions_match_pyproject() -> None:
    if not SERVER_JSON.is_file():
        pytest.skip("server.json not shipped in this distribution")
    version = _pyproject_version()
    data = json.loads(SERVER_JSON.read_text(encoding="utf-8"))

    assert data.get("version") == version, (
        f"server.json .version is {data.get('version')!r} but pyproject.toml "
        f"says {version!r} — bump both in the release commit"
    )
    packages = data.get("packages") or []
    assert packages, "server.json has no packages[] entry"
    assert packages[0].get("version") == version, (
        f"server.json .packages[0].version is {packages[0].get('version')!r} "
        f"but pyproject.toml says {version!r}"
    )


def test_smithery_yaml_version_matches_pyproject() -> None:
    if not SMITHERY_YAML.is_file():
        pytest.skip("smithery.yaml not present (sdist has no repo root)")
    version = _pyproject_version()
    text = SMITHERY_YAML.read_text(encoding="utf-8")
    m = re.search(r'(?m)^version:\s*"?([^"\s]+)"?\s*$', text)
    assert m, "could not find a top-level version: line in smithery.yaml"

    assert m.group(1) == version, (
        f"smithery.yaml version is {m.group(1)!r} but pyproject.toml says "
        f"{version!r} — bump both in the release commit"
    )


def _registered_tool_count_and_docstring():
    """Return ``(tool_count, module_docstring)`` for mcp_server.

    Preferred path imports the TOOLS registry directly; if the import fails
    (e.g. a future refactor makes the module require the optional ``mcp``
    package at import time), fall back to reading the source text.
    """
    try:
        from django_orm_lens import mcp_server

        return len(mcp_server.TOOLS), mcp_server.__doc__ or ""
    except ImportError:
        if not MCP_SERVER_PY.is_file():
            pytest.skip("mcp_server.py source not available")
        source = MCP_SERVER_PY.read_text(encoding="utf-8")
        block = re.search(r"(?ms)^TOOLS\s*=\s*\{(.*?)^\}", source)
        assert block, "could not locate the TOOLS = {...} literal"
        # Top-level keys sit at one indent level: '    "tool_name": {'
        keys = re.findall(r'(?m)^    "([A-Za-z0-9_]+)":\s*\{', block.group(1))
        doc = re.match(r'\s*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')', source, re.S)
        return len(keys), doc.group(1) if doc else ""


def test_mcp_tool_count_matches_module_docstring() -> None:
    count, docstring = _registered_tool_count_and_docstring()

    assert count in _INT_WORDS, (
        f"TOOLS registry has {count} entries — outside the 5..15 range this "
        f"test can spell out; extend _INT_WORDS"
    )
    expected_phrase = f"Exposes {_INT_WORDS[count]} read-only tools"
    assert expected_phrase in docstring, (
        f"mcp_server registers {count} tools but the module docstring does "
        f"not say {expected_phrase!r} — update the docstring (and README "
        f"blurbs) when adding/removing tools"
    )
