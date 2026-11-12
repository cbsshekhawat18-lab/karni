"""The course rules of karni.yaml: what students and instructors may send, and what is refused."""

import datetime as dt
from typing import Any

import pytest
from django.utils import timezone
from karni.testing.factories import create

from courses.models import Course, Enrolment, Lesson, LessonProgress

pytestmark = pytest.mark.django_db


def _code(response: Any, field: str) -> str:
    return str(response.json()[field][0])[:4]


def _course(instructor: Any = None, *, published: bool = True) -> Course:
    """A course with one lesson, published unless asked (publishing needs a lesson)."""
    course = create(Course, **({"instructor": instructor} if instructor else {}), published=False)
    create(Lesson, course=course, position=1)
    if published:
        course.published = True
        course.save()
    return course


def test_a_draft_is_seen_by_its_instructor_and_staff_only(client_as: Any) -> None:
    teacher = client_as("instructor")
    draft = _course(teacher.user, published=False)
    shown = _course()
    anonymous = client_as(None).get("/api/courses/").json()["results"]
    assert [row["id"] for row in anonymous] == [str(shown.pk)]
    assert client_as("student").get(f"/api/courses/{draft.pk}/").status_code == 404
    assert teacher.get(f"/api/courses/{draft.pk}/").status_code == 200
    assert client_as("staff").get(f"/api/courses/{draft.pk}/").status_code == 200


def test_publishing_needs_a_lesson(client_as: Any) -> None:
    teacher = client_as("instructor")
    empty = create(Course, instructor=teacher.user, published=False)
    refused = teacher.patch(f"/api/courses/{empty.pk}/", {"published": True}, format="json")
    assert refused.status_code == 400 and _code(refused, "published") == "E996"


def test_a_student_enrols_once_in_a_published_course_not_their_own(client_as: Any) -> None:
    student = client_as("student")
    draft = _course(published=False)
    hidden = student.post("/api/enrolments/", {"course": str(draft.pk)}, format="json")
    assert hidden.status_code == 400 and "course" in hidden.json()  # a draft is not visible
    staff = client_as("staff")  # staff see drafts, and still cannot enrol in one
    refused = staff.post("/api/enrolments/", {"course": str(draft.pk)}, format="json")
    assert refused.status_code == 400 and _code(refused, "course") == "E993"
    course = _course()
    assert student.post("/api/enrolments/", {"course": str(course.pk)}).status_code == 201
    twice = student.post("/api/enrolments/", {"course": str(course.pk)}, format="json")
    assert twice.status_code == 400 and _code(twice, "course") == "E991"
    teacher = client_as("instructor")
    own = _course(teacher.user)
    mine = teacher.post("/api/enrolments/", {"course": str(own.pk)}, format="json")
    assert mine.status_code == 400 and _code(mine, "course") == "E993"


def test_a_lesson_is_read_by_its_students_its_instructor_and_staff(client_as: Any) -> None:
    teacher = client_as("instructor")
    course = _course(teacher.user)
    lesson = Lesson.objects.get(course=course)
    student = client_as("student")
    assert student.get(f"/api/lessons/{lesson.pk}/").status_code == 404
    create(Enrolment, course=course, student=student.user)
    assert student.get(f"/api/lessons/{lesson.pk}/").status_code == 200
    assert teacher.get(f"/api/lessons/{lesson.pk}/").status_code == 200


def test_lessons_go_only_into_a_course_of_your_own(client_as: Any) -> None:
    lesson = {"title": "Extra", "body": "x", "position": 9}
    course = _course()
    student = client_as("student").post(
        "/api/lessons/", {**lesson, "course": str(course.pk)}, format="json"
    )
    assert student.status_code == 403 and student.json()["detail"].startswith("E134: ")
    other = client_as("instructor").post(
        "/api/lessons/", {**lesson, "course": str(course.pk)}, format="json"
    )
    assert other.status_code == 403
    owner = client_as("instructor", user=course.instructor).post(
        "/api/lessons/", {**lesson, "course": str(course.pk)}, format="json"
    )
    assert owner.status_code == 201, owner.content
    clash = client_as("instructor", user=course.instructor).post(
        "/api/lessons/", {**lesson, "course": str(course.pk)}, format="json"
    )
    assert clash.status_code == 400 and _code(clash, "course") == "E991"


def test_progress_is_once_per_lesson_of_the_course_and_not_ahead(client_as: Any) -> None:
    student = client_as("student")
    course, other = _course(), _course()
    enrolment = create(Enrolment, course=course, student=student.user)
    create(Enrolment, course=other, student=student.user)  # its lessons are readable too
    lesson = Lesson.objects.get(course=course)
    body = {"enrolment": str(enrolment.pk), "lesson": str(lesson.pk)}
    assert student.post("/api/lesson-progresses/", body, format="json").status_code == 201
    twice = student.post("/api/lesson-progresses/", body, format="json")
    assert twice.status_code == 400 and _code(twice, "enrolment") == "E991"
    foreign = {**body, "lesson": str(Lesson.objects.get(course=other).pk)}
    wrong = student.post("/api/lesson-progresses/", foreign, format="json")
    assert wrong.status_code == 400 and _code(wrong, "lesson") == "E993"
    LessonProgress.objects.all().delete()
    ahead = {**body, "completed_at": (timezone.now() + dt.timedelta(days=1000)).isoformat()}
    late = student.post("/api/lesson-progresses/", ahead, format="json")
    assert late.status_code == 400 and _code(late, "completed_at") == "E990"


def test_a_course_with_enrolments_is_not_deleted(client_as: Any) -> None:
    teacher = client_as("instructor")
    course = _course(teacher.user)
    create(Enrolment, course=course)
    refused = teacher.delete(f"/api/courses/{course.pk}/")
    assert refused.status_code == 409 and refused.json()["code"] == "E995"
