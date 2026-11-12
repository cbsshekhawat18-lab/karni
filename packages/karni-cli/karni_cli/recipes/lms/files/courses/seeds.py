"""courses demo data for karni seed. Each seeder extends the one karni build writes in
courses/karni/seeds.py: steer a field's values here.

The courses and lessons are invented. Replace COURSES with your own.
"""

import datetime as dt
from typing import Any, NamedTuple

from courses.karni import seeds as karni
from karni.seeding import SeedContext, cycled

from courses.models import Course, Enrolment, Lesson


class Subject(NamedTuple):
    title: str
    summary: str
    lessons: tuple[tuple[str, str], ...]  # a lesson's title and its text


COURSES = [
    Subject(
        "Introduction to Home Baking",
        "Learn the basics of bread, rolls and simple cakes with ingredients from any "
        "shop.",
        (
            (
                "Flour, water, yeast and salt",
                "Meet the four ingredients behind most bread. Weigh them and see how "
                "each one changes the dough.",
            ),
            (
                "Mixing and kneading by hand",
                "Mix a first dough and knead it until it feels smooth. Learn the "
                "window pane test.",
            ),
            (
                "Proving and shaping",
                "Let the dough rise in a warm place, then shape it into a loaf and a "
                "set of rolls.",
            ),
            (
                "Baking a crisp crust",
                "Heat the oven properly, add steam and bake until the loaf sounds "
                "hollow.",
            ),
            (
                "Simple sponge cakes",
                "Cream butter and sugar, fold in flour and bake a plain sponge that "
                "stays moist.",
            ),
            (
                "Storing and reviving bread",
                "Keep bread fresh for days and bring a stale loaf back to life.",
            ),
        ),
    ),
    Subject(
        "Personal Budgeting Basics",
        "Track your income and spending, set goals and build a monthly plan that you "
        "can keep.",
        (
            (
                "Where your money goes",
                "Collect a month of statements and sort every payment into a handful "
                "of groups.",
            ),
            (
                "Fixed and flexible costs",
                "Separate rent and bills from food and fun, and see which costs you "
                "can change.",
            ),
            (
                "Building a monthly plan",
                "Give every pound a job with a simple plan and a weekly check-in.",
            ),
            (
                "An emergency fund",
                "Decide how much to set aside for surprises and how to build it in "
                "small steps.",
            ),
            (
                "Paying down debt",
                "Compare the snowball and avalanche methods and pick one to follow.",
            ),
            (
                "Saving for a goal",
                "Turn a goal such as a holiday or a deposit into a monthly amount.",
            ),
        ),
    ),
    Subject(
        "Beginner Python Programming",
        "Write small programs from your first line of code to reading and writing "
        "files.",
        (
            (
                "Running your first program",
                "Install Python, open a terminal and run a script that prints a "
                "greeting.",
            ),
            (
                "Variables and types",
                "Store numbers and text in variables and see how Python treats each "
                "type.",
            ),
            (
                "Making decisions with if",
                "Use comparisons and if statements to make a program choose between "
                "paths.",
            ),
            (
                "Repeating with loops",
                "Use for and while loops to work through a list and stop at the "
                "right time.",
            ),
            (
                "Functions you can reuse",
                "Wrap code in a function, give it parameters and return a result.",
            ),
            (
                "Reading and writing files",
                "Open a text file, read its lines and save the results to a new file.",
            ),
        ),
    ),
    Subject(
        "Urban Gardening for Small Spaces",
        "Grow herbs, salad and tomatoes on a balcony, a windowsill or a small yard.",
        (
            (
                "Reading your light",
                "Track the sun across your space and match plants to the light they "
                "get.",
            ),
            (
                "Pots, soil and drainage",
                "Choose containers and a potting mix that keep roots healthy.",
            ),
            (
                "Sowing and transplanting",
                "Start seeds indoors, harden them off and move them outside.",
            ),
            (
                "Watering without waste",
                "Water at the right time and depth, and use mulch to hold moisture.",
            ),
            (
                "Feeding and pest control",
                "Feed plants through the season and deal with aphids and slugs gently.",
            ),
            (
                "Harvesting and saving seed",
                "Pick at the right moment and keep seed for next year's pots.",
            ),
        ),
    ),
    Subject(
        "Public Speaking with Confidence",
        "Plan a talk, steady your nerves and deliver a short presentation clearly.",
        (
            (
                "Know your audience",
                "Ask who is listening and what they need, then shape your message "
                "around it.",
            ),
            (
                "Structuring a short talk",
                "Build a talk from an opening, three points and a clear close.",
            ),
            (
                "Calming your nerves",
                "Use breathing and preparation to bring your pulse down before you "
                "start.",
            ),
            (
                "Voice, pace and pauses",
                "Slow down, vary your tone and use pauses to let ideas land.",
            ),
            (
                "Slides that help",
                "Keep slides simple and let them support you instead of replacing you.",
            ),
            (
                "Answering questions",
                "Listen, pause and answer questions, including the ones you cannot "
                "answer.",
            ),
        ),
    ),
    Subject(
        "Digital Photography Essentials",
        "Understand your camera, light and composition to take sharper, better photos.",
        (
            (
                "Know your camera",
                "Find the main controls on your camera or phone and what each one "
                "does.",
            ),
            (
                "Exposure: aperture, shutter, ISO",
                "See how the three settings trade off against each other.",
            ),
            (
                "Composition basics",
                "Use the rule of thirds, leading lines and framing to guide the eye.",
            ),
            (
                "Working with natural light",
                "Photograph at different times of day and learn which light flatters.",
            ),
            (
                "Portraits and people",
                "Put people at ease and take portraits that look natural.",
            ),
            (
                "Editing and sharing",
                "Crop, adjust and export photos, and keep your library in order.",
            ),
        ),
    ),
]


def _subject(course: Course, position: int) -> Subject:
    """The subject a course row was made from (also with a suffix), else by position."""
    for subject in COURSES:
        if course.title.startswith(subject.title):
            return subject
    return COURSES[position % len(COURSES)]


class CourseSeeder(karni.CourseSeeder):
    """Courses open to students, each with a summary of what it teaches."""

    published = True

    def seed(self, context: SeedContext) -> list[Any]:
        titles = [subject.title for subject in COURSES]
        return [
            context.create(
                1,
                title=cycled(titles, number),
                summary=COURSES[number % len(COURSES)].summary,
            )[0]
            for number in range(context.count)
        ]


class LessonSeeder(karni.LessonSeeder):
    """Lessons numbered from 1 in each course, in the order the course teaches them."""

    def seed(self, context: SeedContext) -> list[Any]:
        courses = list(Course.objects.order_by("title"))
        rows: list[Any] = []
        for number in range(context.count):
            if not courses:
                rows += context.create(1)
                continue
            position = number % len(courses)
            course = courses[position]
            lessons = _subject(course, position).lessons
            turn = number // len(courses)
            title, body = lessons[turn % len(lessons)]
            if turn >= len(lessons):
                title = cycled([title], turn // len(lessons))
            rows += context.create(
                1, course=course, title=title, body=body, position=turn + 1
            )
        return rows


class EnrolmentSeeder(karni.EnrolmentSeeder):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class LessonProgressSeeder(karni.LessonProgressSeeder):
    """Each student did the first lessons of their own course, some more than others."""

    def seed(self, context: SeedContext) -> list[Any]:
        enrolments = list(Enrolment.objects.select_related("course").order_by("pk"))
        lessons = {
            enrolment.pk: list(
                Lesson.objects.filter(course=enrolment.course).order_by("position")
            )
            for enrolment in enrolments
        }
        # how far each student got: at least one lesson, at most the whole course
        reach = {
            enrolment.pk: context.random.randint(1, max(1, len(lessons[enrolment.pk])))
            for enrolment in enrolments
        }
        # first each student's lessons up to how far they got, then the rest, in order
        wanted = [
            (depth >= reach[enrolment.pk], depth, index)
            for index, enrolment in enumerate(enrolments)
            for depth in range(len(lessons[enrolment.pk]))
        ]
        now = context.run.anchor.replace(minute=0, second=0, microsecond=0)
        rows: list[Any] = []
        for _, depth, index in sorted(wanted)[: context.count]:
            enrolment = enrolments[index]
            rows += context.create(
                1,
                enrolment=enrolment,
                lesson=lessons[enrolment.pk][depth],
                completed_at=now - dt.timedelta(days=40 - depth * 4, hours=index % 9),
            )
        return rows
