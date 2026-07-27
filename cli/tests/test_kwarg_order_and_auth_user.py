"""Regression tests for two critical bugs surfaced in the v0.6 ultrareview:

1. ``_extract_related`` and siblings used a positional regex that assumed
   ``to=...`` was the first kwarg, so ``ForeignKey(on_delete=CASCADE,
   to='User')`` silently dropped the target reference or read ``on_delete``
   as the target. AST-based extractors are now kwarg-order-independent.

2. ``settings.AUTH_USER_MODEL`` references were split naively via
   ``related.split('.')[-1]``, which produced ``"AUTH_USER_MODEL"`` — a
   name no workspace model carries. Reverse-relation graphs, signal
   ``sender=`` resolution, and n+1 detection all lost User-model edges.
   ``resolve_related_tail`` + ``find_user_model`` normalise these to the
   workspace's actual User model name.
"""

from __future__ import annotations

import unittest

from django_orm_lens.models import (
    find_user_model,
    find_user_model_from_dict,
    resolve_related_tail,
)
from django_orm_lens.parser import (
    _extract_on_delete,
    _extract_related,
    _extract_related_name,
    _extract_through_model,
    parse_models_file,
)
from django_orm_lens.query_analyzer import _build_schema_from_index
from django_orm_lens.signals_parser import _resolve_sender

# ---------------------------------------------------------------------------
# Fix #1 — AST-based extractors are kwarg-order-independent
# ---------------------------------------------------------------------------


class ExtractRelatedKwargOrderTest(unittest.TestCase):
    def test_positional_first_arg(self) -> None:
        self.assertEqual(_extract_related("'User', on_delete=CASCADE)"), "User")

    def test_to_kwarg_first(self) -> None:
        self.assertEqual(
            _extract_related("to='User', on_delete=CASCADE)"), "User"
        )

    def test_to_kwarg_after_on_delete(self) -> None:
        # This is the bug: legacy regex read `on_delete` as the target.
        self.assertEqual(
            _extract_related("on_delete=models.CASCADE, to='User')"), "User"
        )

    def test_to_kwarg_after_multiple_others(self) -> None:
        self.assertEqual(
            _extract_related(
                "null=True, blank=True, on_delete=models.CASCADE, to='accounts.User')"
            ),
            "accounts.User",
        )

    def test_bare_name_target(self) -> None:
        self.assertEqual(_extract_related("Author, on_delete=CASCADE)"), "Author")

    def test_dotted_name_target(self) -> None:
        self.assertEqual(
            _extract_related("blog.Post, related_name='comments')"), "blog.Post"
        )

    def test_settings_auth_user_model_preserved(self) -> None:
        # We preserve the raw dotted reference — downstream resolves via
        # resolve_related_tail against the workspace User model.
        self.assertEqual(
            _extract_related("settings.AUTH_USER_MODEL, on_delete=CASCADE)"),
            "settings.AUTH_USER_MODEL",
        )

    def test_self_reference(self) -> None:
        self.assertEqual(
            _extract_related("'self', on_delete=CASCADE)"), "self"
        )

    def test_empty_args_returns_none(self) -> None:
        self.assertIsNone(_extract_related(")"))


class ExtractOnDeleteKwargOrderTest(unittest.TestCase):
    def test_on_delete_after_to(self) -> None:
        self.assertEqual(
            _extract_on_delete("to='User', on_delete=CASCADE)"), "CASCADE"
        )

    def test_on_delete_first(self) -> None:
        self.assertEqual(
            _extract_on_delete("on_delete=models.SET_NULL, to='User')"),
            "SET_NULL",
        )

    def test_on_delete_set_callable(self) -> None:
        # AST-based version returns "SET" for callable form, matching legacy.
        self.assertEqual(
            _extract_on_delete("to='User', on_delete=models.SET(get_default))"),
            "SET",
        )
        self.assertEqual(
            _extract_on_delete("on_delete=SET(0), to='X')"),
            "SET",
        )

    def test_absent_returns_none(self) -> None:
        self.assertIsNone(_extract_on_delete("null=True, blank=True)"))


class ExtractRelatedNameKwargOrderTest(unittest.TestCase):
    def test_related_name_last(self) -> None:
        self.assertEqual(
            _extract_related_name("'User', on_delete=CASCADE, related_name='posts')"),
            "posts",
        )

    def test_related_name_first(self) -> None:
        self.assertEqual(
            _extract_related_name("related_name='posts', to='User')"),
            "posts",
        )


class ExtractThroughModelKwargOrderTest(unittest.TestCase):
    def test_through_last(self) -> None:
        self.assertEqual(
            _extract_through_model("'Tag', through='BookTag')"),
            "BookTag",
        )

    def test_through_first(self) -> None:
        self.assertEqual(
            _extract_through_model("through='BookTag', to='Tag')"),
            "BookTag",
        )

    def test_through_dotted_symbol(self) -> None:
        self.assertEqual(
            _extract_through_model("'Tag', through=BookTag)"),
            "BookTag",
        )


class EndToEndReorderedKwargsTest(unittest.TestCase):
    """Full ``parse_models_file`` picks up related_model when kwargs are
    reordered — the class-level regression."""

    SAMPLE = '''
from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=100)


class Book(models.Model):
    author = models.ForeignKey(
        on_delete=models.CASCADE,
        related_name='books',
        to='Author',
    )
'''

    def test_related_model_resolved_when_to_is_last(self) -> None:
        models = parse_models_file("blog/models.py", self.SAMPLE)
        book = next(m for m in models if m.name == "Book")
        author_field = next(f for f in book.fields if f.name == "author")
        self.assertEqual(author_field.related_model, "Author")
        self.assertEqual(author_field.on_delete, "CASCADE")
        self.assertEqual(author_field.related_name, "books")


# ---------------------------------------------------------------------------
# Fix #2 — settings.AUTH_USER_MODEL resolves everywhere
# ---------------------------------------------------------------------------


class _StubField:
    def __init__(self, name, related_model, is_relation=True, related_name=None):
        self.name = name
        self.related_model = related_model
        self.is_relation = is_relation
        self.related_name = related_name
        self.relation_kind = "ForeignKey" if is_relation else None


class _StubModel:
    def __init__(self, name, base_classes=None, fields=None):
        self.name = name
        self.base_classes = base_classes or ["models.Model"]
        self.fields = fields or []


class _StubApp:
    def __init__(self, name, models):
        self.name = name
        self.models = models


class _StubIndex:
    def __init__(self, apps):
        self.apps = apps


class FindUserModelTest(unittest.TestCase):
    def test_abstract_user_subclass(self) -> None:
        user = _StubModel("User", ["AbstractUser"])
        idx = _StubIndex([_StubApp("accounts", [user])])
        self.assertIs(find_user_model(idx), user)

    def test_falls_back_to_named_user(self) -> None:
        user = _StubModel("User", ["models.Model"])
        idx = _StubIndex([_StubApp("core", [user])])
        self.assertIs(find_user_model(idx), user)

    def test_no_user_returns_none(self) -> None:
        idx = _StubIndex([_StubApp("blog", [_StubModel("Post")])])
        self.assertIsNone(find_user_model(idx))


class FindUserModelFromDictTest(unittest.TestCase):
    def test_abstract_user_subclass(self) -> None:
        payload = {
            "apps": [
                {
                    "name": "accounts",
                    "models": [
                        {"name": "User", "baseClasses": ["AbstractUser"]}
                    ],
                }
            ]
        }
        m = find_user_model_from_dict(payload)
        self.assertIsNotNone(m)
        self.assertEqual(m["name"], "User")

    def test_falls_back_to_named_user(self) -> None:
        payload = {
            "apps": [
                {
                    "name": "core",
                    "models": [
                        {"name": "User", "baseClasses": ["models.Model"]}
                    ],
                }
            ]
        }
        m = find_user_model_from_dict(payload)
        self.assertEqual(m["name"], "User")

    def test_no_user_returns_none(self) -> None:
        payload = {"apps": []}
        self.assertIsNone(find_user_model_from_dict(payload))


class ResolveRelatedTailTest(unittest.TestCase):
    def test_plain_name_returns_tail(self) -> None:
        self.assertEqual(resolve_related_tail("accounts.User", "User"), "User")

    def test_settings_auth_user_model_resolves(self) -> None:
        self.assertEqual(
            resolve_related_tail("settings.AUTH_USER_MODEL", "User"), "User"
        )

    def test_bare_auth_user_model_resolves(self) -> None:
        self.assertEqual(resolve_related_tail("AUTH_USER_MODEL", "User"), "User")

    def test_settings_auth_user_no_user_model_falls_through(self) -> None:
        # Preserve tail so callers can decide what to do.
        self.assertEqual(
            resolve_related_tail("settings.AUTH_USER_MODEL", None),
            "AUTH_USER_MODEL",
        )

    def test_none_passes_through(self) -> None:
        self.assertIsNone(resolve_related_tail(None, "User"))


class BuildSchemaFromIndexAuthUserTest(unittest.TestCase):
    """Reverse-relation edges pointing at ``settings.AUTH_USER_MODEL`` must
    land on the actual User model — used by the n+1 detector."""

    def test_reverse_relation_lands_on_user(self) -> None:
        user = _StubModel("User", ["AbstractUser"], fields=[])
        post_author = _StubField("author", "settings.AUTH_USER_MODEL")
        post_author.related_name = "posts"
        post = _StubModel(
            "Post",
            ["models.Model"],
            fields=[post_author],
        )
        idx = _StubIndex(
            [
                _StubApp("accounts", [user]),
                _StubApp("blog", [post]),
            ]
        )
        schema = _build_schema_from_index(idx)
        self.assertIn("User", schema)
        self.assertEqual(schema["User"].get("posts"), "reverse")

    def test_no_user_model_no_edge(self) -> None:
        post_author = _StubField("author", "settings.AUTH_USER_MODEL")
        post_author.related_name = "posts"
        post = _StubModel("Post", ["models.Model"], fields=[post_author])
        idx = _StubIndex([_StubApp("blog", [post])])
        schema = _build_schema_from_index(idx)
        # No User model → nothing to point at, edge silently dropped.
        self.assertNotIn("User", schema)


class ResolveSenderAuthUserTest(unittest.TestCase):
    """Signal receivers with ``sender='settings.AUTH_USER_MODEL'`` must
    resolve to the workspace's User model, not orphan out."""

    def test_settings_auth_user_resolves_to_user_model(self) -> None:
        model_index = {"User": "accounts.User", "Order": "shop.Order"}
        sender, note = _resolve_sender(
            "settings.AUTH_USER_MODEL", model_index, user_model_name="User"
        )
        self.assertEqual(sender, "accounts.User")
        self.assertIsNone(note)

    def test_no_user_model_orphans(self) -> None:
        model_index = {"Order": "shop.Order"}
        sender, note = _resolve_sender(
            "settings.AUTH_USER_MODEL", model_index, user_model_name=None
        )
        self.assertEqual(sender, "settings.AUTH_USER_MODEL")
        self.assertEqual(note, "sender model not found in workspace")

    def test_plain_sender_still_works(self) -> None:
        model_index = {"Order": "shop.Order"}
        sender, note = _resolve_sender("Order", model_index, user_model_name="User")
        self.assertEqual(sender, "shop.Order")
        self.assertIsNone(note)


if __name__ == "__main__":
    unittest.main()
