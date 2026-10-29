from __future__ import annotations

from karni.api import Access, Authenticated, BaseViewSet, HasRole, Public

from tests.formapp.models import Application, AppointmentRequest, Feedback, Subscriber


class AppointmentRequestViewSet(BaseViewSet):
    model = AppointmentRequest
    access = Access(read=HasRole("staff"), write=HasRole("staff"), create=Public())


class SubscriberViewSet(BaseViewSet):
    model = Subscriber
    access = Access(read=HasRole("staff"), write=HasRole("staff"), create=Public())


class ApplicationViewSet(BaseViewSet):
    model = Application
    access = Access(read=HasRole("staff"), write=HasRole("staff"), create=Public())


class FeedbackViewSet(BaseViewSet):
    model = Feedback
    access = Access(read=HasRole("staff"), write=HasRole("staff"), create=Authenticated())
