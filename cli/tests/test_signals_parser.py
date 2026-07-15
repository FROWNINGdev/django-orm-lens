"""Tests for the static signal-graph parser (signal_graph).

The parser walks every ``.py`` file in the workspace via pure ``ast``,
matches ``@receiver(...)`` decorators and ``x = Signal(...)`` module-level
assignments, and returns the sender→signal→handler DAG plus custom
signal definitions and their ``.send()`` call-sites.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from django_orm_lens.signals_parser import signal_graph

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "miniapp"


def _copy_miniapp(dest: Path) -> None:
    for app in ("orders", "users"):
        shutil.copytree(FIXTURE_ROOT / app, dest / app)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class SignalGraphTest(unittest.TestCase):
    def test_receiver_post_save_with_sender_resolves_to_model(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            _write(
                root / "notifications" / "signals.py",
                "from django.db.models.signals import post_save\n"
                "from django.dispatch import receiver\n"
                "from orders.models import Order\n\n"
                "@receiver(post_save, sender=Order)\n"
                "def notify_order_saved(sender, instance, **kwargs):\n"
                "    pass\n",
            )

            result = signal_graph(str(root))

            self.assertEqual(len(result["edges"]), 1)
            edge = result["edges"][0]
            self.assertEqual(edge["signal"], "post_save")
            self.assertEqual(edge["sender"], "orders.Order")
            self.assertTrue(edge["handler"].endswith("notify_order_saved"))
            self.assertIn("notifications", edge["handler"])
            self.assertTrue(edge.get("builtin"))
            self.assertEqual(result["orphan_handlers"], [])

    def test_receiver_no_sender_gets_null_and_note(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            _write(
                root / "audit" / "signals.py",
                "from django.db.models.signals import pre_delete\n"
                "from django.dispatch import receiver\n\n"
                "@receiver(pre_delete)\n"
                "def log_deletion(sender, instance, **kwargs):\n"
                "    pass\n",
            )

            result = signal_graph(str(root))

            self.assertEqual(len(result["edges"]), 1)
            edge = result["edges"][0]
            self.assertEqual(edge["signal"], "pre_delete")
            self.assertIsNone(edge["sender"])
            self.assertEqual(edge["note"], "no sender = fires for all models")

    def test_orphan_handler_when_sender_missing_from_workspace(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            _write(
                root / "notifications" / "signals.py",
                "from django.db.models.signals import post_save\n"
                "from django.dispatch import receiver\n\n"
                "@receiver(post_save, sender=Ghost)\n"
                "def unused_handler(sender, instance, **kwargs):\n"
                "    pass\n",
            )

            result = signal_graph(str(root))

            self.assertEqual(len(result["edges"]), 1)
            edge = result["edges"][0]
            self.assertEqual(edge["sender"], "Ghost")
            self.assertEqual(edge["note"], "sender model not found in workspace")
            self.assertEqual(len(result["orphan_handlers"]), 1)
            self.assertIn("unused_handler", result["orphan_handlers"][0]["handler"])

    def test_custom_signal_definition_and_send(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            _write(
                root / "orders" / "signals.py",
                "from django.dispatch import Signal\n\n"
                "order_shipped = Signal()\n",
            )
            _write(
                root / "orders" / "services.py",
                "from orders.signals import order_shipped\n\n"
                "def ship(order):\n"
                "    order_shipped.send(sender=order.__class__, order=order)\n",
            )

            result = signal_graph(str(root))

            self.assertEqual(len(result["custom_signals"]), 1)
            sig = result["custom_signals"][0]
            self.assertEqual(sig["name"], "order_shipped")
            self.assertIn("orders.signals", sig["fqn"])
            self.assertTrue(sig["defined_in"].endswith("signals.py:3"))
            self.assertEqual(len(sig["sent_from"]), 1)
            self.assertTrue(sig["sent_from"][0].endswith("services.py:4"))

    def test_receiver_string_sender_resolves(self) -> None:
        """``sender="Order"`` string reference also resolves via the model index."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_miniapp(root)
            _write(
                root / "notifications" / "signals.py",
                "from django.db.models.signals import post_save\n"
                "from django.dispatch import receiver\n\n"
                "@receiver(post_save, sender='Order')\n"
                "def h(sender, instance, **kwargs):\n"
                "    pass\n",
            )
            result = signal_graph(str(root))
            self.assertEqual(result["edges"][0]["sender"], "orders.Order")


if __name__ == "__main__":
    unittest.main()
