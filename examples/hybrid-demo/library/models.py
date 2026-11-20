"""library models, each on karni.models.BaseModel: `karni make model <Name>`."""

from django.conf import settings
from django.db import models
from karni.models import BaseModel


class Book(BaseModel):
    title = models.CharField(max_length=200)
    author = models.CharField(max_length=200)
    finished = models.BooleanField(default=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    def __str__(self) -> str:
        return self.title
