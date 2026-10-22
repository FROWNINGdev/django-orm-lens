"""Tests for the static N+1 detector.

The detector walks every ``.py`` file in a workspace, finds ``for ... in
<queryset>:`` loops, and flags attribute-chain accesses against the loop
target that touch a related object (FK / O2O / M2M / reverse FK) without
a corresponding ``select_related`` / ``prefetch_related`` clause on the
source queryset.

These tests build synthetic Django-shaped workspaces inside ``tmp_path``
and assert the returned finding list.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from django_orm_lens.query_analyzer import (
    NPlusOneFinding,
    NPlusOneScanner,
    scan_for_nplusone,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


BLOG_SCHEMA = {
    "Post": {
        "author": "fk",
        "title": "scalar",
        "body": "scalar",
        "tags": "m2m",
        "comment_set": "reverse",
    },
    "Author": {
        "name": "scalar",
        "email": "scalar",
    },
    "Tag": {
        "name": "scalar",
    },
    "Comment": {
        "post": "fk",
        "body": "scalar",
    },
}


SHOP_SCHEMA = {
    "apps": [{
        "name": "shop",
        "models": [
            {"name": "Order", "fields": []},
            {"name": "Item", "fields": [
                {"name": "order", "isRelation": True, "relationKind": "ForeignKey",
                 "relatedModel": "Order", "relatedName": "items"},
                {"name": "product", "isRelation": True, "relationKind": "ForeignKey",
                 "relatedModel": "Product"},
                {"name": "supplier", "isRelation": True, "relationKind": "ForeignKey",
                 "relatedModel": "Supplier"},
                {"name": "backup_order", "isRelation": True, "relationKind": "ForeignKey",
                 "relatedModel": "Order", "relatedName": "backup_items"},
            ]},
            {"name": "Product", "fields": [
                {"name": "category", "isRelation": True, "relationKind": "ForeignKey",
                 "relatedModel": "Category"},
                {"name": "name", "isRelation": False},
            ]},
            {"name": "Category", "fields": [{"name": "name", "isRelation": False}]},
            {"name": "Supplier", "fields": [{"name": "name", "isRelation": False}]},
        ],
    }],
}


class NestedRelationTest(unittest.TestCase):
    def _scan_nested(
        self, eager: str = "", *, schema_less: bool = False,
    ) -> list[NPlusOneFinding]:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from shop.models import Order\n"
                "def index(request):\n"
                f"    orders = Order.objects.all(){eager}\n"
                "    for order in orders:\n"
                "        for item in order.items.all():\n"
                "            print(item.product.category.name)\n",
            )
            return scan_for_nplusone(str(root), None if schema_less else SHOP_SCHEMA)

    def test_multihop_suggestion(self) -> None:
        findings = self._scan_nested()
        self.assertEqual([f.loop_var for f in findings], ["order", "item"])
        self.assertEqual(findings[0].accessed, ["items"])
        self.assertEqual(findings[0].suggested_fix, '.prefetch_related("items")')
        self.assertEqual(findings[1].suggested_fix, '.select_related("product__category")')
        self.assertEqual(findings[1].confidence, "high")

    def test_full_outer_prefetch_covers_inner_loop(self) -> None:
        self.assertEqual(
            self._scan_nested('.prefetch_related("items__product__category")'), [],
        )

    def test_prefetch_alias_leaves_final_relation_unloaded(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from django.db.models import Prefetch\n"
                "def index():\n"
                "    for order in Order.objects.prefetch_related(\n"
                "        Prefetch('items__product__category', to_attr='cached_category')\n"
                "    ):\n"
                "        for item in order.items.all():\n"
                "            print(item.product.category.name)\n",
            )
            self.assertEqual(scan_for_nplusone(str(root), SHOP_SCHEMA), [
                NPlusOneFinding(
                    file="views.py", line=6, loop_var="item", queryset_var="<inline>",
                    accessed=["category"], suggested_fix='.select_related("product__category")',
                    confidence="high",
                ),
            ])

    def test_plain_prefetch_object_covers_inner_loop(self) -> None:
        for destination in ("", ", to_attr=None", ", to_attr='' "):
            with self.subTest(destination=destination), TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write(
                    root / "views.py",
                    "from django.db.models import Prefetch\n"
                    "def index():\n"
                    "    for order in Order.objects.prefetch_related(\n"
                    f"        Prefetch('items__product__category'{destination})\n"
                    "    ):\n"
                    "        for item in order.items.all():\n"
                    "            print(item.product.category.name)\n",
                )
                self.assertEqual(scan_for_nplusone(str(root), SHOP_SCHEMA), [])

    def test_nearer_unpacking_loop_stops_inheritance(self) -> None:
        for target in ("order", "order, label", "[order, label]",
                       "label, (order, other)", "*order, label", "label, [*order]"):
            with self.subTest(target=target), TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write(
                    root / "views.py",
                    "def index(pairs):\n"
                    "    for order in Order.objects.prefetch_related('items__product__category'):\n"
                    f"        for {target} in pairs:\n"
                    "            for item in order.items.all():\n"
                    "                print(item.product.category.name)\n",
                )
                self.assertEqual(scan_for_nplusone(str(root), SHOP_SCHEMA), [
                    NPlusOneFinding(
                        file="views.py", line=4, loop_var="item", queryset_var="<inline>",
                        accessed=["product"], suggested_fix='.select_related("product")',
                        confidence="medium",
                    ),
                ])

    def test_unrelated_unpacking_loop_keeps_inheritance(self) -> None:
        for target in ("other, label", "[other, label]", "label, [*other]", "order.label"):
            with self.subTest(target=target), TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write(
                    root / "views.py",
                    "def index(pairs):\n"
                    "    for order in Order.objects.prefetch_related('items__product__category'):\n"
                    f"        for {target} in pairs:\n"
                    "            for item in order.items.all():\n"
                    "                print(item.product.category.name)\n",
                )
                self.assertEqual(scan_for_nplusone(str(root), SHOP_SCHEMA), [])

    def test_partial_outer_prefetch_reports_unloaded_category(self) -> None:
        findings = self._scan_nested('.prefetch_related("items__product")')
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].loop_var, "item")
        self.assertEqual(findings[0].accessed, ["category"])
        self.assertEqual(findings[0].suggested_fix, '.select_related("product__category")')

    def test_single_hop_inherited_prefetch_covers_inner_loop(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "def index():\n"
                "    for order in Order.objects.prefetch_related('items__product'):\n"
                "        for item in order.items.all():\n"
                "            print(item.product.name)\n",
            )
            self.assertEqual(scan_for_nplusone(str(root), SHOP_SCHEMA), [])

    def test_schema_less_keeps_single_attribute_heuristic(self) -> None:
        findings = self._scan_nested(schema_less=True)
        self.assertEqual([f.loop_var for f in findings], ["order", "item"])
        self.assertEqual(findings[1].accessed, ["product"])
        self.assertEqual(findings[1].suggested_fix, '.select_related("product")')
        self.assertEqual(findings[1].confidence, "medium")

    def test_wildcard_does_not_cover_multihop_path(self) -> None:
        for method in ("select_related", "prefetch_related"):
            with self.subTest(method=method), TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write(
                    root / "views.py",
                    "def index():\n"
                    f"    for item in Item.objects.{method}():\n"
                    "        print(item.product.category.name)\n",
                )
                findings = scan_for_nplusone(str(root), SHOP_SCHEMA)
                self.assertEqual(len(findings), 1)
                self.assertEqual(
                    findings[0].accessed,
                    ["category" if method == "select_related" else "product__category"],
                )
                self.assertEqual(findings[0].suggested_fix, '.select_related("product__category")')

    def test_direct_eager_paths_and_prefix_boundaries(self) -> None:
        for method in ("select_related", "prefetch_related"):
            for eager, accessed in (
                ("product__category", []), ("product", ["category"]),
                ("product__category_extra", ["category"]),
            ):
                with self.subTest(method=method, eager=eager), TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    _write(
                        root / "views.py",
                        "def index():\n"
                        f"    for item in Item.objects.{method}('{eager}'):\n"
                        "        print(item.product.category.name)\n",
                    )
                    findings = scan_for_nplusone(str(root), SHOP_SCHEMA)
                    self.assertEqual([a for f in findings for a in f.accessed], accessed)

    def test_validation_stops_at_scalar_or_unknown_hop(self) -> None:
        for access in ("product.name.category", "product.unknown.category"):
            with self.subTest(access=access), TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write(
                    root / "views.py",
                    "def index():\n"
                    "    for item in Item.objects.all():\n"
                    f"        print(item.{access})\n",
                )
                findings = scan_for_nplusone(str(root), SHOP_SCHEMA)
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0].suggested_fix, '.select_related("product")')

    def test_workspace_index_retains_relation_targets(self) -> None:
        from django_orm_lens.parser import scan_workspace

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "shop" / "models.py",
                "from django.db import models\n"
                "class Order(models.Model):\n"
                "    pass\n"
                "class Category(models.Model):\n"
                "    name = models.CharField(max_length=30)\n"
                "class Product(models.Model):\n"
                "    category = models.ForeignKey(Category, on_delete=models.CASCADE)\n"
                "class Item(models.Model):\n"
                "    product = models.ForeignKey(Product, on_delete=models.CASCADE)\n"
                "    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')\n",
            )
            _write(
                root / "views.py",
                "def index():\n"
                "    for item in Item.objects.all():\n"
                "        print(item.product.category.name)\n"
                "    for order in Order.objects.prefetch_related('items'):\n"
                "        for item in order.items.all():\n"
                "            print(item.order)\n",
            )
            findings = scan_for_nplusone(str(root), scan_workspace(str(root)))
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].suggested_fix, '.select_related("product__category")')

    def test_async_nested_prefetch(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "async def index():\n"
                "    async for order in Order.objects.prefetch_related('items__product__category'):\n"
                "        async for item in order.items.all():\n"
                "            print(item.product.category.name)\n",
            )
            self.assertEqual(scan_for_nplusone(str(root), SHOP_SCHEMA), [])

    def test_covered_chain_does_not_hide_other_access(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "def index():\n"
                "    for order in Order.objects.prefetch_related('items__product__category'):\n"
                "        for item in order.items.all():\n"
                "            print(item.product.category.name, item.supplier)\n",
            )
            findings = scan_for_nplusone(str(root), SHOP_SCHEMA)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].accessed, ["supplier"])
            self.assertEqual(findings[0].suggested_fix, '.select_related("supplier")')

    def test_reverse_manager_caches_inverse_fk(self) -> None:
        for eager in ("", ".prefetch_related('items')",
                      ".prefetch_related('items__product__category')"):
            for manager_call in ("all()", "filter(active=True)", "all().filter(active=True)"):
                with self.subTest(eager=eager, manager_call=manager_call), TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    _write(
                        root / "views.py",
                        "def index():\n"
                        f"    for order in Order.objects.all(){eager}:\n"
                        f"        for item in order.items.{manager_call}:\n"
                        "            print(item.order)\n",
                    )
                    findings = scan_for_nplusone(str(root), SHOP_SCHEMA)
                    self.assertEqual([f.loop_var for f in findings], [] if eager else ["order"])
                    if findings:
                        self.assertEqual(findings[0].accessed, ["items"])

    def test_inverse_cache_is_specific_to_incoming_relation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "def index():\n"
                "    for order in Order.objects.prefetch_related('items'):\n"
                "        for item in order.items.all():\n"
                "            print(item.order, item.backup_order)\n",
            )
            findings = scan_for_nplusone(str(root), SHOP_SCHEMA)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].accessed, ["backup_order"])
            self.assertEqual(findings[0].suggested_fix, '.select_related("backup_order")')

    def test_unrelated_or_invalid_manager_origin_keeps_finding(self) -> None:
        for origin in ("other.items", "order.unknown"):
            with self.subTest(origin=origin), TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write(
                    root / "views.py",
                    "def index():\n"
                    "    for order in Order.objects.prefetch_related('items__product__category'):\n"
                    f"        for item in {origin}.all():\n"
                    "            print(item.product.category.name)\n",
                )
                findings = scan_for_nplusone(str(root), SHOP_SCHEMA)
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0].loop_var, "item")
                self.assertEqual(findings[0].suggested_fix, '.select_related("product")')

    def test_nested_function_does_not_inherit_outer_loop(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "def index():\n"
                "    for order in Order.objects.prefetch_related('items__product__category'):\n"
                "        def nested(order):\n"
                "            for item in order.items.all():\n"
                "                print(item.product.category.name)\n",
            )
            findings = scan_for_nplusone(str(root), SHOP_SCHEMA)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].suggested_fix, '.select_related("product")')

    def test_filtered_manager_does_not_inherit_cache(self) -> None:
        for manager_call in ("filter(active=True)", "all().filter(active=True)"):
            with self.subTest(manager_call=manager_call), TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write(
                    root / "views.py",
                    "def index():\n"
                    "    for order in Order.objects.prefetch_related('items__product__category'):\n"
                    f"        for item in order.items.{manager_call}:\n"
                    "            print(item.product.category.name)\n",
                )
                findings = scan_for_nplusone(str(root), SHOP_SCHEMA)
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0].loop_var, "item")
                self.assertEqual(findings[0].suggested_fix, '.select_related("product__category")')


class ScanForNPlusOneTest(unittest.TestCase):
    # ------------------------------------------------------------------ POSITIVE

    def test_bare_all_loop_with_fk_access_flags_high(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from blog.models import Post\n"
                "def index(request):\n"
                "    posts = Post.objects.all()\n"
                "    for post in posts:\n"
                "        print(post.author.name)\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            self.assertEqual(len(findings), 1)
            f = findings[0]
            self.assertEqual(f.confidence, "high")
            self.assertEqual(f.queryset_var, "posts")
            self.assertIn("author", f.accessed)
            self.assertIn('.select_related("author")', f.suggested_fix)
            self.assertTrue(f.file.endswith("views.py"))

    def test_nested_loop_m2m_is_reported_separately(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from blog.models import Post\n"
                "def page(request):\n"
                "    posts = Post.objects.all()\n"
                "    for post in posts:\n"
                "        for tag in post.tags.all():\n"
                "            print(tag.name)\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            # Outer loop flags ``tags`` as m2m access.
            self.assertGreaterEqual(len(findings), 1)
            outer = [f for f in findings if f.queryset_var == "posts"]
            self.assertEqual(len(outer), 1)
            self.assertIn("tags", outer[0].accessed)
            self.assertIn("prefetch_related", outer[0].suggested_fix)

    def test_filter_result_iterated_still_flags(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "tasks.py",
                "from blog.models import Post\n"
                "def send_notifications():\n"
                "    qs = Post.objects.filter(published=True)\n"
                "    for post in qs:\n"
                "        notify(post.author)\n"
                "def notify(x): pass\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].confidence, "high")
            self.assertIn("author", findings[0].accessed)

    def test_reverse_fk_access_via_manager_is_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from blog.models import Post\n"
                "def show(request):\n"
                "    posts = Post.objects.all()\n"
                "    for post in posts:\n"
                "        for c in post.comment_set.all():\n"
                "            print(c.body)\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            outer = [f for f in findings if f.queryset_var == "posts"]
            self.assertEqual(len(outer), 1)
            self.assertIn("comment_set", outer[0].accessed)
            self.assertEqual(outer[0].confidence, "high")
            self.assertIn('prefetch_related("comment_set")', outer[0].suggested_fix)

    def test_inline_queryset_in_for_iter_is_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from blog.models import Post\n"
                "def run():\n"
                "    for post in Post.objects.all():\n"
                "        print(post.author.name)\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].queryset_var, "<inline>")
            self.assertEqual(findings[0].confidence, "high")

    def test_medium_confidence_without_schema(self) -> None:
        """No schema → detector falls back to structural heuristics.

        ``post.author.name`` is a 3-level chain — flagged medium-confidence
        as a probable FK traversal.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from blog.models import Post\n"
                "def run():\n"
                "    posts = Post.objects.all()\n"
                "    for post in posts:\n"
                "        print(post.author.name)\n",
            )
            findings = scan_for_nplusone(str(root))
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].confidence, "medium")

    # ------------------------------------------------------------------ NEGATIVE

    def test_select_related_covers_fk_no_finding(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from blog.models import Post\n"
                "def run():\n"
                "    posts = Post.objects.select_related('author').all()\n"
                "    for post in posts:\n"
                "        print(post.author.name)\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            self.assertEqual(findings, [])

    def test_prefetch_related_covers_m2m_no_finding(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from blog.models import Post\n"
                "def run():\n"
                "    posts = Post.objects.prefetch_related('tags').all()\n"
                "    for post in posts:\n"
                "        for tag in post.tags.all():\n"
                "            print(tag.name)\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            self.assertEqual(findings, [])

    def test_scalar_attribute_access_not_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from blog.models import Post\n"
                "def run():\n"
                "    posts = Post.objects.all()\n"
                "    for post in posts:\n"
                "        print(post.title, post.body)\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            self.assertEqual(findings, [])

    def test_non_queryset_iteration_not_flagged(self) -> None:
        """Iterating a plain list / dict / range shouldn't be flagged even
        without a schema.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "helpers.py",
                "def run():\n"
                "    items = [1, 2, 3]\n"
                "    for x in items:\n"
                "        print(x.author.name)\n"
                "    for i in range(10):\n"
                "        print(i)\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            self.assertEqual(findings, [])

    # ------------------------------------------------------------------ MISC

    def test_empty_project_returns_empty_findings(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            self.assertEqual(findings, [])

    def test_bad_python_file_is_skipped_gracefully(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "broken.py", "def broken(:\n    for x in y:\n")
            # Add one valid file too so we know the walker keeps going.
            _write(
                root / "views.py",
                "from blog.models import Post\n"
                "def run():\n"
                "    posts = Post.objects.all()\n"
                "    for post in posts:\n"
                "        print(post.author.name)\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            self.assertEqual(len(findings), 1)
            self.assertTrue(findings[0].file.endswith("views.py"))

    def test_migrations_and_venv_are_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "app" / "migrations" / "0001_initial.py",
                "from blog.models import Post\n"
                "def run():\n"
                "    posts = Post.objects.all()\n"
                "    for post in posts:\n"
                "        print(post.author.name)\n",
            )
            _write(
                root / "venv" / "lib" / "site-packages" / "junk.py",
                "from blog.models import Post\n"
                "def run():\n"
                "    posts = Post.objects.all()\n"
                "    for post in posts:\n"
                "        print(post.author.name)\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            self.assertEqual(findings, [])

    def test_finding_has_stable_shape(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from blog.models import Post\n"
                "def run():\n"
                "    posts = Post.objects.all()\n"
                "    for post in posts:\n"
                "        print(post.author.name)\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            self.assertEqual(len(findings), 1)
            d = findings[0].to_dict()
            self.assertEqual(
                set(d.keys()),
                {"file", "line", "loop_var", "queryset_var",
                 "accessed", "suggested_fix", "confidence"},
            )
            self.assertIsInstance(d["line"], int)
            self.assertIsInstance(d["accessed"], list)

    def test_workspace_index_schema_shape_accepted(self) -> None:
        """``scan_for_nplusone`` accepts the ``WorkspaceIndex.to_dict()``
        payload (as emitted by ``scan --format json``) directly.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from blog.models import Post\n"
                "def run():\n"
                "    posts = Post.objects.all()\n"
                "    for post in posts:\n"
                "        print(post.author.name)\n",
            )
            index_shape = {
                "apps": [
                    {
                        "name": "blog",
                        "path": "blog",
                        "models": [
                            {
                                "name": "Post",
                                "fields": [
                                    {
                                        "name": "author",
                                        "isRelation": True,
                                        "relationKind": "ForeignKey",
                                        "relatedModel": "Author",
                                    },
                                    {
                                        "name": "title",
                                        "isRelation": False,
                                    },
                                ],
                            },
                            {
                                "name": "Author",
                                "fields": [
                                    {"name": "name", "isRelation": False},
                                ],
                            },
                        ],
                    }
                ]
            }
            findings = scan_for_nplusone(str(root), index_shape)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].confidence, "high")

    def test_select_related_with_no_args_covers_all_fks(self) -> None:
        """``.select_related()`` (no args) follows every FK on the model —
        no findings for FK accesses.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "views.py",
                "from blog.models import Post\n"
                "def run():\n"
                "    posts = Post.objects.select_related().all()\n"
                "    for post in posts:\n"
                "        print(post.author.name)\n",
            )
            findings = scan_for_nplusone(str(root), BLOG_SCHEMA)
            self.assertEqual(findings, [])

    def test_bad_path_returns_empty(self) -> None:
        findings = scan_for_nplusone("/nonexistent/path/that/should/not/exist_zzz")
        self.assertEqual(findings, [])

    def test_scanner_directly_on_source(self) -> None:
        """The ``NPlusOneScanner`` class can be used on an already-parsed
        tree — useful when integrating into an existing AST pipeline.
        """
        import ast
        source = (
            "from blog.models import Post\n"
            "def run():\n"
            "    posts = Post.objects.all()\n"
            "    for post in posts:\n"
            "        print(post.author.name)\n"
        )
        tree = ast.parse(source)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "views.py"
            file_path.write_text(source, encoding="utf-8")
            scanner = NPlusOneScanner(file_path, root, BLOG_SCHEMA)
            scanner.visit(tree)
            self.assertEqual(len(scanner.findings), 1)
            self.assertIsInstance(scanner.findings[0], NPlusOneFinding)


class ReverseOneToOneTest(unittest.TestCase):
    """The reverse side of a OneToOneField is a single object, so
    ``select_related`` covers it — it must not be treated like a
    ``_set`` manager that only ``prefetch_related`` satisfies.
    """

    MODELS = (
        "from django.db import models\n"
        "\n"
        "class User(models.Model):\n"
        "    name = models.CharField(max_length=10)\n"
        "\n"
        "class Profile(models.Model):\n"
        "    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')\n"
        "    bio = models.TextField()\n"
        "\n"
        "class Account(models.Model):\n"
        "    user = models.OneToOneField(User, on_delete=models.CASCADE)\n"
        "    plan = models.TextField()\n"
    )

    def _scan(self, views: str) -> list[NPlusOneFinding]:
        from django_orm_lens.parser import scan_workspace

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "app" / "models.py", self.MODELS)
            _write(root / "app" / "views.py", views)
            return scan_for_nplusone(str(root), scan_workspace(str(root)))

    def test_select_related_covers_reverse_o2o(self) -> None:
        findings = self._scan(
            "def f():\n"
            "    for u in User.objects.select_related('profile'):\n"
            "        print(u.profile.bio)\n"
        )
        self.assertEqual(findings, [])

    def test_prefetch_related_still_covers_reverse_o2o(self) -> None:
        findings = self._scan(
            "def f():\n"
            "    for u in User.objects.prefetch_related('profile'):\n"
            "        print(u.profile.bio)\n"
        )
        self.assertEqual(findings, [])

    def test_missing_reverse_o2o_suggests_select_related(self) -> None:
        findings = self._scan(
            "def f():\n"
            "    for u in User.objects.all():\n"
            "        print(u.profile.bio)\n"
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].suggested_fix, '.select_related("profile")')

    def test_default_reverse_o2o_name_is_model_lower_not_set(self) -> None:
        findings = self._scan(
            "def f():\n"
            "    for u in User.objects.all():\n"
            "        print(u.account.plan)\n"
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].accessed, ["account"])
        self.assertEqual(findings[0].confidence, "high")


if __name__ == "__main__":
    unittest.main()
