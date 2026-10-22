"""Prefetch coverage follows Django's result cache, including chained operations."""

from pathlib import Path
from typing import Any

import pytest

from django_orm_lens.query_analyzer import scan_for_nplusone
from tests.test_nplusone_detector import BLOG_SCHEMA, SHOP_SCHEMA, _write


# Django QuerySet cloning discards _result_cache; count/exists and slicing read it.
# Manager.all() preserves it, whereas QuerySet.all() (the second all) clones.
@pytest.fixture(params=[
    pytest.param(("", True), id="bare"),
    pytest.param((".all()", True), id="all"),
    pytest.param((".filter(pk=1)", False), id="filter"),
    pytest.param((".exclude(pk=1)", False), id="exclude"),
    pytest.param((".count()", True), id="count"),
    pytest.param((".exists()", True), id="exists"),
    pytest.param((".get(pk=1)", False), id="get"),
    pytest.param((".order_by('pk')", False), id="order_by"),
    pytest.param((".values('pk')", False), id="values"),
    pytest.param((".values_list('pk')", False), id="values_list"),
    pytest.param((".annotate(total=Count('pk'))", False), id="annotate"),
    pytest.param((".distinct()", False), id="distinct"),
    pytest.param((".select_related()", False), id="select_related"),
    pytest.param(("[:5]", True), id="slice"),
    pytest.param((".all()[:5]", True), id="all-slice"),
    pytest.param((".all().all()", False), id="all-all"),
    pytest.param((".all().count()", True), id="all-count"),
    pytest.param((".all().exists()", True), id="all-exists"),
    pytest.param((".filter(pk=1).count()", False), id="filter-count"),
    pytest.param((".exclude(pk=1).all()", False), id="exclude-all"),
    pytest.param((".all().order_by('pk')", False), id="all-order_by"),
    pytest.param((".order_by('pk').all()", False), id="order_by-all"),
    pytest.param((".exclude(pk=1)[:5]", False), id="exclude-slice"),
])
def operation(request: pytest.FixtureRequest) -> tuple[str, bool]:
    return request.param


@pytest.mark.parametrize("prefetched", [False, True], ids=["unloaded", "prefetched"])
@pytest.mark.parametrize("model,relation,schema", [
    pytest.param("Post", "tags", BLOG_SCHEMA, id="m2m"),
    pytest.param("Post", "comment_set", BLOG_SCHEMA, id="reverse"),
    pytest.param("Item", "order.items", SHOP_SCHEMA, id="multi-hop-reverse"),
])
def test_manager_cache_coverage(
    tmp_path: Path, operation: tuple[str, bool], prefetched: bool,
    model: str, relation: str, schema: dict[str, Any],
) -> None:
    suffix, cache_served = operation
    path = relation.replace(".", "__")
    eager = f".prefetch_related('{path}')" if prefetched else ""
    _write(
        tmp_path / "views.py",
        "def index():\n"
        f"    for obj in {model}.objects.all(){eager}:\n"
        f"        print(obj.{relation}{suffix})\n",
    )
    findings = scan_for_nplusone(str(tmp_path), schema)
    assert bool(findings) == (not prefetched or not cache_served)
    if findings:
        # A cache-bypassing operation invalidates the terminal manager, retaining
        # the already-loaded FK prefix in the multi-hop case.
        expected = relation.split(".")[-1] if prefetched else path
        assert len(findings) == 1
        assert findings[0].accessed == [expected]
        assert findings[0].suggested_fix == f'.prefetch_related("{path}")'
