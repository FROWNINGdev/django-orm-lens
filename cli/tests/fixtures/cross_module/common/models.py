from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base shared across apps — must NOT appear as a concrete model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
