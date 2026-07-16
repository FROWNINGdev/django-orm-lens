"""Regression tests for v0.5.1 parser + MCP fixes.

Bugs closed here:
* #8  abstract=True filter — abstract mixins must NOT appear in results
* #9  transitive inheritance — subclasses of user-defined abstract mixins are models
* #10 settings.AUTH_USER_MODEL resolution in relation lookups (MCP layer)
"""

from __future__ import annotations

import unittest

from django_orm_lens.parser import parse_models_file
from django_orm_lens.mcp_server import (
    _rel_matches_target,
    _workspace_user_model,
)


SAMPLE = '''
from django.db import models
from django.contrib.auth.models import AbstractUser


class TimeStamped(models.Model):
    """Abstract mixin — must NOT appear as a concrete model."""
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class Trackable(TimeStamped):
    """Second-level abstract — also must NOT appear."""
    tracked_by = models.CharField(max_length=100, blank=True)

    class Meta:
        abstract = True


class User(AbstractUser, TimeStamped):
    email = models.EmailField(unique=True)


class Profile(TimeStamped):
    """Concrete subclass of a user-defined abstract mixin."""
    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
    )
    bio = models.TextField(blank=True)


class Order(Trackable):
    """Concrete subclass through a two-level abstract chain."""
    total = models.DecimalField(max_digits=10, decimal_places=2)


class SomethingElseAdmin(admin.ModelAdmin):
    """Not a model at all — must NOT appear."""
    pass
'''


class AbstractAndInheritanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.models = parse_models_file("accounts/models.py", SAMPLE)
        self.names = [m.name for m in self.models]

    def test_abstract_mixin_dropped(self):
        self.assertNotIn("TimeStamped", self.names)
        self.assertNotIn("Trackable", self.names)

    def test_concrete_direct_model_included(self):
        self.assertIn("User", self.names)

    def test_concrete_via_abstract_mixin_included(self):
        # BUG #9 — Profile inherits from TimeStamped (which extends models.Model);
        # transitive resolution must still recognize Profile as a model.
        self.assertIn("Profile", self.names)

    def test_concrete_via_two_level_abstract_chain(self):
        # Trackable -> TimeStamped -> models.Model.
        self.assertIn("Order", self.names)

    def test_admin_not_included(self):
        self.assertNotIn("SomethingElseAdmin", self.names)

    def test_profile_field_shape_preserved(self):
        profile = next(m for m in self.models if m.name == "Profile")
        rel_fields = [f for f in profile.fields if f.is_relation]
        self.assertEqual(len(rel_fields), 1)
        self.assertEqual(rel_fields[0].name, "user")
        self.assertEqual(rel_fields[0].relation_kind, "OneToOneField")


class _StubModel:
    def __init__(self, name, base_classes):
        self.name = name
        self.base_classes = base_classes


class _StubApp:
    def __init__(self, name, models):
        self.name = name
        self.models = models


class _StubIndex:
    def __init__(self, apps):
        self.apps = apps


class AuthUserResolutionTest(unittest.TestCase):
    def test_finds_abstract_user_subclass(self):
        user = _StubModel("User", ["AbstractUser"])
        idx = _StubIndex([_StubApp("accounts", [user])])
        app, m = _workspace_user_model(idx)
        self.assertEqual(app, "accounts")
        self.assertIs(m, user)

    def test_falls_back_to_named_user(self):
        user = _StubModel("User", ["models.Model"])
        idx = _StubIndex([_StubApp("core", [user])])
        app, m = _workspace_user_model(idx)
        self.assertEqual(app, "core")
        self.assertIs(m, user)

    def test_no_user_returns_none(self):
        other = _StubModel("Post", ["models.Model"])
        idx = _StubIndex([_StubApp("blog", [other])])
        app, m = _workspace_user_model(idx)
        self.assertIsNone(app)
        self.assertIsNone(m)

    def test_rel_match_plain_reference(self):
        user = _StubModel("User", ["AbstractUser"])
        self.assertTrue(_rel_matches_target("accounts.User", "User", user))
        self.assertTrue(_rel_matches_target("User", "User", user))

    def test_rel_match_settings_auth_user_model(self):
        user = _StubModel("User", ["AbstractUser"])
        self.assertTrue(
            _rel_matches_target("settings.AUTH_USER_MODEL", "User", user)
        )

    def test_rel_no_match_when_no_user_model(self):
        self.assertFalse(
            _rel_matches_target("settings.AUTH_USER_MODEL", "User", None)
        )

    def test_rel_no_match_wrong_target(self):
        user = _StubModel("User", ["AbstractUser"])
        self.assertFalse(_rel_matches_target("blog.Post", "User", user))


if __name__ == "__main__":
    unittest.main()
