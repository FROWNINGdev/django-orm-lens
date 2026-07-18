from django.db import models


class TimeStampBase(models.Model):
    """Abstract base shared across apps — must NOT appear as a concrete model.

    Deliberately NOT named ``TimeStampedModel``: that exact tail is one of
    the hardcoded heuristic names in ``_looks_like_model`` (parser.py), so a
    class inheriting it would be recognized as a model by name alone,
    without needing any base-resolution at all — masking the cross-module
    bug this fixture exists to catch (issue #20).
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
