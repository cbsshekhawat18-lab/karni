"""Experimental. ``karni plan --questions``: the few questions worth asking before ``karni build``.

An agent turns a one-line request into ``karni.yaml``. Some decisions in it
are the user's, and the agent should ask about those and nothing else.
Karni decides which ones, with fixed rules over the spec and the module
catalog's manifests: the same spec gives the same questions in the same
order, and no language model is involved.

A question is a **gap**: a key the spec leaves unwritten where the answer
changes who sees what, or how a module behaves. Each kind of gap, in the
order of its impact:

1. ``owner``: an entity with a relation to the user and no ``owner``
   ("Who owns a Booking: the member?"). The own scope then falls back to
   ``created_by``.
2. ``access``: an entity without ``access``. It gets ``Granted()``, and the
   options are the ``--access`` presets that fit the entity.
3. ``roles``: roles declared, and none says ``default``. Sign-up is open in
   every project a spec describes, and a new account without a role is
   granted nothing.
4. ``app``: ``app.kind`` unwritten (it defaults to ``app``).
5. ``modules``: each ask of a listed module's manifest whose option the
   spec does not set (the site module counts when the kind has a site).
6. ``features``: each ask of a feature the spec turns on, when the ask maps
   to a key of that feature in karni.yaml and the key is unwritten.

An ask whose setting has no key in karni.yaml (how long a sign-in code
lives, who may sign up with a code) is never a question here: ``karni
modules show`` prints it, and the setting goes in the settings. Nothing
cosmetic is ever asked: names, labels, colours and page titles are not
gaps.

:func:`questions` returns every gap of a valid spec, in that order. ``karni
plan --questions`` shows the first :data:`DEFAULT_MAX` (``--max`` changes it).
``karni spec answer <id> <value>`` writes the answer with
:mod:`karni_cli.spec.edit`, keeping the file's comments and layout, and the
question is gone. Editing the file by hand settles it the same way.

Override / escape hatch: a question is a plain :class:`Question`, so a tool
filters or reorders them, and :meth:`Question.writes` says which keys an
answer sets, for a tool that writes the file its own way. ``x-`` keys are
the place for notes of your own: they never settle a question.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Final, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from karni_cli.generators.fields import is_user_target, parse_field, relation_name
from karni_cli.generators.naming import pluralize, words
from karni_cli.generators.viewset import PUBLIC_READ_WRITER
from karni_cli.project import CliError
from karni_cli.spec import schema
from karni_cli.spec.catalog import FEATURES, MODULES, KnownFeature, KnownModule
from karni_cli.spec.edit import EditError, set_values
from karni_cli.spec.normal import role_name
from karni_cli.spec.source import Loc
from karni_cli.spec.validate import SHIPPED_ROLES, validate_text

__all__ = [
    "AREAS",
    "DEFAULT_MAX",
    "QUESTIONS_SCHEMA_URL",
    "QUESTIONS_VERSION",
    "AnswerError",
    "Answered",
    "Option",
    "Question",
    "access_rule",
    "answer",
    "checked_output",
    "invalid_output",
    "json_schema",
    "output",
    "questions",
    "render",
    "shown",
]

#: Experimental. How many questions ``karni plan --questions`` shows without ``--max``.
DEFAULT_MAX: Final = 5
#: Experimental. The version of the ``--json`` output. It moves only for a breaking change.
QUESTIONS_VERSION: Final = 1
#: Experimental. Where the JSON Schema of ``karni plan --questions --json`` is published.
QUESTIONS_SCHEMA_URL: Final = (
    "https://cbsshekhawat18-lab.github.io/karni/assets/karni-questions.schema.json"
)
Area = Literal["owner", "access", "roles", "app", "modules", "features"]
#: Experimental. The kinds of gap, most impact first: the order questions come in.
AREAS: Final[tuple[str, ...]] = get_args(Area)
#: The answer to the sign-up role question that gives a new account no role.
NO_ROLE: Final = "none"
_JSON_TYPES: Final = {bool: "boolean", int: "integer", float: "number", str: "string"}


class AnswerError(ValueError):
    """Experimental. A value the question does not take: the message says which ones it does."""


@dataclass(frozen=True)
class Option:
    """Experimental. One answer a question offers: the value written, and what it means."""

    value: Any
    label: str

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "label": self.label}


@dataclass(frozen=True)
class Question:
    """Experimental. One gap of the spec, asked as one sentence with its options.

    ``id`` is the same for the same gap whatever else the spec says, ``key``
    is the dotted path of the spec key the answer sets, ``options`` are the
    answers to choose from (none: a free value of one of ``types``), and
    ``default`` is the answer when the user has no preference.
    """

    id: str
    area: str
    question: str
    key: str
    options: tuple[Option, ...] = ()
    default: Any = None
    types: tuple[str, ...] = ("string",)
    multiple: bool = False
    #: The spec path the answer is written to (``roles`` writes to each role's ``default``).
    target: Loc = field(default=(), repr=False)

    def parse(self, raw: str) -> Any:
        """Experimental. The value ``raw`` (as typed on the command line) stands for.

        Raises :class:`AnswerError` when it is not one of the options, or not
        of a type the key takes.
        """
        text = raw.strip()
        if self.options:
            if self.multiple:
                return [self._choice(part.strip()) for part in text.split(",") if part.strip()]
            return self._choice(text)
        return self._free(text)

    def _choice(self, text: str) -> Any:
        choices = {_show(option.value): option.value for option in self.options}
        for candidate in (text, text.lower()):
            if candidate in choices:
                return choices[candidate]
        raise AnswerError(
            f"{text!r} is not an answer to {self.id}. Choose one of: "
            + ", ".join(choices)
            + (" (several, comma-separated)." if self.multiple else ".")
        )

    def _free(self, text: str) -> Any:
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = text
        if not isinstance(parsed, str) and _json_type(parsed) in self.types:
            return parsed
        if "string" in self.types:
            return text
        if "array" in self.types:
            return [part.strip() for part in text.split(",") if part.strip()]
        raise AnswerError(
            f"{text!r} is not an answer to {self.id}: it takes {' or '.join(self.types)}."
        )

    def writes(self, value: Any) -> list[tuple[Loc, Any]]:
        """Experimental. The ``(spec path, value)`` pairs answering ``value`` sets."""
        if self.area == "access":
            return [(self.target, access_rule(str(value)))]
        if self.area == "roles":
            if value == NO_ROLE:
                return [
                    (("roles", str(option.value), "default"), False)
                    for option in self.options
                    if option.value != NO_ROLE
                ]
            return [(("roles", str(value), "default"), True)]
        return [(self.target, value)]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "area": self.area,
            "question": self.question,
            "options": [option.as_dict() for option in self.options],
            "default": self.default,
            "multiple": self.multiple,
            "types": list(self.types),
            "key": self.key,
        }

    def lines(self, number: int) -> list[str]:
        """The question as ``karni plan --questions`` prints it."""
        out = [f"{number}. {self.id}: {self.question}"]
        for option in self.options:
            value = _show(option.value)
            mark = " (default)" if value == _show(self.default) else ""
            label = "" if option.label == value else f": {option.label}"
            out.append(f"   - {value}{label}{mark}")
        if not self.options:
            default = f", default {_show(self.default)}" if self.default is not None else ""
            out.append(f"   - any {' or '.join(self.types)}{default}")
        return out


# helpers ----------------------------------------------------------------------------


def _show(value: Any) -> str:
    """A value as typed on the command line: ``true``, ``null``, ``stripe``."""
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, list):
        return ",".join(_show(item) for item in value)
    return str(value)


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return _JSON_TYPES.get(type(value), "string")


def _phrase(name: str) -> str:
    """``session__instructor`` -> ``session instructor``, ``TicketTier`` -> ``ticket tier``."""
    return " ".join(words(name.replace("__", "_")))


def _article(noun: str) -> str:
    return "an" if noun[:1].lower() in "aeiou" else "a"


def _either(items: list[str]) -> str:
    """``a``, ``a or b``, ``a, b or c``."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def _ask_text(title: str, question: str) -> str:
    """A manifest's question, with its title in front when it does not name it already.

    ``Payments: which currency, as a lowercase ISO 4217 code?``, but ``How many
    minutes may an impersonation last?`` as written.
    """
    text = question.lower()
    if not title or any(
        word.rstrip("s") in text for word in title.lower().split() if len(word) > 3
    ):
        return question
    if len(question) > 1 and question[0].isupper() and question[1].islower():
        question = question[0].lower() + question[1:]
    return f"{title}: {question}"


def access_rule(preset: str) -> dict[str, str]:
    """Experimental. The ``access:`` mapping an ``--access`` preset is in karni.yaml.

    The table of docs/app-spec.md#access: ``public-read`` is ``{read: public,
    write: "role:staff"}``, ``owned:member`` is ``{read: "owned:member",
    write: "owned:member"}``, ``granted`` writes both slots out.
    """
    kind, colon, arg = preset.partition(":")
    if kind in ("granted", "authenticated") and not colon:
        return {"read": kind, "write": kind}
    if kind in ("public-read", "public-create"):
        role = f"role:{arg if colon else PUBLIC_READ_WRITER}"
        if kind == "public-read":
            return {"read": "public", "write": role}
        return {"read": role, "write": role, "create": "public"}
    if kind == "staff" and not colon:
        return {"read": "role:staff", "write": "role:staff"}
    if kind in ("role", "owned") and arg:
        return {"read": preset, "write": preset}
    raise AnswerError(f"{preset!r} is not an access preset.")


# the gaps ---------------------------------------------------------------------------


@dataclass
class _Entity:
    app: str
    name: str
    entity: schema.Entity
    raw: dict[str, Any]
    #: Relations to the user, in field order: field name -> its type as written.
    users: dict[str, str]

    @property
    def id(self) -> str:
        return f"{self.app}.{self.name}"

    @property
    def key(self) -> str:
        return f"apps.{self.app}.entities.{self.name}"

    @property
    def path(self) -> Loc:
        return ("apps", self.app, "entities", self.name)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _entities(spec: schema.Spec, data: dict[str, Any]) -> list[_Entity]:
    found = []
    for app_label, app in spec.apps.items():
        raw_app = _mapping(_mapping(_mapping(data.get("apps")).get(app_label)).get("entities"))
        for name, entity in app.entities.items():
            users: dict[str, str] = {}
            for field_name, token in entity.tokens().items():
                try:
                    parsed = parse_field(f"{field_name}:{token}")
                    if parsed.is_relation and is_user_target(relation_name(parsed)):
                        users[field_name] = token
                except CliError:  # pragma: no cover - the spec is valid
                    continue
            found.append(_Entity(app_label, name, entity, _mapping(raw_app.get(name)), users))
    return found


def _owner(entity: _Entity) -> Question | None:
    if "owner" in entity.raw or not entity.users:
        return None
    options = [
        Option(name, f"the {_phrase(name)} ({token})") for name, token in entity.users.items()
    ]
    database = entity.entity.database
    if not entity.entity.external and database in (None, "default"):
        options.append(Option("created_by", "whoever created it"))
    names = [f"the {_phrase(name)}" for name in entity.users]
    # the default: the first relation to the user the entity's access names (owned:<field>)
    rule = entity.entity.access
    owned = (
        [
            item[len("owned:") :]
            for slot in (rule.read, rule.write, rule.create or [])
            for item in slot
        ]
        if isinstance(rule, schema.Access)
        else []
    )
    default = next((name for name in owned if name in entity.users), next(iter(entity.users)))
    return Question(
        id=f"{entity.id}.owner",
        area="owner",
        question=f"Who owns {_article(entity.name)} {entity.name}: {_either(names)}?",
        key=f"{entity.key}.owner",
        options=tuple(options),
        default=default,
        target=(*entity.path, "owner"),
    )


def _staff(spec: schema.Spec) -> str | None:
    """The role the ``public-read``, ``public-create`` and ``staff`` presets let write."""
    declared = list(spec.roles) or list(SHIPPED_ROLES)
    if PUBLIC_READ_WRITER in declared:
        return PUBLIC_READ_WRITER
    return next((slug for slug, role in spec.roles.items() if role.system), None)


def _access(entity: _Entity, staff: str | None) -> Question | None:
    if "access" in entity.raw:
        return None
    plural = pluralize(_phrase(entity.name))
    options = [Option("granted", "what each role's grants allow")]
    owners = [entity.entity.owner] if entity.entity.owner else []
    owners += [name for name in entity.users if name not in owners]
    options += [
        Option(f"owned:{path}", f"only its {_phrase(path)}, each their own") for path in owners
    ]
    options.append(Option("authenticated", "any signed-in user"))
    if staff is not None:
        suffix = "" if staff == PUBLIC_READ_WRITER else f":{staff}"
        options += [
            Option(f"public-read{suffix}", f"anyone sees them, only {staff} change them"),
            Option(
                f"public-create{suffix}",
                f"anyone creates them (a public form), only {staff} see and change them",
            ),
            Option("staff" if staff == "staff" else f"role:{staff}", f"only {staff}"),
        ]
    return Question(
        id=f"{entity.id}.access",
        area="access",
        question=f"Who may see and change {plural}?",
        key=f"{entity.key}.access",
        options=tuple(options),
        default="granted",
        target=(*entity.path, "access"),
    )


def _grants(role: schema.Role) -> str:
    if not role.grants:
        return "no grants"
    return "grants " + ", ".join(f"{pattern} {scope}" for pattern, scope in role.grants.items())


def _default_role(spec: schema.Spec, data: dict[str, Any]) -> Question | None:
    raw = _mapping(data.get("roles"))
    if not spec.roles or any("default" in _mapping(role) for role in raw.values()):
        return None
    open_roles = [(slug, role) for slug, role in spec.roles.items() if not role.system]
    if not open_roles:
        return None
    # the least the role grants: fewest "all" scopes, then fewest grants, then the spec's order
    least = min(
        enumerate(open_roles),
        key=lambda item: (
            sum(scope == "all" for scope in item[1][1].grants.values()),
            len(item[1][1].grants),
            item[0],
        ),
    )[1][0]
    options = [
        Option(slug, f"{role.name or role_name(slug)}, {_grants(role)}")
        for slug, role in open_roles
    ]
    options.append(Option(NO_ROLE, "no role, staff give each account its role"))
    return Question(
        id="roles.default",
        area="roles",
        question=(
            "Which role does someone who signs up get: "
            + _either([slug for slug, _ in open_roles] + [NO_ROLE])
            + "?"
        ),
        key="roles.<role>.default",
        options=tuple(options),
        default=least,
    )


_KINDS: Final = (
    Option("app", "React screens behind sign-in"),
    Option("site", "public pages the server renders"),
    Option("site+app", "both, a public site and an app"),
)


def _kind(data: dict[str, Any]) -> Question | None:
    if "kind" in _mapping(data.get("app")):
        return None
    return Question(
        id="app.kind",
        area="app",
        question="What kind of project is it: an app, a public site or both?",
        key="app.kind",
        options=_KINDS,
        default="app",
        target=("app", "kind"),
    )


def _module_asks(name: str, module: KnownModule, raw: dict[str, Any]) -> Iterable[Question]:
    prefix = f"KARNI_{name.upper()}_"
    for ask in module.asks:
        option = ask.setting[len(prefix) :].lower() if ask.setting.startswith(prefix) else ""
        if option not in module.options or option in raw:
            continue
        yield Question(
            id=f"modules.{name}.{option}",
            area="modules",
            question=_ask_text(module.title, ask.question),
            key=f"modules.{name}.{option}",
            options=tuple(Option(value, _show(value)) for value in ask.options),
            default=ask.default if ask.has_default else None,
            types=module.options[option],
            multiple=ask.multiple,
            target=("modules", name, option),
        )


def _feature_asks(
    name: str, feature: KnownFeature, value: Any, raw: dict[str, Any]
) -> Iterable[Question]:
    if not isinstance(value, BaseModel):
        return  # true/false or a list: the key itself answers the feature's asks
    for ask in feature.asks:
        head, dot, sub = ask.setting.partition(".")
        if head != feature.switch or not dot or sub not in type(value).model_fields or sub in raw:
            continue
        types = sorted({_json_type(option) for option in ask.options}) or ["string"]
        yield Question(
            id=f"features.{name}.{sub}",
            area="features",
            question=_ask_text(feature.title, ask.question),
            key=f"features.{name}.{sub}",
            options=tuple(Option(option, _show(option)) for option in ask.options),
            default=ask.default if ask.has_default else None,
            types=tuple(types),
            multiple=ask.multiple,
            target=("features", name, sub),
        )


def questions(spec: schema.Spec, data: dict[str, Any]) -> list[Question]:
    """Experimental. Every gap of a valid spec, as a question, most impact first.

    ``spec`` is the validated spec and ``data`` the file's own data
    (:attr:`karni_cli.spec.validate.Report.source`), which says which keys
    are written: a default the spec fills in is not an answer.
    """
    entities = _entities(spec, data)
    staff = _staff(spec)
    found: list[Question | None] = [_owner(entity) for entity in entities]
    found += [_access(entity, staff) for entity in entities]
    found += [_default_role(spec, data), _kind(data)]
    raw_modules = _mapping(data.get("modules"))
    names = [name for name in raw_modules if name in MODULES]
    if spec.app.kind != "app" and "site" in MODULES and "site" not in names:
        names.append("site")
    for name in names:
        found += _module_asks(name, MODULES[name], _mapping(raw_modules.get(name)))
    raw_features = _mapping(data.get("features"))
    for name in schema.Features.model_fields:
        value = getattr(spec.features, name)
        if name in FEATURES and name in raw_features and value:
            found += _feature_asks(name, FEATURES[name], value, _mapping(raw_features[name]))
    return [question for question in found if question is not None]


def shown(found: list[Question], limit: int | None) -> list[Question]:
    """Experimental. The first ``limit`` questions (all of them for ``None`` or ``0``)."""
    return found[:limit] if limit else list(found)


# output -----------------------------------------------------------------------------


def render(found: list[Question], limit: int | None, *, file: str = "karni.yaml") -> str:
    """Experimental. What ``karni plan --questions`` prints."""
    if not found:
        return (
            f"No questions: {file} settles everything Karni asks before a build.\n"
            "next: karni build\n"
        )
    asked = shown(found, limit)
    count = f"{len(asked)} of {len(found)}" if len(asked) < len(found) else str(len(found))
    noun = "question" if len(found) == 1 else "questions"
    lines = [f"{count} {noun} for the user before karni build, most impact first:"]
    for number, question in enumerate(asked, 1):
        lines += question.lines(number)
    lines.append(
        f"next: ask the user only these, then karni spec answer <id> <value> for each (or edit "
        f"{file}), and karni plan --questions again."
    )
    return "\n".join(lines) + "\n"


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Scalar = str | int | float | bool | None


class _IssueOut(_Out):
    """A problem in the spec, as karni spec validate --json reports it."""

    code: str = Field(description="The error code (karni explain <code>).")
    line: int | None = Field(description="The 1-based line, when known.")
    path: str = Field(description="The dotted path of the key.")
    message: str = Field(description="What is wrong.")
    fix: str = Field(description="How to fix it.")


class _OptionOut(_Out):
    value: Scalar = Field(description="The value karni spec answer takes and writes.")
    label: str = Field(description="What it means, in plain words.")


class _QuestionOut(_Out):
    """One question for the user."""

    id: str = Field(description="Stable for the same gap: karni spec answer <id> <value>.")
    area: Area = Field(description="The kind of gap, most impact first: " + ", ".join(AREAS) + ".")
    question: str = Field(description="One sentence to ask the user.")
    options: list[_OptionOut] = Field(
        description="The answers to choose from. Empty: a free value of one of types."
    )
    default: Scalar | list[Scalar] = Field(
        description="The answer when the user has no preference. null when there is none."
    )
    multiple: bool = Field(description="true: the answer is several options, comma-separated.")
    types: list[str] = Field(description="The JSON types the value takes.")
    key: str = Field(description="The dotted path of the karni.yaml key the answer sets.")


class _QuestionsOut(_Out):
    """Experimental. The output of karni plan --questions --json."""

    version: Literal[1] = Field(description="The version of this output: 1.")
    file: str = Field(description="The spec file, as given.")
    valid: bool = Field(description="false when the spec has problems: then issues lists them.")
    issues: list[_IssueOut] = Field(description="The spec's problems (karni spec validate's).")
    questions: list[_QuestionOut] = Field(
        description="The questions to ask, most impact first, at most max of them."
    )
    total: int = Field(description="How many questions the spec leaves open in all.")
    max: int | None = Field(description="The cap (--max). null: no cap (--max 0).")


def json_schema() -> dict[str, Any]:
    """Experimental. The JSON Schema of ``karni plan --questions --json``."""
    from karni_cli.spec.schema import _tidy

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": QUESTIONS_SCHEMA_URL,
        "title": "karni plan --questions --json",
        "description": (
            "Experimental. The questions to ask the user before karni build. Generated by "
            "python -m karni_cli.spec.questions. Never edit it by hand."
        ),
        **_tidy(_QuestionsOut.model_json_schema()),
    }


def checked_output(data: dict[str, Any]) -> dict[str, Any]:
    """``data`` checked against the published schema's models (raises when they disagree)."""
    return _QuestionsOut.model_validate(data).model_dump(mode="json")


def output(found: list[Question], limit: int | None, *, file: str) -> dict[str, Any]:
    """Experimental. The ``--json`` output of a valid spec."""
    return checked_output(
        {
            "version": QUESTIONS_VERSION,
            "file": file,
            "valid": True,
            "issues": [],
            "questions": [question.as_dict() for question in shown(found, limit)],
            "total": len(found),
            "max": limit or None,
        }
    )


def invalid_output(
    file: str, issues: Iterable[dict[str, Any]], limit: int | None
) -> dict[str, Any]:
    """The ``--json`` output for a spec with problems: no questions."""
    return checked_output(
        {
            "version": QUESTIONS_VERSION,
            "file": file,
            "valid": False,
            "issues": list(issues),
            "questions": [],
            "total": 0,
            "max": limit or None,
        }
    )


@dataclass(frozen=True)
class Answered:
    """Experimental. An answer written into a spec's text (``karni spec answer``)."""

    #: The spec's text with the answer in it. Every other line is as it was.
    text: str
    #: The dotted keys the answer set.
    keys: tuple[str, ...]
    #: How many questions are open after it.
    open: int


def answer(
    text: str, found: list[Question], question_id: str, value: str, *, file: str
) -> Answered:
    """Experimental. ``karni spec answer``: the answer to ``question_id`` written into ``text``.

    ``found`` is :func:`questions` of the valid spec ``text`` holds, and
    ``value`` the answer as typed. Nothing is written to disk here.

    :raises CliError: ``C400`` when ``question_id`` is not an open question,
        ``C401`` when the question does not take ``value``, ``C402`` when the
        answer cannot be written without changing anything else, or would
        make the spec invalid.
    """
    by_id = {question.id: question for question in found}
    question = by_id.get(question_id)
    if question is None:
        open_ids = ", ".join(by_id) or "none"
        raise CliError(
            f"{question_id!r} is not an open question of {file} (open: {open_ids}). An "
            "answered question is gone: karni plan --questions lists the open ones.",
            code="C400",
        )
    try:
        parsed = question.parse(value)
        writes = question.writes(parsed)
    except AnswerError as exc:
        raise CliError(str(exc), code="C401") from None
    try:
        changed = set_values(text, writes)
    except EditError as exc:
        raise CliError(
            f"{file}: the answer to {question_id} cannot be written without changing anything "
            f"else: {exc} Nothing was written. Set {question.key} by hand.",
            code="C402",
        ) from None
    after = validate_text(changed)
    if not after.ok or after.spec is None or after.source is None:
        problems = " ".join(issue.render(file) for issue in after.issues)
        raise CliError(
            f"{file}: the answer to {question_id} would make the spec invalid ({problems}). "
            f"Nothing was written. Set {question.key} by hand.",
            code="C402",
        )
    keys = tuple(".".join(str(part) for part in where) for where, _ in writes)
    return Answered(changed, keys, len(questions(after.spec, after.source.data)))


if __name__ == "__main__":  # pragma: no cover - python -m karni_cli.spec.questions
    print(json.dumps(json_schema(), indent=2, sort_keys=False))
