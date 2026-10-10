from karni.api.serializers import KarniModelSerializer
from rest_framework.exceptions import ValidationError

from events.models import Booking, Event


# karni: allow(redundant-serializer): capacity rule: quantity must not exceed the tier's remaining seats
class BookingSerializer(KarniModelSerializer):
    class Meta:
        model = Booking
        fields = (
            "id",
            "event",
            "tier",
            "attendee",
            "quantity",
            "status",
            "payment",
            "confirmed_at",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        )
        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "attendee",
            "status",
            "payment",
            "confirmed_at",
        )

    def validate(self, attrs):
        current = self.instance
        event = attrs.get("event", getattr(current, "event", None))
        tier = attrs.get("tier", getattr(current, "tier", None))
        quantity = attrs.get("quantity", getattr(current, "quantity", 0))
        if event is not None and event.status != Event.Status.PUBLISHED:
            raise ValidationError({"event": ["Only published events can be booked."]})
        if tier is not None and event is not None and tier.event_id != event.pk:
            raise ValidationError({"tier": ["This ticket tier belongs to another event."]})
        if tier is not None:
            held = quantity if current is not None and current.tier_id == tier.pk else 0
            if quantity < 1:
                raise ValidationError({"quantity": ["Book at least one ticket."]})
            if quantity > tier.remaining + held:
                raise ValidationError(
                    {"quantity": [f"Only {tier.remaining} seats left in {tier.name}."]}
                )
        return attrs
