"""Cross-function N+1 resolution — `for p in recent():` and friends.

Until this landed the detector gave up whenever the loop source was a call
rather than an inline chain or a local variable, which is how a large share of
real Django code is written: the queryset is built in a helper or in
`get_queryset()`, and the loop lives somewhere else.

The suppression cases matter as much as the detections. A false positive on a
queryset the author already fixed is worse than a miss — it teaches people to
ignore the tool.

Run: python -m unittest discover cli/tests -v
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from django_orm_lens.query_analyzer import (
    NPlusOneScanner,
    _helper_call_name,
    _ReturnedQuerySetTracker,
)

ROOT = Path("/proj")
FILE = ROOT / "blog" / "views.py"


def scan(src: str) -> list:
    scanner = NPlusOneScanner(FILE, ROOT)
    scanner.visit(ast.parse(src))
    return scanner.findings


def helpers(src: str) -> dict:
    tracker = _ReturnedQuerySetTracker()
    tracker.visit(ast.parse(src))
    return {name: model for name, (_chain, model) in tracker.returns.items()}


class HelperCallNameTest(unittest.TestCase):
    def _name(self, expr: str) -> tuple[str | None, bool]:
        return _helper_call_name(ast.parse(expr, mode="eval").body)

    def test_bare_call_is_not_part_of_the_chain(self) -> None:
        self.assertEqual(self._name("recent()"), ("recent", False))
        self.assertEqual(self._name("recent().select_related('a')"), ("recent", False))

    def test_self_method_is_part_of_the_chain(self) -> None:
        self.assertEqual(self._name("self.get_queryset()"), ("get_queryset", True))
        self.assertEqual(self._name("cls.build()"), ("build", True))

    def test_model_rooted_chain_is_not_a_helper(self) -> None:
        self.assertEqual(self._name("Post.objects.filter(x=1)"), (None, False))
        self.assertEqual(self._name("Post.objects.all()"), (None, False))


class ReturnTrackerTest(unittest.TestCase):
    def test_direct_return_of_a_chain(self) -> None:
        found = helpers("def recent():\n    return Post.objects.filter(a=1)\n")
        self.assertEqual(found, {"recent": "Post"})

    def test_return_of_a_local_binding(self) -> None:
        found = helpers("def built():\n    qs = Post.objects.all()\n    return qs\n")
        self.assertEqual(found, {"built": "Post"})

    def test_return_inside_a_conditional_is_seen(self) -> None:
        src = (
            "def maybe(flag):\n"
            "    if flag:\n"
            "        return Post.objects.filter(a=1)\n"
            "    return Post.objects.none()\n"
        )
        self.assertEqual(helpers(src), {"maybe": "Post"})

    def test_non_queryset_return_is_ignored(self) -> None:
        self.assertEqual(helpers("def n():\n    return 42\n"), {})
        self.assertEqual(helpers("def n():\n    return [1, 2]\n"), {})

    def test_nested_function_return_is_not_attributed_to_the_outer(self) -> None:
        # ast.walk would hand the inner return to `outer` and quietly make it
        # look like a queryset factory.
        src = (
            "def outer():\n"
            "    def inner():\n"
            "        return Post.objects.all()\n"
            "    return inner\n"
        )
        found = helpers(src)
        self.assertNotIn("outer", found)
        self.assertIn("inner", found)


class CrossFunctionScanTest(unittest.TestCase):
    def test_flags_a_loop_over_a_helper_call(self) -> None:
        src = (
            "def recent():\n"
            "    return Post.objects.filter(published=True)\n"
            "\n"
            "def report():\n"
            "    for post in recent():\n"
            "        print(post.author.name)\n"
        )
        found = scan(src)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].loop_var, "post")
        self.assertIn("select_related", found[0].suggested_fix)

    def test_flags_a_loop_over_self_get_queryset(self) -> None:
        src = (
            "class PostView:\n"
            "    def get_queryset(self):\n"
            "        return Post.objects.all()\n"
            "\n"
            "    def render(self):\n"
            "        for post in self.get_queryset():\n"
            "            print(post.author.name)\n"
        )
        self.assertEqual(len(scan(src)), 1)

    def test_helper_that_returns_a_local_binding(self) -> None:
        src = (
            "def built():\n"
            "    qs = Post.objects.all()\n"
            "    return qs\n"
            "\n"
            "def report():\n"
            "    for post in built():\n"
            "        print(post.author.name)\n"
        )
        self.assertEqual(len(scan(src)), 1)

    def test_helper_defined_after_its_caller_is_still_resolved(self) -> None:
        # Textual order must not decide what the scanner can see.
        src = (
            "def report():\n"
            "    for post in recent():\n"
            "        print(post.author.name)\n"
            "\n"
            "def recent():\n"
            "    return Post.objects.all()\n"
        )
        self.assertEqual(len(scan(src)), 1)


class SuppressionTest(unittest.TestCase):
    """A fix applied on either side of the call must silence the finding."""

    def test_select_related_inside_the_helper(self) -> None:
        src = (
            "def safe():\n"
            "    return Post.objects.all().select_related('author')\n"
            "\n"
            "def report():\n"
            "    for post in safe():\n"
            "        print(post.author.name)\n"
        )
        self.assertEqual(scan(src), [])

    def test_select_related_added_by_the_caller(self) -> None:
        src = (
            "def recent():\n"
            "    return Post.objects.all()\n"
            "\n"
            "def report():\n"
            "    for post in recent().select_related('author'):\n"
            "        print(post.author.name)\n"
        )
        self.assertEqual(scan(src), [])

    def test_prefetch_related_on_a_reverse_manager(self) -> None:
        src = (
            "def recent():\n"
            "    return Post.objects.all().prefetch_related('comment_set')\n"
            "\n"
            "def report():\n"
            "    for post in recent():\n"
            "        print(post.comment_set.all())\n"
        )
        self.assertEqual(scan(src), [])

    def test_unknown_callable_is_not_guessed_at(self) -> None:
        # No helper of that name in the module — stay quiet rather than
        # invent a model.
        src = (
            "def report():\n"
            "    for post in fetch_from_cache():\n"
            "        print(post.author.name)\n"
        )
        self.assertEqual(scan(src), [])

    def test_helper_returning_a_plain_list_is_not_flagged(self) -> None:
        src = (
            "def items():\n"
            "    return [1, 2, 3]\n"
            "\n"
            "def report():\n"
            "    for post in items():\n"
            "        print(post.author.name)\n"
        )
        self.assertEqual(scan(src), [])


if __name__ == "__main__":
    unittest.main()
