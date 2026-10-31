"""N+1 precision on patterns taken from large real-world codebases.

Each case was a false or misleading finding when the scanner was run over
NetBox, Healthchecks, Plane, authentik and paperless-ngx.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from django_orm_lens.cli import main
from django_orm_lens.query_analyzer import scan_for_nplusone
from tests.test_nplusone_detector import BLOG_SCHEMA, _write

SCHEMA = {
    **BLOG_SCHEMA,
    "Profile": {"user": "o2o", "email": "scalar"},
    "User": {"email": "scalar"},
}


def test_related_manager_writes_are_not_reads(tmp_path: Path) -> None:
    # NetBox: `interface.vdcs.set(vdcs)` used to be suggested a prefetch.
    _write(
        tmp_path / "views.py",
        "def tag_all(tags):\n"
        "    for post in Post.objects.all():\n"
        "        post.tags.set(tags)\n"
        "        post.tags.add(tags[0])\n"
        "        post.comment_set.create(body='x')\n",
    )
    assert scan_for_nplusone(str(tmp_path), SCHEMA) == []


def test_write_after_loading_a_single_valued_relation_is_still_flagged(tmp_path: Path) -> None:
    # Healthchecks: `profile.user.delete()` loads profile.user first. The fix
    # is select_related, and only select_related.
    _write(
        tmp_path / "prune.py",
        "def prune():\n"
        "    for profile in Profile.objects.filter(email=''):\n"
        "        print(profile.user.email)\n"
        "        profile.user.delete()\n",
    )
    (finding,) = scan_for_nplusone(str(tmp_path), SCHEMA)
    assert finding.suggested_fix == '.select_related("user")'


def test_schema_less_scan_never_suggests_both_clauses_for_one_field(tmp_path: Path) -> None:
    _write(
        tmp_path / "prune.py",
        "def prune(pq):\n"
        "    pq = pq.filter(active=False)\n"
        "    for profile in pq:\n"
        "        print(profile.user.email)\n"
        "        profile.user.delete()\n",
    )
    for finding in scan_for_nplusone(str(tmp_path), None):
        assert 'prefetch_related("user")' not in finding.suggested_fix


def test_assigning_a_relation_is_not_reading_it(tmp_path: Path) -> None:
    # NetBox virtualization/views.py: `device.cluster = cluster` in a loop.
    _write(
        tmp_path / "views.py",
        "def assign(cluster, pks):\n"
        "    for post in Post.objects.filter(pk__in=pks):\n"
        "        post.author = cluster\n"
        "        post.save()\n",
    )
    assert scan_for_nplusone(str(tmp_path), SCHEMA) == []


def test_writing_through_a_relation_still_loads_it(tmp_path: Path) -> None:
    _write(
        tmp_path / "views.py",
        "def rename(pks):\n"
        "    for post in Post.objects.filter(pk__in=pks):\n"
        "        post.author.name = 'x'\n",
    )
    (finding,) = scan_for_nplusone(str(tmp_path), SCHEMA)
    assert finding.suggested_fix == '.select_related("author")'


def test_method_call_on_the_instance_is_not_a_relation(tmp_path: Path) -> None:
    # Healthchecks api/views.py: `check.matches_tag_set(tags)` matched the
    # `<model>_set` reverse-manager heuristic.
    _write(
        tmp_path / "views.py",
        "def listing(tags):\n"
        "    for post in Post.objects.all():\n"
        "        if post.matches_tag_set(tags):\n"
        "            print(post.to_dict())\n",
    )
    assert scan_for_nplusone(str(tmp_path), SCHEMA) == []
    assert scan_for_nplusone(str(tmp_path), None) == []


def test_test_modules_are_skipped_unless_asked(tmp_path: Path) -> None:
    loop = (
        "def check():\n"
        "    for post in Post.objects.all():\n"
        "        print(post.author.name)\n"
    )
    for rel in ("tests/test_views.py", "app/tests.py", "app/test_api.py", "conftest.py", "app/views_test.py"):
        _write(tmp_path / rel, loop)
    _write(tmp_path / "app" / "views.py", loop)

    files = {f.file for f in scan_for_nplusone(str(tmp_path), SCHEMA)}
    assert files == {"app/views.py"}
    everything = {f.file for f in scan_for_nplusone(str(tmp_path), SCHEMA, include_tests=True)}
    assert len(everything) == 6


def test_cli_include_tests_flag(tmp_path: Path) -> None:
    _write(
        tmp_path / "tests" / "test_views.py",
        "def check():\n"
        "    for post in Post.objects.all():\n"
        "        print(post.author.name)\n",
    )

    def run(*extra: str) -> list:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["nplusone", "--path", str(tmp_path), "--format", "json", "--exit-zero", *extra])
        return json.loads(out.getvalue())

    assert run() == []
    assert len(run("--include-tests")) == 1
