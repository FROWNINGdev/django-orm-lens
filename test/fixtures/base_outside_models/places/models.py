from django.db import models

from .base import Located


class City(Located):
    name = models.CharField(max_length=80)
