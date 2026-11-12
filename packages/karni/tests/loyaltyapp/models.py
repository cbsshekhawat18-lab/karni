"""A loyalty card per person, and the visits that earn points."""

from __future__ import annotations

from django.db import models

from karni.models import BaseModel


class LoyaltyCard(BaseModel):
    """The part's profile of a person: one card each, with points."""

    person = models.OneToOneField(
        "people.Person", on_delete=models.CASCADE, related_name="loyalty_card"
    )
    points = models.PositiveIntegerField(default=0)
    nickname = models.CharField(max_length=60, blank=True, default="")

    class Meta(BaseModel.Meta):
        app_label = "loyaltyapp"


class Visit(BaseModel):
    """One visit of a person, and what they spent."""

    person = models.ForeignKey(
        "people.Person", on_delete=models.PROTECT, related_name="club_visits"
    )
    visited_on = models.DateField()
    spent = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta(BaseModel.Meta):
        app_label = "loyaltyapp"
