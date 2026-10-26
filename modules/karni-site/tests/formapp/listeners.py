from __future__ import annotations

from karni.events import on_created

from karni_site.notify import notify_recipients
from tests.formapp.models import AppointmentRequest


@on_created(AppointmentRequest, queued=True)
def notify_appointment(request: AppointmentRequest) -> None:
    notify_recipients(
        request,
        setting="APPOINTMENT_RECIPIENTS",
        template="formapp/email/appointment",
        reply_to=request.email,
    )
