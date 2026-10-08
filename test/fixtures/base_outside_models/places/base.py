from django.db import models


class Located(models.Model):
    lat = models.FloatField()
    lng = models.FloatField()
