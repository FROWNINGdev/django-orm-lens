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


if __name__ == "__main__":
    unittest.main()
