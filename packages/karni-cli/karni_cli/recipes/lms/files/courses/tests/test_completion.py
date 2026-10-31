"""The course rule: a student's completion is the share of the lessons they did."""

from typing import Any

import pytest
from django.utils import timezone
from karni.testing.factories import create

from courses.models import Course, Enrolment, Lesson, LessonProgress

pytestmark = pytest.mark.django_db


def test_completion_counts_the_lessons_of_the_course_the_student_did(
    client_as: Any,
) -> None:
    client = client_as("student")
    course = create(Course)
    lessons = [create(Lesson, course=course, position=n) for n in range(1, 5)]
    enrolment = create(Enrolment, course=course, student=client.user)
    assert course.completion(client.user) == 0
    for lesson in lessons[:3]:
        create(
            LessonProgress,
            enrolment=enrolment,
            lesson=lesson,
            completed_at=timezone.now(),
        )
    create(
        LessonProgress, enrolment=enrolment, lesson=lessons[3], completed_at=None
    )  # started
    create(
        LessonProgress,
        enrolment=enrolment,
        lesson=create(Lesson),
        completed_at=timezone.now(),
    )
    assert course.completion(client.user) == 75
    response = client.get(f"/api/enrolments/{enrolment.pk}/progress/")
    assert response.status_code == 200 and response.json() == {"percent": 75}


def test_a_course_without_lessons_is_not_started() -> None:
    enrolment = create(Enrolment)
    assert enrolment.course.completion(enrolment.student) == 0
