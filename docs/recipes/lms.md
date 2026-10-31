---
description: "The lms recipe: courses, lessons in order, enrolments students own and lesson progress, with instructor and student roles and a course's completion for a student."
---

# Recipe: online courses

!!! warning "Experimental"
    Recipes are [experimental](../stability.md#experimental-names). See
    [recipes](index.md).

Courses that instructors write as lessons in order, enrolments that
students own, and the lessons each student has completed. A course knows
how far a student is, in percent.

```sh
karni new "Evening Classes" --recipe lms
```

## Entities and roles

The app `courses`:

| Entity | Fields | Owner | Who reads, who writes |
|---|---|---|---|
| Course | title, slug (the import key), summary, instructor, published | instructor | anyone reads, the instructor and staff write, instructors and staff create |
| Lesson | course, title, body, position | course's instructor | anyone signed in reads, the instructor and staff write |
| Enrolment | course, student | student | the student, the course's instructor and staff read, the student and staff write |
| LessonProgress | enrolment, lesson, completed_at | enrolment's student | the student, the instructor and staff read, the student and staff write |

Lessons are ordered by course, then `position`. Enrolments keep their
change history.

| Role | Grants |
|---|---|
| `staff` | a system role: everything |
| `instructor` | `own:instructor` on courses, `own` on lessons |
| `student` | the role every account that signs up gets: `own` on enrolments and lesson progress |

## Modules and settings

- `email_code_login`: students sign in with a code sent by email.

Pages: the staff dashboard, courses and lessons (list, detail, form) and
enrolments (list, detail). Demo data: 6 published courses, 36 lessons, 40
enrolments, and progress on the first lessons of each student's course.

## Domain code

- `courses/models.py`: `Course.completion(student)` is the share of the
  course's lessons the student has completed, as a whole percent. Progress
  on a lesson of another course, or a lesson only started, does not count.
- `courses/viewsets.py`: `GET /api/enrolments/<id>/progress/` answers
  `{"percent": 75}` for the enrolled student.
- `courses/seeds.py`: published courses, lessons numbered in each course,
  and progress only on the lessons of the enrolment's own course.
- `courses/tests/test_completion.py`: the completion.

## What people usually change

| Change | In karni.yaml |
|---|---|
| the course and lesson fields | `fields` of `Course` and `Lesson`, for example `video: "url?"` or `minutes: "int?"` |
| who may enrol | `apps.courses.entities.Enrolment.access`, for example `create: "role:staff"` |
| whether lessons are open to everyone signed in | `apps.courses.entities.Lesson.access.read`, for example `["owned:course__instructor", "role:staff"]`, with a custom scope for enrolled students in code |

Then run `karni build`.
