from django.db import models


class AppSetting(models.Model):
    key = models.CharField(max_length=60, primary_key=True)
    value = models.CharField(max_length=250)
