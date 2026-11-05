"""courses models. Each class extends the one karni build writes in
courses/karni/models.py from karni.yaml: add your methods here.
"""

from typing import Any

from courses.karni import models as karni


class Course(karni.Course):
    """A course: its lessons in order, and how far each student is."""

    def completion(self, student: Any) -> int:
        """The share of the lessons the student completed, as a whole percent."""
        lessons = self.lesson_set.count()
        if not lessons:
            return 0
        done = (
            LessonProgress.objects.filter(
                enrolment__course=self,
                enrolment__student=student,
                lesson__course=self,
                completed_at__isnull=False,
            )
            .values("lesson")
            .distinct()
            .count()
        )
        return round(100 * done / lessons)


class Lesson(karni.Lesson):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class Enrolment(karni.Enrolment):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class LessonProgress(karni.LessonProgress):
    """The base class comes from karni.yaml (karni build). Add your own code here."""
