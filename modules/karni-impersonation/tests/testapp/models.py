from __future__ import annotations

from django.db import models
from karni.models import BaseModel


class Note(BaseModel):
    """Customer data: owned, audited."""

    text = models.CharField(max_length=200)

    class Karni:
        audit = True

    def __str__(self) -> str:
        return self.text


class Secret(BaseModel):
    """Only finance may view these — a grant support does not hold."""

    text = models.CharField(max_length=200)

    def __str__(self) -> str:
        return self.text
