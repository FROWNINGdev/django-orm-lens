from django.db import models


class Order(models.Model):
    reference = models.CharField(max_length=32)
    customer = models.ForeignKey("auth.User", on_delete=models.CASCADE)
