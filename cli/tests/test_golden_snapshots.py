"""Full-output regression net over the vendored real-world fixture projects.

test_golden_fixtures.py only asserts the parser *survives* Zulip, Saleor,
Wagtail, django-CMS, Mezzanine, and Read the Docs. A parser change can
silently drop a field, mangle a Meta block, or lose a relation on
real-world code while that suite stays green. This suite pins the complete
``scan_workspace`` output for each project against a committed snapshot,
so any behavioral diff on real code shows up as a reviewable unified diff.

Snapshot files
--------------
``fixtures/golden/<project>.snapshot.json`` — stored as plain files inside
the golden directory (NOT a subdirectory: test_golden_fixtures.py treats
every subdirectory of ``golden/`` as a vendored project via ``iterdir``,
so a snapshot folder there would break its parametrization).

Each snapshot is ``scan_workspace(<project>, DEFAULT_EXCLUDES).to_dict()``
serialized with ``json.dumps(..., indent=2, sort_keys=True,
ensure_ascii=False)`` plus a trailing newline, after normalization:

* ``scannedAt`` (wall-clock ms) is zeroed — differs every run;
* app ``path`` / model ``filePath`` are rewritten project-root-relative
  with POSIX separators — ``to_dict`` embeds absolute OS-specific paths;
* model lists are sorted by ``(filePath, lineNumber)`` and apps by
  ``(name, path)`` — ``os.walk`` order is filesystem-dependent (NTFS
  returns names sorted, ext4 does not).

Line numbers and everything else stay byte-exact.

Updating
--------
After an intentional parser change, regenerate and commit:

    UPDATE_GOLDEN_SNAPSHOTS=1 python -m pytest tests/test_golden_snapshots.py

(PowerShell: ``$env:UPDATE_GOLDEN_SNAPSHOTS='1'; python -m pytest ...``)
"""

from __future__ import annotations

import difflib
import json
import os
from itertools import islice
from pathlib import Path

import pytest

from django_orm_lens.parser import DEFAULT_EXCLUDES, scan_workspace

GOLDEN = Path(__file__).parent / "fixtures" / "golden"

# Explicit list (not iterdir) so a deleted or renamed fixture project fails
# loudly here instead of silently shrinking the net.
PROJECTS = ("django-cms", "mezzanine", "readthedocs", "saleor", "wagtail", "zulip")

_REGEN_HINT = (
    "If the change is intentional, regenerate snapshots with "
    "UPDATE_GOLDEN_SNAPSHOTS=1 python -m pytest tests/test_golden_snapshots.py"
)


def _snapshot_path(project: str) -> Path:
    return GOLDEN / f"{project}.snapshot.json"


def _rel_posix(root: Path, value: str) -> str:
    p = Path(value)
    try:
        return p.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return p.as_posix()


def _normalize(payload: dict, project_root: Path) -> dict:
    root = project_root.resolve()
    out = json.loads(json.dumps(payload))  # deep copy, JSON-clean
    out["scannedAt"] = 0
    for app in out["apps"]:
        app["path"] = _rel_posix(root, app["path"])
        for model in app["models"]:
            model["filePath"] = _rel_posix(root, model["filePath"])
        app["models"].sort(key=lambda m: (m["filePath"], m["lineNumber"]))
    out["apps"].sort(key=lambda a: (a["name"], a["path"]))
    return out


def build_snapshot(project: str) -> str:
    """Parse one golden project and return its normalized snapshot text."""
    project_root = GOLDEN / project
    index = scan_workspace(str(project_root), DEFAULT_EXCLUDES)
    normalized = _normalize(index.to_dict(), project_root)
    return (
        json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )


def _update_mode() -> bool:
    return os.environ.get("UPDATE_GOLDEN_SNAPSHOTS") == "1"


@pytest.mark.parametrize("project", PROJECTS)
def test_parse_output_matches_snapshot(project: str) -> None:
    live = build_snapshot(project)
    snap_file = _snapshot_path(project)

    if _update_mode():
        with open(snap_file, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(live)
        return

    assert snap_file.is_file(), (
        f"snapshot {snap_file.name} is missing. {_REGEN_HINT}"
    )
    stored = snap_file.read_text(encoding="utf-8")
    if live == stored:
        return

    diff_lines = list(
        islice(
            difflib.unified_diff(
                stored.splitlines(),
                live.splitlines(),
                fromfile=f"{snap_file.name} (committed)",
                tofile=f"{project} (live parse)",
                lineterm="",
            ),
            40,
        )
    )
    pytest.fail(
        f"parser output for {project!r} diverged from its snapshot "
        f"(first 40 diff lines):\n" + "\n".join(diff_lines) + f"\n{_REGEN_HINT}"
    )


def _model_count(payload: dict) -> int:
    return sum(len(app["models"]) for app in payload["apps"])


def test_total_model_count_matches_snapshots() -> None:
    """Guard against accidental fixture deletion: the live parse of all six
    projects must produce exactly as many models as the committed snapshots
    record. A vanished models.py drops the live count; a vanished snapshot
    fails the lookup."""
    if _update_mode():
        pytest.skip("snapshots are being regenerated in this run")

    live_total = 0
    snapshot_total = 0
    for project in PROJECTS:
        live_total += _model_count(
            json.loads(build_snapshot(project))
        )
        snap_file = _snapshot_path(project)
        assert snap_file.is_file(), (
            f"snapshot {snap_file.name} is missing. {_REGEN_HINT}"
        )
        snapshot_total += _model_count(
            json.loads(snap_file.read_text(encoding="utf-8"))
        )

    assert live_total > 0, "0 models parsed across all golden projects"
    assert live_total == snapshot_total, (
        f"live parse found {live_total} models but snapshots record "
        f"{snapshot_total} — a fixture or snapshot file was likely "
        f"deleted or truncated. {_REGEN_HINT}"
    )
