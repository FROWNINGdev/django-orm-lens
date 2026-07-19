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


if __name__ == "__main__":
    unittest.main()
