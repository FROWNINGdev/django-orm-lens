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


def test_mcp_extra_pins_each_api_to_a_python_that_has_it() -> None:
    """Each mcp major must be bounded, and gated on a Python that can run it.

    mcp 2.0.0 removed `mcp.server.fastmcp`. While the bootstrap only knew that
    name, a bare `>=1.0` resolved 2.0.0 and every MCP user got "requires the
    'mcp' package" from a package that was installed — which is why this test
    used to demand a flat `<2` cap.

    `mcp_server._load_server_class()` now accepts either SDK, so the cap moves
    up rather than away. What replaces it is the constraint that actually
    binds: mcp 2.0 requires Python >= 3.10 while this package supports 3.9, so
    the two majors have to be split on an environment marker. Without the
    marker, pip on 3.9 finds no installable mcp 2.x and fails the whole extra.

    Both ceilings stay closed. A 3.0 that removes `MCPServer` the way 2.0
    removed `FastMCP` must fail here, not in a user's terminal.
    """
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    for extra in ("mcp", "full"):
        line = next(
            row
            for row in text.splitlines()
            if row.strip().startswith(f"{extra} = [")
        )
        assert "mcp>=1.0,<2" in line, f"{extra} must keep a 1.x branch: {line}"
        assert "mcp>=2.0,<3" in line, f"{extra} must cap 2.x below 3.0: {line}"
        assert (
            "python_version < '3.10'" in line
        ), f"{extra} must gate 1.x to Python 3.9: {line}"
        assert (
            "python_version >= '3.10'" in line
        ), f"{extra} must gate 2.x to Python 3.10+: {line}"
