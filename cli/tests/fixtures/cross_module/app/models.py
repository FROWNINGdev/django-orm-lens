from django.db import models

from common.models import TimeStampedModel


class Article(TimeStampedModel):
    """Concrete model whose base is defined in a different scanned module."""

    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
