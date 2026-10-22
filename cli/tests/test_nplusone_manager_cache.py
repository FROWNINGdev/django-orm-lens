"""Prefetch coverage follows Django's result cache, including chained operations."""

import ast
import re
from pathlib import Path
from typing import Any

import pytest

from django_orm_lens.query_analyzer import _collect_target_accesses, scan_for_nplusone
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
    pytest.param((".all().reverse()", False), id="reverse"),
    pytest.param((".iterator(chunk_size=10)", False), id="iterator"),
    pytest.param((".aggregate(total=Count('pk'))", False), id="aggregate"),
    pytest.param((".union(other)", False), id="union"),
    pytest.param((".intersection(other)", False), id="intersection"),
    pytest.param((".difference(other)", False), id="difference"),
    pytest.param((".defer('name')", False), id="defer"),
    pytest.param((".only('pk')", False), id="only"),
    pytest.param((".using('default')", False), id="using"),
    pytest.param((".alias(total=Count('pk'))", False), id="alias"),
    pytest.param((".extra(select={\"constant\": \"1\"})", False), id="extra"),
    pytest.param((".explain()", False), id="explain"),
    pytest.param((".dates('created', 'day')", False), id="dates"),
    pytest.param((".datetimes('created', 'day')", False), id="datetimes"),
    pytest.param((".in_bulk()", False), id="in_bulk"),
    pytest.param((".latest('pk')", False), id="latest"),
    pytest.param((".earliest('pk')", False), id="earliest"),
    pytest.param((".first()", False), id="first"),
    pytest.param((".last()", False), id="last"),
    pytest.param((".none()", False), id="none"),
    pytest.param((".prefetch_related()", False), id="prefetch_related"),
    pytest.param((".select_for_update()", False), id="select_for_update"),
    pytest.param((".contains(candidate)", True), id="contains"),
    pytest.param((".update(name=\"updated\")", False), id="update"),
    pytest.param((".all().delete()", False), id="delete"),
    pytest.param((".bulk_create(objects)", False), id="bulk_create"),
    pytest.param((".bulk_update(objects, fields)", False), id="bulk_update"),
    pytest.param((".update_or_create(pk=1, defaults=defaults)", False), id="update_or_create"),
    pytest.param((".aaggregate(total=Count('pk'))", False), id="aaggregate"),
    pytest.param((".acount()", True), id="acount"),
    pytest.param((".acontains(candidate)", True), id="acontains"),
    pytest.param((".aexists()", True), id="aexists"),
    pytest.param((".aget(pk=1)", False), id="aget"),
    pytest.param((".aiterator(chunk_size=10)", False), id="aiterator"),
    pytest.param((".aearliest('pk')", False), id="aearliest"),
    pytest.param((".alatest('pk')", False), id="alatest"),
    pytest.param((".afirst()", False), id="afirst"),
    pytest.param((".alast()", False), id="alast"),
    pytest.param((".ain_bulk()", False), id="ain_bulk"),
    pytest.param((".aexplain()", False), id="aexplain"),
    pytest.param((".aupdate(name=\"updated\")", False), id="aupdate"),
    pytest.param((".all().adelete()", False), id="adelete"),
    pytest.param((".abulk_create(objects)", False), id="abulk_create"),
    pytest.param((".abulk_update(objects, fields)", False), id="abulk_update"),
    pytest.param((".aupdate_or_create(pk=1, defaults=defaults)", False), id="aupdate_or_create"),
    pytest.param((".all().prefetch_related()", False), id="all-prefetch_related"),
    pytest.param((".all().contains(candidate)", True), id="all-contains"),
    pytest.param((".filter(pk=1).contains(candidate)", False), id="filter-contains"),
    pytest.param((".filter(pk=1).acount()", False), id="filter-acount"),
    pytest.param((".filter(pk=1).aexists()", False), id="filter-aexists"),
    pytest.param((".filter(pk=1).acontains(candidate)", False), id="filter-acontains"),
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
    accesses = _collect_target_accesses(
        ast.parse(f"print(obj.{relation}{suffix})").body, "obj",
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
    # Missing cache readers otherwise fall through as bare accesses with the same verdict.
    assert accesses[0][2] == tuple(re.findall(r"\.([a-z_]+)\(", suffix))


@pytest.mark.parametrize("method", [
    "add", "set", "remove", "clear", "create", "get_or_create", "raw",
    "acreate", "aget_or_create", "as_manager", "custom_query",
])
def test_non_queryset_manager_methods_remain_outside_gate(tmp_path: Path, method: str) -> None:
    source = f"for post in Post.objects.prefetch_related('tags'):\n    post.tags.{method}()\n"
    _write(tmp_path / "views.py", source)
    accesses = _collect_target_accesses(ast.parse(source).body[0].body, "post")
    assert accesses[0][2] == ()
    assert scan_for_nplusone(str(tmp_path), BLOG_SCHEMA) == []
