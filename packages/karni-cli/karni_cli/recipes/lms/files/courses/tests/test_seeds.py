"""The demo data karni seed writes: real-sounding, and the same on every run."""

import datetime as dt
import re
from typing import Any

import pytest
from django.apps import apps
from karni.seeding import seed, seeders

from courses.models import Course, Enrolment, Lesson, LessonProgress
from courses.seeds import COURSES

pytestmark = pytest.mark.django_db

NOW = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)


def snapshot(app: str) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every model of the app, but for the times a save stamps."""
    found: dict[str, list[tuple[Any, ...]]] = {}
    for model in apps.get_app_config(app).get_models():
        names = [
            field.attname
            for field in model._meta.concrete_fields
            if not getattr(field, "auto_now", False)
            and not getattr(field, "auto_now_add", False)
        ]
        rows = model._base_manager.values_list(*names)
        found[model.__name__] = sorted(tuple(map(str, row)) for row in rows)
    return found


def without_round(name: str) -> str:
    """A name without the number a repeat is tagged with (Name 2)."""
    return re.sub(r" \d+$", "", name)


def test_the_same_seed_gives_the_same_rows_and_the_yaml_counts() -> None:
    seed(seed=7, now=NOW, reset=True)
    first = snapshot("courses")
    for model in (Course, Lesson, Enrolment, LessonProgress):
        assert model.objects.count() == seeders()[model].row_count(10)
    seed(seed=7, now=NOW, reset=True)
    assert snapshot("courses") == first
    seed(seed=8, now=NOW, reset=True)
    assert snapshot("courses") != first


def test_lessons_belong_to_their_course_in_order_and_progress_is_a_prefix() -> None:
    seed(seed=3, now=NOW, reset=True)
    subjects = {subject.title: subject for subject in COURSES}
    assert set(Course.objects.values_list("title", flat=True)) <= set(subjects)
    for lesson in Lesson.objects.select_related("course"):
        wanted = subjects[lesson.course.title].lessons[lesson.position - 1]
        assert (lesson.title, lesson.body) == wanted
    for enrolment in Enrolment.objects.all():
        done = LessonProgress.objects.filter(enrolment=enrolment).select_related(
            "lesson"
        )
        positions = sorted(row.lesson.position for row in done)
        assert positions == list(range(1, len(positions) + 1))
        assert all(row.lesson.course_id == enrolment.course_id for row in done)
        assert all(row.completed_at < NOW for row in done)


def test_a_larger_count_repeats_titles_with_a_number_and_never_clashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seeders()[Course].Meta, "count", 9)
    monkeypatch.setattr(seeders()[Lesson].Meta, "count", 100)
    seed(seed=1, now=NOW, reset=True)
    titles = list(Course.objects.values_list("title", flat=True))
    assert len(titles) == len(set(titles)) == 9
    assert {without_round(title) for title in titles} <= {s.title for s in COURSES}
    assert Lesson.objects.count() == 100
    assert not Lesson.objects.filter(position__lt=1).exists()
