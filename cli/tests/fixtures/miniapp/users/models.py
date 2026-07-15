from django.db import models


class User(models.Model):
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
