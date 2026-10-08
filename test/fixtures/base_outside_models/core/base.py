from django.db import models


class MyCustomModel(models.Model):
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class NotAModel:
    pass
