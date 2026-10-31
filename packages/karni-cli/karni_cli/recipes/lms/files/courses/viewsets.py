"""courses API. Each viewset extends the one karni build writes in courses/karni/api.py from
karni.yaml: add your actions here.
"""

from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from courses.karni import api as karni


class CourseViewSet(karni.CourseViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class LessonViewSet(karni.LessonViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class EnrolmentViewSet(karni.EnrolmentViewSet):
    """Enrolments, and how far each student is in the course."""

    @action(detail=True)
    def progress(self, request: Request, pk: str | None = None) -> Response:
        """The enrolled student's completion of the course, in percent."""
        enrolment = self.get_object()
        return Response({"percent": enrolment.course.completion(enrolment.student)})


class LessonProgressViewSet(karni.LessonProgressViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""
