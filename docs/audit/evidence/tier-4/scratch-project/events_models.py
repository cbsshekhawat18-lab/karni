"""events models, each on karni.models.BaseModel: `karni make model <Name>`."""

from django.conf import settings
from django.db import models
from karni.models import BaseModel


class Venue(BaseModel):
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Event(BaseModel):
    title = models.CharField(max_length=200)
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    venue = models.ForeignKey("Venue", on_delete=models.CASCADE)

    def __str__(self) -> str:
        return self.title


class Booking(BaseModel):
    event = models.ForeignKey("Event", on_delete=models.CASCADE)
    attendee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    quantity = models.IntegerField()
