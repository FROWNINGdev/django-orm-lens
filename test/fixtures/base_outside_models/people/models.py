from django.db import models

from core import base as core_base
from core.base import (
    MyCustomModel,
    NotAModel,  # a plain class, must not turn its subclass into a model
)
from core.db import SoftDeletable


class Person(MyCustomModel):
    name = models.CharField(max_length=50)


class Archive(SoftDeletable):
    title = models.CharField(max_length=100)


class Note(core_base.MyCustomModel):
    text = models.TextField()


class Plain(NotAModel):
    pass
