"""courses demo data for karni seed. Each seeder extends the one karni build writes in
courses/karni/seeds.py: steer a field's values here.
"""

from typing import Any

import factory
from django.utils import timezone
from karni.seeding import SeedContext

from courses.karni import seeds as karni
from courses.models import Enrolment


class CourseSeeder(karni.CourseSeeder):
    """Courses open to students."""

    published = True


class LessonSeeder(karni.LessonSeeder):
    """Lessons numbered from 1 in each course."""

    position = factory.Sequence(lambda n: n % 6 + 1)


class EnrolmentSeeder(karni.EnrolmentSeeder):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class LessonProgressSeeder(karni.LessonProgressSeeder):
    """Each student has done the first lessons of their own course, some more than others."""

    def seed(self, context: SeedContext) -> list[Any]:
        rows: list[Any] = []
        for enrolment in Enrolment.objects.select_related("course"):
            lessons = list(enrolment.course.lesson_set.order_by("position"))
            for lesson in lessons[: context.random.randint(0, len(lessons))]:
                rows += context.create(
                    1, enrolment=enrolment, lesson=lesson, completed_at=timezone.now()
                )
        return rows
