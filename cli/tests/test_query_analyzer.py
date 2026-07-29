"""Tests for the static QuerySet usage analyzer (suggest_indexes).

The analyzer walks every ``.py`` file in the workspace via pure ``ast``,
matches ``<Model>.objects.<qs_method>(...)`` calls, and proposes
``Meta.indexes`` entries from field-usage frequency. These tests build
synthetic Django-shaped workspaces inside ``tmp_path`` and assert the
returned shape.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from django_orm_lens.query_analyzer import suggest_indexes

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "miniapp"


def _copy_miniapp(dest: Path) -> None:
    """Copy the fixture miniapp into a fresh workspace root."""
    for app in ("orders", "users"):
        shutil.copytree(FIXTURE_ROOT / app, dest / app)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class SuggestIndexesTest(unittest.TestCase):
    def test_single_field_filter_proposes_single_index(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            _write(
                root / "views" / "dashboard.py",
                "from orders.models import Order\n"
                "def a():\n"
                "    return Order.objects.filter(status='paid')\n"
                "def b():\n"
                "    return Order.objects.filter(status='shipped')\n",
            )

            result = suggest_indexes("orders", "Order", str(root))

            self.assertEqual(result["target"], "orders.Order")
            fields = [u["field"] for u in result["filter_usages"] if not u.get("composite")]
            self.assertIn("status", fields)
            proposed_fieldsets = [p["fields"] for p in result["proposed_indexes"]]
            self.assertIn(["status"], proposed_fieldsets)
            # user is already in Meta.indexes → don't propose it again
            self.assertNotIn(["user"], proposed_fieldsets)
            self.assertEqual(result["existing_meta_indexes"], [["user"]])

    def test_chained_filter_counts_as_composite(self) -> None:
        """``.filter(user=x).filter(status=y)`` produces two filter sites, one
        per call. Because they're in *separate* calls they are NOT treated as
        composite — composites require field co-occurrence in one call.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            _write(
                root / "views" / "dashboard.py",
                "from orders.models import Order\n"
                "def q():\n"
                "    return Order.objects.filter(user=1).filter(status='paid')\n"
                "def q2():\n"
                "    return Order.objects.filter(user=2).filter(status='shipped')\n",
            )

            result = suggest_indexes("orders", "Order", str(root))

            singles = {u["field"]: u["sites"] for u in result["filter_usages"] if not u.get("composite")}
            # 2 chained filter calls in each of 2 functions = 2 sites each field
            self.assertEqual(singles.get("user"), 2)
            self.assertEqual(singles.get("status"), 2)
            composites = [u for u in result["filter_usages"] if u.get("composite")]
            self.assertEqual(composites, [])

    def test_composite_filter_call_is_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            _write(
                root / "views" / "dashboard.py",
                "from orders.models import Order\n"
                "def a():\n"
                "    return Order.objects.filter(user=1, status='paid')\n"
                "def b():\n"
                "    return Order.objects.filter(user=2, status='shipped')\n",
            )

            result = suggest_indexes("orders", "Order", str(root))

            composites = [u for u in result["filter_usages"] if u.get("composite")]
            self.assertEqual(len(composites), 1)
            self.assertEqual(composites[0]["field"], ["status", "user"])
            self.assertEqual(composites[0]["sites"], 2)
            proposed_fieldsets = [p["fields"] for p in result["proposed_indexes"]]
            self.assertIn(["status", "user"], proposed_fieldsets)

    def test_order_by_and_lookup_stripping(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            _write(
                root / "views" / "list_view.py",
                "from orders.models import Order\n"
                "def a():\n"
                "    return Order.objects.filter(user__email='x').order_by('-created_at')\n"
                "def b():\n"
                "    return Order.objects.order_by('-created_at')\n",
            )

            result = suggest_indexes("orders", "Order", str(root))

            singles = {u["field"]: u["sites"] for u in result["filter_usages"] if not u.get("composite")}
            # user__email → root field 'user' (Meta already indexes it)
            self.assertEqual(singles.get("user"), 1)
            order_by = {u["field"]: u["sites"] for u in result["order_by_usages"]}
            self.assertEqual(order_by.get("-created_at"), 2)
            proposed_fieldsets = [p["fields"] for p in result["proposed_indexes"]]
            self.assertIn(["-created_at"], proposed_fieldsets)

    def test_advanced_flag_on_q_expression(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            _write(
                root / "managers.py",
                "from django.db.models import Q\n"
                "from orders.models import Order\n"
                "def q():\n"
                "    return Order.objects.filter(Q(status='paid') | Q(status='shipped'))\n",
            )

            result = suggest_indexes("orders", "Order", str(root))

            # The Q() expression is opaque — analyzer records the site with
            # advanced=True and no field name. No index proposal from it.
            # Only the user index (from Meta) exists → no new proposals.
            self.assertEqual(result["existing_meta_indexes"], [["user"]])

    def test_missing_model_returns_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            result = suggest_indexes("orders", "NoSuchModel", str(root))
            self.assertEqual(result["target"], "orders.NoSuchModel")
            self.assertEqual(result["error"], "model not found in workspace")

    def test_get_call_is_captured(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            _write(
                root / "api.py",
                "from orders.models import Order\n"
                "def get_one(pk):\n"
                "    return Order.objects.get(pk=pk)\n"
                "def get_two(pk):\n"
                "    return Order.objects.get(pk=pk)\n",
            )

            result = suggest_indexes("orders", "Order", str(root))
            # get sites feed into the filter/exclude/get pool for indexing
            fields = {u["field"]: u["sites"] for u in result["filter_usages"] if not u.get("composite")}
            self.assertEqual(fields.get("pk"), 2)

    def test_pk_and_id_not_proposed(self) -> None:
        """Filtering on pk/id should never generate a proposal — it's the PK."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            _write(
                root / "api.py",
                "from orders.models import Order\n"
                "def a(): return Order.objects.filter(pk=1)\n"
                "def b(): return Order.objects.filter(pk=2)\n"
                "def c(): return Order.objects.filter(id=3)\n"
                "def d(): return Order.objects.filter(id=4)\n",
            )

            result = suggest_indexes("orders", "Order", str(root))
            proposed = [p["fields"] for p in result["proposed_indexes"]]
            self.assertNotIn(["pk"], proposed)
            self.assertNotIn(["id"], proposed)

    def test_db_index_true_field_not_proposed(self) -> None:
        """Fields with db_index=True already have a DB index — no proposal."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "myapp" / "__init__.py", ""
            )
            _write(
                root / "myapp" / "models.py",
                "from django.db import models\n\n"
                "class Widget(models.Model):\n"
                "    code = models.CharField(max_length=32, db_index=True)\n"
                "    name = models.CharField(max_length=64)\n",
            )
            _write(
                root / "views.py",
                "from myapp.models import Widget\n"
                "def a(): return Widget.objects.filter(code='x')\n"
                "def b(): return Widget.objects.filter(code='y')\n",
            )

            result = suggest_indexes("myapp", "Widget", str(root))
            proposed = [p["fields"] for p in result["proposed_indexes"]]
            self.assertNotIn(["code"], proposed)

    def test_unique_field_not_proposed(self) -> None:
        """Fields declared unique=True carry an implicit index."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "shop" / "__init__.py", "")
            _write(
                root / "shop" / "models.py",
                "from django.db import models\n\n"
                "class Product(models.Model):\n"
                "    sku = models.CharField(max_length=32, unique=True)\n",
            )
            _write(
                root / "views.py",
                "from shop.models import Product\n"
                "def a(): return Product.objects.filter(sku='A1')\n"
                "def b(): return Product.objects.filter(sku='A2')\n",
            )

            result = suggest_indexes("shop", "Product", str(root))
            proposed = [p["fields"] for p in result["proposed_indexes"]]
            self.assertNotIn(["sku"], proposed)

    def test_unique_constraint_not_proposed(self) -> None:
        """UniqueConstraint in Meta.constraints implies a DB index — skip it."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "inventory" / "__init__.py", "")
            _write(
                root / "inventory" / "models.py",
                "from django.db import models\n\n"
                "class Stock(models.Model):\n"
                "    warehouse = models.CharField(max_length=32)\n"
                "    product = models.CharField(max_length=32)\n\n"
                "    class Meta:\n"
                "        constraints = [\n"
                "            models.UniqueConstraint(\n"
                "                fields=['warehouse', 'product'], name='uc_stock'\n"
                "            )\n"
                "        ]\n",
            )
            _write(
                root / "views.py",
                "from inventory.models import Stock\n"
                "def a(): return Stock.objects.filter(warehouse='A', product='X')\n"
                "def b(): return Stock.objects.filter(warehouse='B', product='Y')\n",
            )

            result = suggest_indexes("inventory", "Stock", str(root))
            proposed = [p["fields"] for p in result["proposed_indexes"]]
            self.assertNotIn(["product", "warehouse"], proposed)
            self.assertNotIn(["warehouse", "product"], proposed)


if __name__ == "__main__":
    unittest.main()
