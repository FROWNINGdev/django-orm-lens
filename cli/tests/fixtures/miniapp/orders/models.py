from django.db import models


class Order(models.Model):
    user = models.ForeignKey("users.User", on_delete=models.CASCADE)
    status = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user"])]


class LineItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    sku = models.CharField(max_length=64)
    quantity = models.PositiveIntegerField(default=1)
