"""Golden fixture suite: parser must survive real-world Django code.

Vendored `models.py` files from Zulip, Saleor, Wagtail, and django-CMS live
under ``cli/tests/fixtures/golden/<project>/``. See that directory's README.md
for attribution, licences, and fetch date.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from django_orm_lens.parser import scan_workspace

FIXTURES = Path(__file__).parent / "fixtures" / "golden"

PROJECTS = sorted(
    p.name for p in FIXTURES.iterdir() if p.is_dir() and p.name != "__pycache__"
)


@pytest.mark.parametrize("project", PROJECTS)
def test_scan_survives_real_project(project: str) -> None:
    """Parser must not raise + must find at least 1 model in each vendored project."""
    path = FIXTURES / project
    result = scan_workspace(str(path))
    assert result.apps, f"{project}: no apps parsed (parser failed silently?)"
    total_models = sum(len(a.models) for a in result.apps)
    assert total_models >= 1, f"{project}: 0 models found"


def test_all_projects_scan_under_2s() -> None:
    """All golden fixtures combined must scan under 2 seconds — regression guard."""
    t0 = time.time()
    result = scan_workspace(str(FIXTURES))
    elapsed = time.time() - t0
    assert elapsed < 2.0, (
        f"golden fixture scan took {elapsed:.2f}s, past 2s regression threshold"
    )
    # Sanity: aggregate scan finds every project's models.
    assert len(result.apps) >= len(PROJECTS), (
        f"aggregate scan lost apps: {len(result.apps)} apps for {len(PROJECTS)} projects"
    )
