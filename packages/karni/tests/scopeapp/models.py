"""Plain ``BaseModel``\\ s for ``tests/test_scopes.py``.

Nothing here knows about the test-only ``tenant`` scope beyond a ``tenant``
column (``karni-tenancy`` will contribute that column itself). The scope is
registered from outside, the way an installed module registers one:

* ``Project`` → ``Task`` (FK, ``related_name="tasks"``);
* ``Task`` ↔ ``Topic`` (M2M, ``related_name="tasks"``);
* ``Country`` — global reference data, ``ScopeMeta.tenant = "shared"``.
"""

from __future__ import annotations

from django.db import models

from karni.models import BaseModel


class Project(BaseModel):
    tenant = models.CharField(max_length=20)
    name = models.CharField(max_length=50)

    def __str__(self) -> str:
        return self.name


class Topic(BaseModel):
    tenant = models.CharField(max_length=20)
    name = models.CharField(max_length=50)

    def __str__(self) -> str:
        return self.name


class Task(BaseModel):
    tenant = models.CharField(max_length=20)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=50)
    topics = models.ManyToManyField(Topic, blank=True, related_name="tasks")

    def __str__(self) -> str:
        return self.title


class Country(BaseModel):
    """Global reference data: opted out of the tenant scope (ruling Q1.6)."""

    name = models.CharField(max_length=50)

    class ScopeMeta:
        tenant = "shared"

    def __str__(self) -> str:
        return self.name
