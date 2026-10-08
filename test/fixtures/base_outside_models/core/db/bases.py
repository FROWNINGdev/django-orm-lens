from django.db import models

from core.base import MyCustomModel


class SoftDeletable(MyCustomModel):
    deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True
