"""crm models. Each class extends the one karni build writes in crm/karni/models.py
from karni.yaml: add your methods here.
"""

from crm.karni import models as karni
from django.core.exceptions import ValidationError


class Company(karni.Company):
    """A company. Its name is unique."""

    def clean(self) -> None:
        taken = Company.objects.filter(name__iexact=self.name).exclude(pk=self.pk)
        if self.name and taken.exists():
            raise ValidationError({"name": "A company with this name exists."})


class Contact(karni.Contact):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class Deal(karni.Deal):
    """A deal in the pipeline. The stage moves only through ``transition``."""

    class APIMeta:
        read_only = ["stage", "owner"]

    def clean(self) -> None:
        if self.value is not None and self.value < 0:
            raise ValidationError({"value": "The value is not negative."})
