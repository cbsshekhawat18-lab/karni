"""``karni plan --questions`` and ``karni spec answer`` (experimental): the questions before a build.

Every kind of gap, every module's and feature's ask, the order, the cap,
determinism, answers written back with the file's comments kept, a hand edit
settling a question, refused answers, and the JSON output against its
published schema. The rule agents follow is checked in ``test_rules.py``.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from karni_cli.main import app
from karni_cli.project import CliError
from karni_cli.spec import questions as q
from karni_cli.spec.catalog import FEATURES, MODULES
from karni_cli.spec.edit import EditError, set_value
from karni_cli.spec.validate import validate_text

from .conftest import REPO_ROOT

FIXTURE = Path(__file__).parent / "fixtures" / "spec" / "harbour-yoga.yaml"
SCHEMA_FILE = REPO_ROOT / "docs" / "assets" / "karni-questions.schema.json"
DOCS = REPO_ROOT / "docs" / "app-spec.md"

#: Every kind of gap once, with comments on every level to see they are kept.
GAPS = """\
# yaml-language-server: $schema=https://example.invalid/karni-spec.schema.json
version: 1
app:
  name: Club   # the name the users see
modules:
  payments:   # Stripe, most likely
features:
  terms: {version: "1", url: /terms/}
roles:
  staff: {name: Staff, system: true, grants: {"*": all}}
  coach: {grants: {club.lesson: own}, x-note: kept}
  member:
    grants: {club.booking: own, club.lesson: all}
apps:
  club:
    entities:
      Lesson:
        fields: {title: "str:100", coach: fk:User}   # who teaches
      Booking:
        fields:
          lesson: fk:Lesson
          member: fk:User
          # a note about the guest
          guest: fk:User?
        owner: member
# the end
"""


def ask(text: str) -> list[q.Question]:
    report = validate_text(textwrap.dedent(text))
    assert report.ok, [issue.render("x") for issue in report.issues]
    assert report.spec is not None and report.source is not None
    return q.questions(report.spec, report.source.data)


def ids(text: str) -> list[str]:
    return [question.id for question in ask(text)]


def answer(text: str, question_id: str, value: str) -> str:
    """``text`` with the answer written, as ``karni spec answer`` writes it."""
    question = {found.id: found for found in ask(text)}[question_id]
    for path, written in question.writes(question.parse(value)):
        text = set_value(text, path, written)
    return text


def write_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> Path:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "karni.yaml"
    path.write_text(text)
    return path


# each kind of gap -----------------------------------------------------------------------


def test_every_kind_of_gap_in_impact_order() -> None:
    found = ask(GAPS)
    assert [question.id for question in found] == [
        "club.Lesson.owner",
        "club.Lesson.access",
        "club.Booking.access",
        "roles.default",
        "app.kind",
        "modules.payments.provider",
        "modules.payments.currency",
        "features.terms.required",
    ]
    areas = [question.area for question in found]
    assert areas == sorted(areas, key=q.AREAS.index)
    assert set(areas) == set(q.AREAS)


def test_an_entity_related_to_the_user_without_owner() -> None:
    (owner,) = [question for question in ask(GAPS) if question.area == "owner"]
    assert owner.question == "Who owns a Lesson: the coach?"
    assert [option.value for option in owner.options] == ["coach", "created_by"]
    assert owner.default == "coach" and owner.key == "apps.club.entities.Lesson.owner"
    two = ask("""\
        version: 1
        app: {name: X}
        apps:
          a:
            entities:
              Order: {fields: {buyer: fk:User, seller: "o2o:User?", tags: "str:9"}}
    """)
    assert two[0].question == "Who owns an Order: the buyer or the seller?"
    assert two[0].default == "buyer"
    named = ask("""\
        version: 1
        app: {name: X}
        apps:
          a:
            entities:
              Order:
                fields: {buyer: fk:User, seller: "o2o:User?"}
                access: {read: [public], write: "owned:seller"}
    """)
    assert named[0].default == "seller"  # the access names it


def test_an_entity_without_a_user_relation_has_no_owner_question() -> None:
    assert "club.Booking.owner" not in ids(GAPS)
    spec = """\
        version: 1
        app: {name: X, kind: app}
        apps: {a: {entities: {Tag: {fields: {name: str}, access: {read: public, write: granted}}}}}
    """
    assert ids(spec) == []


def test_an_external_entity_is_not_owned_by_its_creator() -> None:
    (owner, _access) = ask("""\
        version: 1
        app: {name: X, kind: app}
        apps:
          a:
            entities:
              Legacy: {external: true, table: legacy, fields: {who: fk:User}}
    """)
    assert [option.value for option in owner.options] == ["who"]


def test_an_entity_without_access_offers_the_presets_that_fit() -> None:
    found = {question.id: question for question in ask(GAPS)}
    booking = found["club.Booking.access"]
    assert booking.question == "Who may see and change bookings?"
    assert [option.value for option in booking.options] == [
        "granted",
        "owned:member",
        "owned:guest",
        "authenticated",
        "public-read",
        "public-create",
        "staff",
    ]
    assert booking.default == "granted"
    assert q.access_rule("public-read") == {"read": "public", "write": "role:staff"}
    assert q.access_rule("public-create:admin") == {
        "read": "role:admin",
        "write": "role:admin",
        "create": "public",
    }
    assert q.access_rule("owned:member") == {"read": "owned:member", "write": "owned:member"}


def test_access_presets_follow_the_staff_role_of_the_spec() -> None:
    no_staff = """\
        version: 1
        app: {name: X, kind: app}
        roles: {admin: {system: true}, member: {default: true}}
        apps: {a: {entities: {Note: {fields: {body: text}}}}}
    """
    (access,) = ask(no_staff)
    assert [option.value for option in access.options][-3:] == [
        "public-read:admin",
        "public-create:admin",
        "role:admin",
    ]
    none = no_staff.replace("admin: {system: true}, ", "")
    (access,) = ask(none)
    assert [option.value for option in access.options] == ["granted", "authenticated"]


def test_roles_without_a_default_for_sign_ups() -> None:
    found = {question.id: question for question in ask(GAPS)}
    role = found["roles.default"]
    assert role.question == "Which role does someone who signs up get: coach, member or none?"
    assert [option.value for option in role.options] == ["coach", "member", "none"]
    assert role.default == "coach"  # member has an "all" grant: coach grants less
    assert role.key == "roles.<role>.default"


def test_no_roles_or_a_written_default_settle_the_sign_up_role() -> None:
    assert "roles.default" not in ids("version: 1\napp: {name: X}\n")
    written = GAPS.replace("x-note: kept}", "default: false}")
    assert "roles.default" not in ids(written)
    only_system = "version: 1\napp: {name: X}\nroles: {staff: {system: true}}\n"
    assert "roles.default" not in ids(only_system)


def test_a_missing_app_kind() -> None:
    kind = ask("version: 1\napp: {name: X}\n")
    assert [question.id for question in kind] == ["app.kind"]
    assert [option.value for option in kind[0].options] == ["app", "site", "site+app"]
    assert ids("version: 1\napp: {name: X, kind: app}\n") == []


# each module and feature ask ----------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(MODULES))
def test_every_module_ask_is_a_question_until_its_option_is_set(name: str) -> None:
    module = MODULES[name]
    kind = "site+app" if name == "site" else "app"
    spec = f"version: 1\napp: {{name: X, kind: {kind}}}\nmodules:\n  {name}:\n"
    expected = []
    for item in module.asks:
        option = item.setting.removeprefix(f"KARNI_{name.upper()}_").lower()
        expected.append((f"modules.{name}.{option}", item))
    assert expected, f"{name} asks nothing"
    found = {question.id: question for question in ask(spec)}
    assert list(found) == [question_id for question_id, _ in expected]
    for question_id, item in expected:
        question = found[question_id]
        assert [option.value for option in question.options] == list(item.options)
        assert question.default == (item.default if item.has_default else None)
        assert question.types == module.options[question_id.rsplit(".", 1)[1]]
        assert question.question.endswith(item.question[1:])
    settled = (
        spec.rstrip(":\n")
        + ": {"
        + ", ".join(
            f"{question_id.rsplit('.', 1)[1]}: {json.dumps(item.default if item.has_default else 'x')}"
            for question_id, item in expected
        )
        + "}\n"
    )
    assert ids(settled) == []


def test_module_questions_name_the_module_unless_the_question_does() -> None:
    found = {question.id: question for question in ask(GAPS)}
    assert found["modules.payments.provider"].question == (
        "Which payment provider: Stripe or Razorpay?"
    )
    assert found["modules.payments.currency"].question == (
        "Payments: which currency, as a lowercase ISO 4217 code?"
    )


def test_a_kind_with_a_site_asks_the_site_module() -> None:
    assert "modules.site.editor_role" in ids("version: 1\napp: {name: X, kind: site}\n")
    assert "modules.site.editor_role" not in ids("version: 1\napp: {name: X, kind: app}\n")


def test_feature_asks_only_where_karni_yaml_has_their_key() -> None:
    every = """\
        version: 1
        app: {name: X, kind: app}
        features:
          two_factor: true
          email_code_login: true
          social_login: [google]
          terms: {version: "1", url: /terms/}
    """
    assert ids(every) == ["features.terms.required"]
    # an ask without a key in karni.yaml (how long a code lives, who may sign up) is never asked
    unasked = {
        item.setting
        for feature in FEATURES.values()
        for item in feature.asks
        if not item.setting.startswith(f"{feature.switch}.")
    }
    assert "KARNI_EMAIL_OTP_TTL" in unasked and "KARNI_SOCIAL_TOKEN_SIGNUP" in unasked
    off = every.replace("two_factor: true", "two_factor: false").replace(
        '  terms: {version: "1", url: /terms/}\n', ""
    )
    assert ids(off) == []
    assert ids(every.replace("url: /terms/}", "url: /terms/, required: false}")) == []


def test_never_a_cosmetic_question() -> None:
    every = [question.key for question in ask(GAPS)]
    for cosmetic in ("name", "description", "groups", "pages", "seed", "search", "order"):
        assert not any(key.endswith(f".{cosmetic}") for key in every), cosmetic


# order, cap, determinism ----------------------------------------------------------------


def test_the_cap_and_max(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_spec(tmp_path, monkeypatch, GAPS)
    runner = CliRunner()
    default = runner.invoke(app, ["plan", "--questions", "--json"])
    assert default.exit_code == 0, default.output
    data = json.loads(default.output)
    assert len(data["questions"]) == q.DEFAULT_MAX == 5 and data["total"] == 8
    assert data["max"] == 5
    two = json.loads(runner.invoke(app, ["plan", "--questions", "--json", "--max", "2"]).output)
    assert [item["id"] for item in two["questions"]] == [
        item["id"] for item in data["questions"][:2]
    ]
    every = json.loads(runner.invoke(app, ["plan", "--questions", "--json", "--max", "0"]).output)
    assert len(every["questions"]) == 8 and every["max"] is None
    text = runner.invoke(app, ["plan", "--questions"]).output
    assert text.startswith("5 of 8 questions for the user before karni build")
    assert "1. club.Lesson.owner: Who owns a Lesson: the coach?" in text
    assert "   - coach: the coach (fk:User) (default)" in text
    refused = runner.invoke(app, ["plan", "--max", "2"])
    assert refused.exit_code != 0 and "--max goes with --questions" in refused.output


def test_the_same_spec_gives_the_same_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_spec(tmp_path, monkeypatch, GAPS)
    runner = CliRunner()
    first = runner.invoke(app, ["plan", "--questions", "--json", "--max", "0"]).output
    again = runner.invoke(app, ["plan", "--questions", "--json", "--max", "0"]).output
    assert first == again
    assert [question.as_dict() for question in ask(GAPS)] == json.loads(first)["questions"]


def test_an_id_stays_with_its_gap_when_others_are_answered() -> None:
    before = ids(GAPS)
    after = ids(answer(GAPS, "club.Lesson.owner", "coach"))
    assert after == before[1:]


def test_no_questions_and_no_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_spec(tmp_path, monkeypatch, FIXTURE.read_text())
    runner = CliRunner()
    full = runner.invoke(app, ["plan", "--questions", "--max", "0"])
    assert full.exit_code == 0, full.output  # no manage.py here: the project is not read
    assert "modules.payments.currency" in full.output
    settled = (
        FIXTURE.read_text()
        .replace(
            "    provider: stripe\n",
            "    provider: stripe\n    currency: eur\n  site:\n    editor_role: editor\n",
        )
        .replace("url: /terms/}", "url: /terms/, required: true}")
    )
    (tmp_path / "karni.yaml").write_text(settled)
    none = runner.invoke(app, ["plan", "--questions"])
    assert none.output == (
        "No questions: karni.yaml settles everything Karni asks before a build.\nnext: karni build\n"
    )


def test_an_invalid_spec_has_no_questions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_spec(tmp_path, monkeypatch, "version: 1\napp: {name: X, colour: red}\n")
    runner = CliRunner()
    text = runner.invoke(app, ["plan", "--questions"])
    assert text.exit_code == 1 and "C212" in text.output and "so no questions" in text.output
    data = json.loads(runner.invoke(app, ["plan", "--questions", "--json"]).output)
    assert (
        data["valid"] is False and data["questions"] == [] and data["issues"][0]["code"] == "C212"
    )
    (tmp_path / "karni.yaml").unlink()
    missing = runner.invoke(app, ["plan", "--questions"])
    assert isinstance(missing.exception, CliError) and missing.exception.code == "C210"


# answers ----------------------------------------------------------------------------------


def test_an_answer_is_written_with_the_comments_and_vanishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_spec(tmp_path, monkeypatch, GAPS)
    runner = CliRunner()
    result = runner.invoke(app, ["spec", "answer", "club.Booking.access", "owned:member"])
    assert result.exit_code == 0, result.output
    assert result.output == (
        "karni.yaml: apps.club.entities.Booking.access set (club.Booking.access answered).\n"
        "next: karni plan --questions (7 questions open)\n"
    )
    text = path.read_text()
    added = [line for line in text.splitlines() if line not in GAPS.splitlines()]
    assert added == ['        access: {read: "owned:member", write: "owned:member"}']
    assert [line for line in text.splitlines() if line in GAPS.splitlines()] == GAPS.splitlines()
    assert "club.Booking.access" not in ids(text)


def test_every_answer_to_every_question_is_valid_and_settles_it() -> None:
    comments = [line.split("#", 1)[1] for line in GAPS.splitlines() if "#" in line]
    for question in ask(GAPS):
        values = [option.value for option in question.options] or ["eur"]
        for value in values:
            shown = q._show(value)
            text = answer(GAPS, question.id, shown)
            report = validate_text(text)
            assert report.ok, (question.id, shown, [i.render("x") for i in report.issues])
            assert question.id not in ids(text), (question.id, shown)
            assert all(comment in text for comment in comments), (question.id, shown)
            assert len(text.splitlines()) - len(GAPS.splitlines()) in (0, 1), (question.id, shown)


def test_an_empty_module_takes_its_options_on_its_line() -> None:
    text = answer(GAPS, "modules.payments.provider", "razorpay")
    assert "  payments: {provider: razorpay}   # Stripe, most likely\n" in text
    text = answer(text, "modules.payments.currency", "inr")
    assert "  payments: {provider: razorpay, currency: inr}   # Stripe, most likely\n" in text
    data = yaml.safe_load(text)
    assert data["modules"]["payments"] == {"provider": "razorpay", "currency": "inr"}


def test_the_sign_up_role_answers() -> None:
    member = answer(GAPS, "roles.default", "member")
    assert "    grants: {club.booking: own, club.lesson: all}\n    default: true\n" in member
    none = yaml.safe_load(answer(GAPS, "roles.default", "none"))
    assert none["roles"]["coach"]["default"] is False
    assert none["roles"]["member"]["default"] is False
    assert "default" not in none["roles"]["staff"]


def test_free_values_take_their_type() -> None:
    approvals = "version: 1\napp: {name: X, kind: app}\nmodules: {approvals: {}}\n"
    found = {question.id: question for question in ask(approvals)}
    assert found["modules.approvals.required"].parse("2") == 2
    with pytest.raises(q.AnswerError, match="takes integer"):
        found["modules.approvals.required"].parse("two")
    site = {question.id: question for question in ask("version: 1\napp: {name: X, kind: site}\n")}
    editor = site["modules.site.editor_role"]
    assert editor.parse("null") is None and editor.parse("editor") == "editor"
    text = answer(approvals, "modules.approvals.required", "2")
    assert "modules: {approvals: {required: 2}}" in text


def test_a_hand_edit_settles_a_question() -> None:
    assert "club.Lesson.owner" in ids(GAPS)
    edited = GAPS.replace(
        '{title: "str:100", coach: fk:User}   # who teaches',
        '{title: "str:100", coach: fk:User}   # who teaches\n        owner: created_by',
    )
    assert "club.Lesson.owner" not in ids(edited)
    assert "app.kind" not in ids(GAPS.replace("  name: Club", "  kind: app\n  name: Club"))


def test_refused_answers_write_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_spec(tmp_path, monkeypatch, GAPS)
    runner = CliRunner()
    cases = [
        (["spec", "answer", "club.Nope.owner", "x"], "C400", "open: club.Lesson.owner, "),
        (["spec", "answer", "club.Booking.owner", "member"], "C400", "is not an open question"),
        (["spec", "answer", "app.kind", "website"], "C401", "Choose one of: app, site, site+app"),
        (["spec", "answer", "club.Lesson.owner", "title"], "C401", "coach, created_by"),
        (["spec", "answer", "features.terms.required", "maybe"], "C401", "true, false"),
    ]
    for args, code, fragment in cases:
        result = runner.invoke(app, args)
        assert isinstance(result.exception, CliError), (args, result.output)
        assert result.exception.code == code and fragment in str(result.exception), args
        assert path.read_text() == GAPS
    (tmp_path / "karni.yaml").write_text("version: 1\napp: {name: X, colour: red}\n")
    invalid = runner.invoke(app, ["spec", "answer", "app.kind", "app"])
    assert invalid.exit_code == 1 and "C212" in invalid.output


def test_an_answer_that_cannot_keep_the_layout_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = """\
version: 1
app: {name: X, kind: app}
apps:
  a:
    entities:
      Note: &note {fields: {body: text, by: fk:User}, owner: by}
      Memo: *note
"""
    path = write_spec(tmp_path, monkeypatch, shared)
    result = CliRunner().invoke(app, ["spec", "answer", "a.Note.access", "granted"])
    assert isinstance(result.exception, CliError) and result.exception.code == "C402"
    assert "Nothing was written" in str(result.exception)
    assert path.read_text() == shared


# the writer -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "path", "value", "expected"),
    [
        ("a:\n  b: 1\n", ("a", "c"), 2, "a:\n  b: 1\n  c: 2\n"),
        ("a:\n  b: 1", ("a", "c"), 2, "a:\n  b: 1\n  c: 2\n"),
        ("a:\r\n  b: 1\r\n", ("a", "c"), 2, "a:\r\n  b: 1\r\n  c: 2\r\n"),
        ("a: {b: 1}  # x\n", ("a", "c"), "y:z", 'a: {b: 1, c: "y:z"}  # x\n'),
        ("a: {}\n", ("a", "c"), True, "a: {c: true}\n"),
        ("a: {\n  b: 1,\n}\n", ("a", "c"), 2, "a: {\n  b: 1, c: 2\n}\n"),
        ("a:\n", ("a", "c"), 2, "a: {c: 2}\n"),
        ("a: null  # n\n", ("a", "c"), 2, "a: {c: 2}  # n\n"),
        ("a: 1  # keep\nb: 2\n", ("a",), 3, "a: 3  # keep\nb: 2\n"),
        ("a:\n  b: |\n    text\n\nc: 1\n", ("a", "d"), 1, "a:\n  b: |\n    text\n\n  d: 1\nc: 1\n"),
        ("x: 1\n", ("a", "b"), {"c": 1}, "x: 1\na: {b: {c: 1}}\n"),
        ("x: 1\n", ("modules", "site"), {"c": 1}, "x: 1\nmodules:\n  site: {c: 1}\n"),
        ("a:\n  b: 1\n# tail\n", ("a", "c"), [1, 2], "a:\n  b: 1\n  c: [1, 2]\n# tail\n"),
    ],
)
def test_the_writer_keeps_everything_else(
    text: str, path: tuple[str, ...], value: Any, expected: str
) -> None:
    assert set_value(text, path, value) == expected


def test_the_writer_refuses_what_it_cannot_place() -> None:
    with pytest.raises(EditError, match="not a mapping"):
        set_value("a: 1\n", ("a", "b"), 2)
    with pytest.raises(EditError, match="block"):
        set_value("a:\n  b: 1\n", ("a",), {"c": 2})
    with pytest.raises(EditError, match="more than that key"):
        set_value("a: &x {b: 1}\nc: *x\n", ("a", "d"), 2)
    with pytest.raises(EditError, match="not valid YAML"):
        set_value("a: [\n", ("a",), 1)


# the JSON output and the docs -------------------------------------------------------------


def test_the_published_questions_schema_is_current_and_checks_the_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = json.dumps(q.json_schema(), indent=2) + "\n"
    assert SCHEMA_FILE.read_text() == expected, (
        "docs/assets/karni-questions.schema.json is stale. Regenerate it: "
        "python -m karni_cli.spec.questions > docs/assets/karni-questions.schema.json"
    )
    jsonschema = pytest.importorskip("jsonschema")
    published = json.loads(SCHEMA_FILE.read_text())
    jsonschema.Draft202012Validator.check_schema(published)
    validator = jsonschema.Draft202012Validator(published)
    write_spec(tmp_path, monkeypatch, GAPS)
    runner = CliRunner()
    for args in (["--max", "0"], [], ["--max", "1"]):
        data = json.loads(runner.invoke(app, ["plan", "--questions", "--json", *args]).output)
        validator.validate(data)
    (tmp_path / "karni.yaml").write_text("version: 1\napp: {name: X, colour: red}\n")
    validator.validate(json.loads(runner.invoke(app, ["plan", "--questions", "--json"]).output))


#: The keys the docs' example removes from the fixture (docs/app-spec.md#questions).
REMOVED = (
    "  kind: site+app\n",
    "    provider: stripe\n",
    '        access: {read: public, write: "role:staff"}\n',
    "        owner: member\n",
)


def test_the_docs_show_the_fixture_with_keys_removed() -> None:
    spec = FIXTURE.read_text().replace(" default: true,", "")
    for line in REMOVED:
        assert spec.count(line) == 1, line
        spec = spec.replace(line, "")
    docs = DOCS.read_text()
    section = docs.split("\n## Questions", 1)[1].split("\n## ", 1)[0]
    shown = section.split("```text\n", 1)[1].split("```", 1)[0]
    assert q.render(ask(spec), q.DEFAULT_MAX) == shown
    for line in (*REMOVED, "default: true"):
        assert line.strip() in section, line
