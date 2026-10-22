"""Recognise a Karni failure in pasted text: a traceback, a test failure or a log line.

``karni explain -`` (and the ``explain_text`` MCP tool) reads what a
developer or an agent would otherwise read by hand and answers with the
failure class, the cause, where it happened (the innermost project frame),
the fix and the docs link. :func:`diagnose` does the work; it never guesses:
text that no pattern recognises is reported as such, with the generic next
step.

Sources of identification, most specific first (:data:`PATTERNS`):

1. a registered code in the text (``E104: …``, ``(karni.E101)``,
   ``error: C012: …``, ``PAY004: …``, a ``…/errors/#e117`` link);
2. an agent rule (``K101 [model-base]``), an architecture violation
   (``[model-base] path:12:``) or an ESLint rule id (``karni/no-raw-elements``);
3. query-count failures: Django's ``assertNumQueries``, pytest-django's
   ``django_assert_num_queries``, a budget warning or the dev query log
   (each points at ``karni queries``);
4. session-mode CSRF and CORS refusals;
5. access outcomes: a 404 or 403 from a Karni viewset, a request without
   credentials (each points at ``karni why``);
6. the framework-adjacent failures Karni documents: a missing database
   driver (C012), an unreachable database (C013), missing or unapplied
   migrations, settings that are not configured, a missing environment
   variable, a host not in ``ALLOWED_HOSTS``, Redis not running, OpenAPI
   schema warnings.

Stdlib only, like the rest of :mod:`karni.errorcodes`: karni-cli loads this
module by path, so ``karni explain -`` works without Django and without a
project.

Override / escape hatch: :func:`diagnose` takes ``patterns=`` (extend or
replace :data:`PATTERNS`; a pattern is any callable ``(Text) -> list[Finding]``),
``lookup=`` (how a code becomes its entry) and ``rules=`` (the agent rules
that enforcement ids map to).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from . import DOCS_BASE_URL
from . import get as _core_get

__all__ = [
    "CLASSES",
    "DOCS_PAGE",
    "PATTERNS",
    "WHY_COMMAND",
    "Diagnosis",
    "Finding",
    "Frame",
    "Pattern",
    "Text",
    "class_url",
    "diagnose",
    "parse_frames",
]

#: The page every failure class without a code links to (``docs/debugging/explain.md``).
DOCS_PAGE: Final[str] = "debugging/explain/"
#: How an access outcome is handed to ``karni why`` (the access-decision explainer).
WHY_COMMAND: Final[str] = "karni why {path} --as <user>{method}"
#: How a query-count failure is handed to ``karni queries``.
QUERIES_COMMAND: Final[str] = "karni queries {endpoint} --as <user>"
#: Findings shown at most (the rest are dropped, most specific first).
MAX_FINDINGS: Final[int] = 5

Lookup = Callable[[str], Mapping[str, str] | None]


def class_url(anchor: str) -> str:
    """The docs link of a failure class without a code (``…/debugging/explain/#<anchor>``)."""
    return f"{DOCS_BASE_URL}{DOCS_PAGE}#{anchor}"


# frames


@dataclass(frozen=True)
class Frame:
    """One stack frame named in the text: ``path:line in function``."""

    path: str
    line: int
    function: str = ""
    #: ``project`` (your code), ``karni`` (Karni or a Karni module) or ``library``.
    kind: str = "project"

    def location(self, root: Path | None = None) -> str:
        shown = _short(self.path, root)
        return (
            f"{shown}:{self.line} in {self.function}" if self.function else f"{shown}:{self.line}"
        )


_KARNI_PATH = re.compile(
    r"(?:site|dist)-packages/karni(?:_[a-z]+)?/"
    r"|/packages/karni/karni/|/packages/karni-cli/karni_cli/|/modules/karni-[a-z-]+/karni_[a-z_]+/"
)
_LIBRARY_PATH = re.compile(r"(?:site|dist)-packages/|/lib/python3\.\d+/|^<|\\Lib\\")
_PY_FRAME = re.compile(r'^\s*File "(?P<path>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)')
_PYTEST_FRAME = re.compile(r"^(?P<path>[^\s:]+\.py):(?P<line>\d+): in (?P<func>\S+)\s*$")
_PYTEST_RAISE = re.compile(r"^(?P<path>[^\s:]+\.py):(?P<line>\d+): (?P<func>[A-Z]\w*)\s*$")
_PYTEST_BARE = re.compile(r"^(?P<path>[^\s:]+\.py):(?P<line>\d+): ?$")
_RICH_FRAME = re.compile(
    r"^\s*(?P<path>/\S+\.py|[\w.\-]+(?:/[\w.\-]+)+\.py):(?P<line>\d+) in (?P<func>\S+)"
)
_ORIGIN = re.compile(r"\((?P<path>[\w./\-]+\.py):(?P<line>\d+) in (?P<func>[\w<>]+)\)")


def _kind(path: str) -> str:
    normal = path.replace("\\", "/")
    if _KARNI_PATH.search(normal):
        return "karni"
    if _LIBRARY_PATH.search(normal) or normal.startswith("<"):
        return "library"
    return "project"


def _short(path: str, root: Path | None) -> str:
    """An installed package's path from its import root; a project path from the root."""
    match = re.search(r"(?:site|dist)-packages/(.+)$", path) or re.search(
        r"/(?:packages/karni|packages/karni-cli|modules/karni-[a-z-]+)/(karni(?:_[a-z]+)?/.+)$",
        path,
    )
    if match:
        return match.group(1)
    if root is not None and path.startswith("/"):
        try:
            return Path(path).relative_to(root).as_posix()
        except ValueError:
            pass
    return path


def parse_frames(text: str) -> list[Frame]:
    """Every frame the text names, outermost first (Python, pytest and rich layouts)."""
    frames: list[Frame] = []
    for line in text.splitlines():
        match = (
            _PY_FRAME.match(line)
            or _PYTEST_FRAME.match(line)
            or _PYTEST_RAISE.match(line)
            or _PYTEST_BARE.match(line)
            or _RICH_FRAME.match(line)
        )
        if match:
            path = match.group("path")
            func = match.groupdict().get("func") or ""
            if _PYTEST_RAISE.match(line):
                func = ""  # ``path:870: QueryBudgetExceeded`` names the exception, not a function
            frames.append(Frame(path, int(match.group("line")), func, _kind(path)))
    return frames


# the text


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_BOX = re.compile(r"[│╭╮╰╯─┃━┏┓┗┛❱]")
_PYTEST_E = re.compile(r"^E {2,}", re.MULTILINE)
_EXCEPTION = re.compile(
    r"^(?:E\s+)?(?P<name>(?:[A-Za-z_]\w*\.)*[A-Z]\w*(?:Error|Exception|Exceeded|Configured"
    r"|NotReady|DoesNotExist|DisallowedHost|Failed|Missing|Denied|Exit))(?::\s*(?P<message>.*))?$"
)


@dataclass
class Text:
    """The pasted text, normalised once for every pattern."""

    raw: str
    #: Project root: frames under it are project frames, shown relative to it.
    root: Path | None = None
    plain: str = ""
    #: Whitespace collapsed (messages wrapped over several lines read as one).
    flat: str = ""
    frames: list[Frame] = field(default_factory=list)
    exception: str = ""

    def __post_init__(self) -> None:
        plain = _ANSI.sub("", self.raw).replace("\r\n", "\n")
        plain = _BOX.sub(" ", plain)
        self.plain = _PYTEST_E.sub("", plain)
        self.flat = " ".join(self.plain.split())
        self.frames = [self._rooted(frame) for frame in parse_frames(self.plain)]
        self.exception = self._last_exception()

    def _rooted(self, frame: Frame) -> Frame:
        """With a known root, an absolute path outside it is not project code."""
        if self.root is None or frame.kind != "project" or not frame.path.startswith("/"):
            return frame
        try:
            Path(frame.path).relative_to(self.root)
        except ValueError:
            return Frame(frame.path, frame.line, frame.function, "library")
        return frame

    def _last_exception(self) -> str:
        found = ""
        for line in self.plain.splitlines():
            match = _EXCEPTION.match(line.strip())
            if match:
                found = line.strip()
        return found

    def where(self) -> Frame | None:
        """The innermost project frame, else the innermost Karni frame.

        ``manage.py`` only starts the command: when it is the one project frame
        and Karni code ran below it, the Karni frame says more.
        """
        project = next((f for f in reversed(self.frames) if f.kind == "project"), None)
        karni = next((f for f in reversed(self.frames) if f.kind == "karni"), None)
        if project is not None and karni is not None and project.path.endswith("manage.py"):
            if self.frames.index(karni) > self.frames.index(project):
                return karni
        return project or karni

    def raised(self) -> Frame | None:
        """The innermost Karni frame (where Karni raised), if any."""
        for frame in reversed(self.frames):
            if frame.kind == "karni":
                return frame
        return None

    def search(self, pattern: str | re.Pattern[str]) -> re.Match[str] | None:
        """Search the whitespace-collapsed text (a wrapped message reads as one line)."""
        return re.search(pattern, self.flat)

    def search_lines(self, pattern: str | re.Pattern[str]) -> re.Match[str] | None:
        """Search line by line (for patterns that run to the end of a line)."""
        compiled = pattern if isinstance(pattern, re.Pattern) else re.compile(pattern, re.M)
        return compiled.search(self.plain)

    def location(self, frame: Frame | None) -> str:
        return frame.location(self.root) if frame is not None else ""


# findings


@dataclass(frozen=True)
class Finding:
    """One recognised failure: its class, the specific cause, where, the fix and the link."""

    key: str
    title: str
    cause: str
    fix: str
    docs: str
    code: str = ""
    where: str = ""
    #: A follow-up command that answers the rest (``karni queries …``, ``karni why …``).
    next: str = ""
    #: Why Karni behaves this way (from the registry entry, when there is one).
    why: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "class": self.key,
            "code": self.code,
            "title": self.title,
            "cause": self.cause,
            "where": self.where,
            "fix": self.fix,
            "next": self.next,
            "why": self.why,
            "docs": self.docs,
        }


@dataclass(frozen=True)
class Diagnosis:
    """What :func:`diagnose` found: findings (most specific first), or none."""

    findings: tuple[Finding, ...]
    exception: str
    where: str
    raised: str
    #: Side findings that do not explain the exception (repeated queries in a dev log
    #: printed next to a traceback); shown after the answer.
    also: tuple[Finding, ...] = ()

    @property
    def recognised(self) -> bool:
        return bool(self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "recognised": self.recognised,
            "exception": self.exception,
            "where": self.where,
            "raised_in": self.raised,
            "findings": [finding.as_dict() for finding in self.findings],
            "also": [finding.as_dict() for finding in self.also],
            "next": "" if self.recognised else _UNKNOWN_NEXT,
        }

    def render(self) -> str:
        """The text ``karni explain -`` prints."""
        if not self.findings:
            what = self.exception or "the text has no exception line"
            lines = [f"Not a failure Karni recognises: {what}"]
            if self.where:
                lines.append(f"Where: {self.where}")
            lines.append(f"Next:  {_UNKNOWN_NEXT}")
            blocks = ["\n".join(lines)]
        else:
            blocks = [_block(finding) for finding in self.findings]
        if self.also:
            blocks.append("Also in the text:")
            blocks.extend(_block(finding) for finding in self.also)
        return "\n\n".join(blocks)


def _block(finding: Finding) -> str:
    head = f"{finding.code}  {finding.title}" if finding.code else finding.title
    rows = [f"Class: {head}", f"Cause: {finding.cause}"]
    if finding.where:
        rows.append(f"Where: {finding.where}")
    if finding.why:
        rows.append(f"Why:   {finding.why}")
    rows.append(f"Fix:   {finding.fix}")
    if finding.next:
        rows.append(f"Next:  {finding.next}")
    rows.append(f"Docs:  {finding.docs}")
    return "\n".join(rows)


_UNKNOWN_NEXT = (
    "Karni does not know this failure, so it will not guess. Read the innermost project frame "
    "(Where) and the exception's own message. `karni doctor` checks the environment and "
    "`karni check` the declarations."
)


def _clip(text: str, width: int = 320) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


#: A pattern: ``(text, context) -> findings``.
Pattern = Callable[["Text", "_Context"], list[Finding]]


@dataclass(frozen=True)
class _Context:
    lookup: Lookup
    rules: tuple[Mapping[str, Any], ...]

    def entry(self, code: str) -> Mapping[str, str] | None:
        try:
            return self.lookup(code)
        except Exception:  # noqa: BLE001 - a broken registry must not break explain
            return None

    def rule(self, code: str) -> Mapping[str, Any] | None:
        return next((rule for rule in self.rules if rule.get("code") == code), None)

    def rule_for(self, enforcement_id: str) -> Mapping[str, Any] | None:
        return next(
            (rule for rule in self.rules if enforcement_id in (rule.get("enforced_by") or ())),
            None,
        )


def _finding(
    text: Text,
    key: str,
    title: str,
    cause: str,
    fix: str,
    *,
    frame: Frame | None = None,
    next_step: str = "",
    code: str = "",
    ctx: _Context | None = None,
) -> Finding:
    """A finding for a class; with ``code`` the registered entry supplies why and the link."""
    docs = class_url(key)
    why = ""
    if code and ctx is not None:
        entry = ctx.entry(code)
        if entry is not None:
            docs = entry.get("url", docs)
            why = entry.get("why", "")
    where = text.location(frame if frame is not None else text.where())
    return Finding(key, title, _clip(cause), fix, docs, code, where, next_step, why)


# 1. registered codes

#: ``E104: …`` at the start of a line or after ``<Exception>: `` / ``error: ``.
_CODE_COLON = re.compile(r"(?:^\s*|: )(?P<code>[A-Z]{1,5}\d{3}): (?P<message>\S.*)")
_CHECK_ID = re.compile(r"\(?karni\.(?P<code>[EW]\d{3})\)?:?\s*(?P<message>.*)")
_DOCS_LINK = re.compile(r"/errors/#(?P<code>[a-z]{1,5}\d{3})\b")
#: Codes that summarise other failures; the specific ones are listed first.
_SUMMARY_CODES = frozenset({"E702", "C009"})
_BUDGET_CODES = frozenset({"E117", "E129"})


_MESSAGE_END = ("See http", "HINT:", "Traceback", "File ", "During handling", "The above")


def _code_message(lines: list[str], index: int, start: int) -> str:
    """The message after the code, with its continuation lines (a multi-line report)."""
    parts = [lines[index][start:]]
    for line in lines[index + 1 : index + 7]:
        stripped = line.strip()
        if not stripped or stripped.startswith(_MESSAGE_END) or _CODE_COLON.match(line):
            break
        parts.append(stripped)
    message = " ".join(parts)
    return re.split(r"\s+See https?://\S+/errors/#", message)[0].strip()


def _codes(text: Text, ctx: _Context) -> list[Finding]:
    seen: dict[str, str] = {}
    lines = text.plain.splitlines()
    for index, line in enumerate(lines):
        for match in _CODE_COLON.finditer(line):
            seen.setdefault(
                match.group("code"), _code_message(lines, index, match.start("message"))
            )
        for match in _CHECK_ID.finditer(line):
            if "karni." in match.group(0):
                seen.setdefault(match.group("code"), match.group("message").strip())
    for match in _DOCS_LINK.finditer(text.plain):
        seen.setdefault(match.group("code").upper(), "")
    findings: list[Finding] = []
    for code, message in seen.items():
        if code.startswith("K"):
            continue  # agent rules: _rules()
        entry = ctx.entry(code)
        if entry is None:
            continue
        if code in _BUDGET_CODES:
            findings.extend(_budget(text, code, message, ctx, entry))
            continue
        cause = message or entry.get("title", "")
        findings.append(
            Finding(
                key=f"code-{code.lower()}",
                title=entry.get("title", code),
                cause=_clip(cause),
                fix=entry.get("fix", ""),
                docs=entry.get("url", ""),
                code=code,
                where=text.location(text.where()),
                why=entry.get("why", ""),
            )
        )
    return findings


# query budgets and counts

_RAN = re.compile(
    r"(?P<label>(?P<viewset>\w+)\.(?P<action>\w+)) ran (?P<count>\d+) queries"
    r"(?: against a budget of|; budget is) (?P<limit>\d+)"
)
_GROWS = re.compile(
    r"(?P<viewset>\w+)\.(?P<action>\w+)(?P<query>\?\S+)?: (?P<small>\d+) queries with \d+ rows, "
    r"(?P<large>\d+) with \d+"
)
_REPEAT = re.compile(r"^\s*(?P<count>\d+)× (?P<sql>.+)$")
_FROM = re.compile(r"\bFROM\s+[\"`\[]?(?P<table>[\w.]+)", re.IGNORECASE)
_ARROW = re.compile(r"^\s*← (?P<origin>.+)$")


def _repeats(text: Text, after: str = "") -> list[tuple[int, str, str]]:
    """``(count, table, origin)`` per duplicate group of a Karni query report.

    With ``after``, only the report that follows the first line containing it
    (a pasted test run can hold several reports).
    """
    found: list[tuple[int, str, str]] = []
    seen: set[tuple[str, str]] = set()
    lines = text.plain.splitlines()
    start = next((i for i, line in enumerate(lines) if after and after in line), -1)
    if after and start < 0:
        return found
    for index in range(start + 1, len(lines)):
        line = lines[index]
        match = _REPEAT.match(line)
        if not match:
            if after and found and not _ARROW.match(line):
                break  # the report ended
            continue
        table = _FROM.search(match.group("sql"))
        origin = ""
        if index + 1 < len(lines):
            arrow = _ARROW.match(lines[index + 1])
            origin = _strip_log_tail(arrow.group("origin")) if arrow else ""
        name = table.group("table") if table else "?"
        if (name, origin) not in seen:
            seen.add((name, origin))
            found.append((int(match.group("count")), name, origin))
    return found


def _strip_log_tail(origin: str) -> str:
    """``EventSerializer.x (a.py:3 in f) [karni.queries]`` → without the logger tail."""
    return re.sub(r"\s*\[[\w.]+\]\s*.*$", "", origin).strip()


def _describe_repeats(repeats: Sequence[tuple[int, str, str]]) -> str:
    parts = []
    for count, table, origin in repeats[:3]:
        parts.append(f"{count}× {table}" + (f" from {origin}" if origin else ""))
    return ", ".join(parts)


def _origin_frame(repeats: Sequence[tuple[int, str, str]]) -> Frame | None:
    for _count, _table, origin in repeats:
        match = _ORIGIN.search(origin)
        if match:
            return Frame(match.group("path"), int(match.group("line")), match.group("func"))
    return None


_BUDGET_FIX = (
    "Run the `karni queries` command below: it attributes every repeated query to the serializer "
    "field, method or property that issued it and prints the exact hint (select_related / "
    "prefetch_related on the viewset, APIMeta.select / prefetch on the model, or an annotation "
    "for an aggregate). Raise the budget only for work that is real: query_budget = "
    "Budget(<action>=N, reason=...)."
)


def _endpoint_of(viewset: str, action: str, query: str = "") -> str:
    endpoint = f"{viewset}.{action}{query}"
    return f"'{endpoint}'" if query else endpoint


def _budget(
    text: Text, code: str, message: str, ctx: _Context, entry: Mapping[str, str]
) -> list[Finding]:
    # The first sentence; the report that follows it is summarised below.
    head = re.split(r"(?<=\.)\s+", message, maxsplit=1)[0] if message else ""
    repeats = _repeats(text, after=head.rstrip(".")) if head else _repeats(text)
    next_step = ""
    if code == "E129":
        grows = text.search(_GROWS)
        if grows:
            next_step = QUERIES_COMMAND.format(
                endpoint=_endpoint_of(grows["viewset"], grows["action"], grows["query"] or "")
            )
    else:
        ran = text.search(_RAN)
        if ran:
            next_step = QUERIES_COMMAND.format(endpoint=_endpoint_of(ran["viewset"], ran["action"]))
    cause = head or entry.get("title", "")
    if repeats:
        cause = f"{cause} Repeated: {_describe_repeats(repeats)}."
    frame = _origin_frame(repeats) or text.where()
    return [
        Finding(
            key=f"code-{code.lower()}",
            title=entry.get("title", code),
            cause=_clip(cause, 480),
            fix=_BUDGET_FIX,
            docs=entry.get("url", ""),
            code=code,
            where=text.location(frame),
            next=next_step,
            why=entry.get("why", ""),
        )
    ]


_NUM_QUERIES = re.compile(r"(?P<done>\d+) != (?P<expected>\d+) : \1 queries executed, \2 expected")
_PYTEST_DJANGO = re.compile(
    r"Expected to perform (?P<expected>\d+) quer(?:y|ies) but (?P<done>\d+) were done"
)
_CAPTURED = re.compile(r"^\s*\d+\. (?P<sql>(?:SELECT|INSERT|UPDATE|DELETE)\b.+)$", re.IGNORECASE)
_LITERAL = re.compile(r"'(?:[^']|'')*'|\b\d+(?:\.\d+)?\b")
_CLIENT_CALL = re.compile(
    r"\.(?P<method>get|post|put|patch|delete)\(\s*f?[\"'](?P<path>/[^\"'{]*)[\"']"
)
_DEV_LOG = re.compile(
    r"(?P<method>GET|POST|PUT|PATCH|DELETE) (?P<path>/\S*) (?P<status>\d{3})(?::| —) "
    r"(?P<count>\d+) queries, (?P<dups>\d+) duplicated"
)


def _captured_repeats(text: Text) -> list[tuple[int, str, str]]:
    groups: Counter[str] = Counter()
    for line in text.plain.splitlines():
        match = _CAPTURED.match(line)
        if match:
            groups[_LITERAL.sub("?", match.group("sql"))] += 1
    found = []
    for sql, count in groups.most_common():
        if count > 1:
            table = _FROM.search(sql)
            found.append((count, table.group("table") if table else "?", ""))
    return found


def _query_counts(text: Text, ctx: _Context) -> list[Finding]:
    match = text.search(_NUM_QUERIES) or text.search(_PYTEST_DJANGO)
    if match:
        repeats = _captured_repeats(text)
        call = text.search(_CLIENT_CALL)
        endpoint = call["path"] if call else "<the endpoint the test requests>"
        cause = f"The block ran {match['done']} queries, but the test expects {match['expected']}."
        if repeats:
            cause += f" Repeated: {_describe_repeats(repeats)}."
        return [
            _finding(
                text,
                "query-count",
                "A query-count assertion failed (likely an N+1)",
                cause,
                _BUDGET_FIX,
                next_step=QUERIES_COMMAND.format(endpoint=endpoint),
            )
        ]
    ran = text.search(_RAN)
    if ran and "E117" not in text.flat:
        repeats = _repeats(text, after=ran.group(0))
        cause = f"{ran['label']} ran {ran['count']} queries against a budget of {ran['limit']}."
        if repeats:
            cause += f" Repeated: {_describe_repeats(repeats)}."
        return [
            _finding(
                text,
                "query-budget-warning",
                "A request ran more SQL queries than its budget (dev warning)",
                cause,
                _BUDGET_FIX,
                frame=_origin_frame(repeats),
                next_step=QUERIES_COMMAND.format(
                    endpoint=_endpoint_of(ran["viewset"], ran["action"])
                ),
                code="E117",
                ctx=ctx,
            )
        ]
    log = text.search(_DEV_LOG)
    if log and int(log["dups"]) > 0:
        repeats = _repeats(text, after=log.group(0))
        cause = (
            f"{log['method']} {log['path']} ran {log['count']} queries, {log['dups']} of them "
            "repeated statements (the dev query log)."
        )
        if repeats:
            cause += f" Repeated: {_describe_repeats(repeats)}."
        method = "" if log["method"] == "GET" else f" --method {log['method']}"
        return [
            _finding(
                text,
                "query-log-duplicates",
                "Repeated queries in the dev query log (an N+1)",
                cause,
                _BUDGET_FIX,
                frame=_origin_frame(repeats),
                next_step=QUERIES_COMMAND.format(endpoint=log["path"]) + method,
            )
        ]
    return []


# 2. agent rules, architecture and ESLint ids

_RULE_CODE = re.compile(r"(?<![\w-])(?P<code>K\d{3}) \[(?P<id>[a-z][a-z-]+)\]")
_VIOLATION = re.compile(r"\[(?P<id>[a-z]+(?:-[a-z]+)+)\] (?P<where>[^\s:]+:\d+)")
_ESLINT = re.compile(r"(?<![\w@/-])(?P<id>karni/[a-z]+(?:-[a-z]+)*)\b")


def _rules(text: Text, ctx: _Context) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()

    def add(rule: Mapping[str, Any] | None, enforcement: str, where: str) -> None:
        if rule is None or rule["code"] in seen:
            return
        seen.add(str(rule["code"]))
        anchor = enforcement.replace("/", "-") if enforcement.startswith("karni/") else ""
        docs = (
            f"{DOCS_BASE_URL}errors/#{anchor}"
            if anchor
            else f"{DOCS_BASE_URL}errors/#{str(rule['code']).lower()}"
        )
        findings.append(
            Finding(
                key=f"rule-{str(rule['code']).lower()}",
                title=f"Agent rule {rule['code']}: {rule.get('summary', '')}",
                cause=_clip(f"[{enforcement}] {rule.get('rule', '')}"),
                fix=str(rule.get("fix") or rule.get("rule", "")),
                docs=docs,
                code=str(rule["code"]),
                where=where,
                why=str(rule.get("rationale", "")),
            )
        )

    for match in _RULE_CODE.finditer(text.plain):
        add(ctx.rule(match["code"]), match["id"], "")
    for match in _VIOLATION.finditer(text.plain):
        where = match["where"]
        path, _, line = where.rpartition(":")
        add(ctx.rule_for(match["id"]), match["id"], f"{_short(path, text.root)}:{line}")
    for match in _ESLINT.finditer(text.plain):
        add(ctx.rule_for(match["id"]), match["id"], "")
    return findings


# 3. Karni exception classes without a code

_CLASSES: Mapping[str, str] = {
    "QueryBudgetExceeded": "E117",
    "ScopeContextMissing": "E006",
}


def _classes(text: Text, ctx: _Context) -> list[Finding]:
    findings = []
    for name, code in _CLASSES.items():
        match = text.search(rf"\b{name}: (?!{code}:)(?P<message>[^\n]{{0,300}})")
        if match is None:
            continue
        entry = ctx.entry(code)
        if entry is None:
            continue
        if code in _BUDGET_CODES:
            findings.extend(_budget(text, code, match["message"], ctx, entry))
        else:
            findings.append(
                _finding(
                    text,
                    f"code-{code.lower()}",
                    entry["title"],
                    match["message"],
                    entry["fix"],
                    code=code,
                    ctx=ctx,
                )
            )
    return findings


# 4. CSRF and CORS

_CSRF = re.compile(
    r"CSRF Failed: (?P<reason>[^\"}\n]+?)\.?(?=[\"}]|$)|Forbidden \(CSRF (?P<old>[^)]+)\)"
    r"|CSRF verification failed\. Request aborted"
)
_ORIGIN_FAILED = re.compile(
    r"Origin checking failed - (?P<origin>\S+) does not match any trusted origins"
)
_CORS = re.compile(
    r"blocked by CORS policy|No 'Access-Control-Allow-Origin' header|Cross-Origin Request Blocked"
    r"|CORS request did not succeed|Access-Control-Allow-Credentials"
)


def _csrf(text: Text, ctx: _Context) -> list[Finding]:
    match = text.search(_CSRF)
    if match is None:
        return []
    origin = text.search(_ORIGIN_FAILED)
    if origin:
        cause = (
            f"The request came from {origin['origin']}, which is not in CSRF_TRUSTED_ORIGINS. In "
            "session mode Karni trusts the origin of KARNI_FRONTEND_URL, so the SPA must be "
            "served from exactly that origin (scheme, host and port)."
        )
        fix = (
            f"Set KARNI_FRONTEND_URL={origin['origin']} in .env when that is the SPA's origin, or "
            "serve the SPA from the KARNI_FRONTEND_URL origin (the Vite dev proxy keeps one "
            'origin), or add the origin after karni_settings(): CSRF_TRUSTED_ORIGINS += ["…"].'
        )
    else:
        reason = (match["reason"] or match["old"] or "CSRF verification failed").strip()
        cause = (
            f"CSRF refused the write: {reason}. In session mode every unsafe request (POST, PUT, "
            "PATCH, DELETE) needs the csrftoken cookie and the same value in the X-CSRFToken "
            "header."
        )
        fix = (
            "Use @karni/ui's KarniClient (it bootstraps the cookie with GET /api/auth/csrf/ and "
            "sends X-CSRFToken). A hand-written client must do both. In tests, APIClient skips "
            "CSRF unless enforce_csrf_checks=True. JWT mode (KARNI_AUTH_MODE=jwt) has no CSRF."
        )
    return [_finding(text, "csrf", "CSRF check failed (session mode)", cause, fix)]


def _cors(text: Text, ctx: _Context) -> list[Finding]:
    if text.search(_CORS) is None:
        return []
    origin = text.search(r"from origin '(?P<origin>[^']+)'")
    who = f"The page at {origin['origin']}" if origin else "The page"
    return [
        _finding(
            text,
            "cors",
            "The browser blocked a cross-origin API call (CORS)",
            f"{who} called the API on another origin and the response did not allow it. Karni's "
            "dev profile allows every origin. Outside dev, CORS is closed unless "
            "CORS_ALLOWED_ORIGINS lists the origin.",
            "List the SPA's origin in CORS_ALLOWED_ORIGINS (comma-separated, in .env), or serve "
            "the SPA and the API from one origin (a reverse proxy such as the Caddyfile, or the "
            "Vite dev proxy). Session mode across sites also needs SESSION_COOKIE_SAMESITE / "
            "CSRF_COOKIE_SAMESITE = 'None' and HTTPS.",
        )
    ]


# 5. access outcomes

_KARNI_404 = re.compile(
    r"No (?P<model>\w+) matches the given query\. Rows are limited by (?P<viewset>\w+)\.access "
    r"read=(?P<read>.+?)\.?\"?\}"
)
_KARNI_403 = re.compile(
    r"Access denied: this row is readable but the action requires (?P<rule>.+?)\.\"?\}"
)
_DRF_403 = re.compile(r"You do not have permission to perform this action")
_NO_CREDENTIALS = re.compile(
    r"Authentication credentials were not provided|Unauthorized: (?P<path>/\S*)"
)
_ACCESS_LOG = re.compile(
    r"\"(?P<method>GET|POST|PUT|PATCH|DELETE) (?P<path>/\S*) HTTP/[\d.]+\" (?P<status>40[134])"
)
_DJANGO_LOG = re.compile(r"(?P<what>Not Found|Forbidden): (?P<path>/\S+)")


def _why(path: str, method: str) -> str:
    return WHY_COMMAND.format(
        path=path, method="" if method in ("", "GET") else f" --method {method}"
    )


def _request(text: Text) -> tuple[str, str]:
    log = text.search(_ACCESS_LOG)
    if log:
        return log["path"], log["method"]
    django_log = text.search(_DJANGO_LOG)
    return (django_log["path"], "") if django_log else ("<path>", "")


def _access(text: Text, ctx: _Context) -> list[Finding]:
    if text.search(_CSRF):
        return []  # a CSRF 403 is not an access decision
    path, method = _request(text)
    match = text.search(_KARNI_404)
    if match:
        return [
            _finding(
                text,
                "access-404",
                "404 from a Karni viewset: the row is outside the read scope (or does not exist)",
                f"{match['viewset']} answers 404 when the requester cannot read the "
                f"{match['model']} row, exactly as when the row does not exist (so a 404 never "
                f"confirms the row). Its read rule is {match['read'].strip()}.",
                "Check which part of the read rule should admit this user, and whether the row "
                "exists. The command below evaluates the rule for this user and row and names the "
                "predicate that refused it. Change the rule, the user's roles or the row, never "
                "the queryset.",
                next_step=_why(path, method),
            )
        ]
    match = text.search(_KARNI_403)
    if match:
        return [
            _finding(
                text,
                "access-403",
                "403 from a Karni viewset: the row is readable, the action is not allowed",
                f"The requester can read this row but the action requires {match['rule'].strip()}.",
                "Give the user what the rule requires (the owner, a role), or change the write "
                "rule on the viewset's access. The command below shows the decision.",
                next_step=_why(path, method or "PATCH"),
            )
        ]
    if text.search(_NO_CREDENTIALS) and "Authentication credentials were not provided" in text.flat:
        return [
            _finding(
                text,
                "access-unauthenticated",
                "The request carried no credentials",
                f"{path} needs a signed-in user and the request had neither a session cookie "
                "(session mode) nor an Authorization: Bearer token (jwt mode).",
                "Sign in first with POST /api/auth/login/ (KarniClient keeps the session or the "
                "tokens), or in tests authenticate the client (client.force_authenticate(user), "
                "or the role clients of karni.testing.APITestCase). A Public() read rule makes "
                "a read anonymous.",
                next_step=_why(path, method),
            )
        ]
    if text.search(_DRF_403):
        return [
            _finding(
                text,
                "access-denied",
                "403 from a viewset: the access rule refused the request",
                f"The viewset's access declaration refused {method or 'the'} request to {path} "
                "for this user.",
                "See which predicate refused it with the command below. Change the rule or the "
                "user's roles, never the permission classes.",
                next_step=_why(path, method),
            )
        ]
    logged = text.search(_DJANGO_LOG)
    status = text.search(_ACCESS_LOG)
    if logged or status:
        code = (
            status["status"]
            if status
            else ("404" if logged and logged["what"] == "Not Found" else "403")
        )
        return [
            _finding(
                text,
                f"access-{code}",
                f"{code} from {path}",
                f"The server answered {code} for {path}. From a Karni viewset, a 404 also means "
                "a row outside the requester's read scope and a 403 an action the access rule "
                "refuses. From anything else, no route matched (404).",
                "Run the command below for the access decision. `karni routes` lists every "
                "route with its viewset and access.",
                next_step=_why(path, method),
            )
        ]
    return []


# 6. framework-adjacent failures

_DRIVER = re.compile(
    r"Error loading (?P<module>psycopg2 or psycopg|MySQLdb|oracledb|cx_Oracle) module"
    r"|No module named '(?P<missing>psycopg2?|psycopg_binary|MySQLdb|oracledb)'"
)
_UNREACHABLE = re.compile(
    r"(?:OperationalError|InterfaceError): (?P<error>"
    r"(?:connection failed: )?connection to server at [^\n]*"
    r"|failed to resolve host '[^']+'[^\n]*|could not translate host name \"[^\"]+\"[^\n]*"
    r"|could not connect to server[^\n]*|password authentication failed[^\n]*"
    r"|FATAL: +database \"[^\"]+\" does not exist[^\n]*"
    r"|\(2003, \"Can't connect to MySQL server[^\n]*"
    r"|Connection refused[^\n]*)"
)
_HOST = re.compile(
    r"(?:server at \"(?P<a>[^\"]+)\"|resolve host '(?P<b>[^']+)'|host name \"(?P<c>[^\"]+)\")"
)
_NO_TABLE = re.compile(
    r"no such table: (?P<a>[\w.]+)|relation \"(?P<b>[\w.]+)\" does not exist"
    r"|Table '[\w]+\.(?P<c>\w+)' doesn't exist"
)
_NO_COLUMN = re.compile(
    r"no such column: (?P<a>[\w.]+)|column (?P<b>[\w.\"]+) does not exist"
    r"|Unknown column '(?P<c>[\w.]+)'"
)
_MIGRATIONS_FOR = re.compile(r"Migrations for '(?P<app>\w+)':")
_UNAPPLIED = re.compile(
    r"You have (?P<count>\d+) unapplied migration\(s\)\. Your project may not work properly until "
    r"you apply the migrations for app\(s\): (?P<apps>[\w, ]+)\."
)


def _database(text: Text, ctx: _Context) -> list[Finding]:
    findings: list[Finding] = []
    driver = text.search(_DRIVER)
    if driver:
        module = driver["module"] or driver["missing"]
        findings.append(
            _finding(
                text,
                "db-driver",
                "The database driver is not installed",
                f"DATABASE_URL names a server database, and its driver ({module}) is not "
                "installed in the interpreter that ran this. Django loads it as it starts.",
                'Install it into the project interpreter: pip install "psycopg[binary]" for '
                "PostgreSQL (or pip install -e . for every dependency). Or run in Docker "
                "(`karni serve -d`, then --docker), or use DATABASE_URL=sqlite:///db.sqlite3.",
                code="C012",
                ctx=ctx,
            )
        )
    unreachable = text.search_lines(_UNREACHABLE)
    if unreachable:
        host_match = text.search(_HOST)
        host = next((h for h in (host_match.groups() if host_match else ()) if h), "")
        compose = (
            " `db` is the docker compose service name: it resolves only inside the compose "
            "network, not from the host."
            if host == "db"
            else ""
        )
        findings.append(
            _finding(
                text,
                "db-unreachable",
                "The database cannot be reached",
                f"Django could not open a connection: {unreachable['error'].strip()}.{compose}",
                "Start the database (`karni serve -d` runs the compose stack with PostgreSQL), or "
                "point DATABASE_URL in .env at a server that runs (cp .env.example .env first). "
                "DATABASE_URL=sqlite:///db.sqlite3 needs no server.",
                code="C013",
                ctx=ctx,
            )
        )
    table = text.search(_NO_TABLE)
    if table:
        name = next(group for group in table.groups() if group)
        findings.append(
            _finding(
                text,
                "migrations-not-applied",
                "A table is missing: migrations are not applied (or not made)",
                f"The database has no table {name}: the migrations that create it were not "
                "applied to this database, or the model has no migration yet.",
                "Run `karni migrate` (make migrate). If the table belongs to one of your models, "
                "make its migration first: `karni make migration && karni migrate` (rule K003). "
                "In tests, pytest-django builds the test database from the migrations, so a "
                "model without one has no table there either.",
            )
        )
    column = text.search(_NO_COLUMN)
    if column:
        name = next(group for group in column.groups() if group).replace('"', "")
        findings.append(
            _finding(
                text,
                "migration-missing",
                "A column is missing: a model change has no migration (or it is not applied)",
                f"The model has a field the database lacks ({name}): the model changed after the "
                "last migration, or that migration is not applied here.",
                "`karni make migration && karni migrate`, then `karni types` (rule K003).",
            )
        )
    made = text.search(_MIGRATIONS_FOR)
    if made:
        findings.append(
            _finding(
                text,
                "migration-missing",
                "Model changes have no migration",
                f"makemigrations reports changes to the models of '{made['app']}' that no "
                "committed migration records (what `makemigrations --check` fails on).",
                "`karni make migration && karni migrate`, commit the migration, then `karni types` "
                "(rule K003).",
            )
        )
    unapplied = text.search(_UNAPPLIED)
    if unapplied:
        findings.append(
            _finding(
                text,
                "migrations-not-applied",
                "Migrations are not applied",
                f"{unapplied['count']} migration(s) of {unapplied['apps'].strip()} are not "
                "applied to this database.",
                "`karni migrate` (make migrate).",
            )
        )
    return findings


_NOT_CONFIGURED = re.compile(
    r"Requested setting (?P<name>\w+), but settings are not configured|Apps aren't loaded yet"
)
_ENV_VAR = re.compile(r"Set the (?P<name>\w+) environment variable")
_BAD_HOST = re.compile(r"Invalid HTTP_HOST header: '(?P<host>[^']+)'")
_REDIS = re.compile(
    r"Error \d+ connecting to (?P<host>[\w.\-]+):(?P<port>\d+)\. (?P<reason>[^\n.]+)"
    r"|Cannot connect to redis://(?P<url>\S+)"
)


def _settings(text: Text, ctx: _Context) -> list[Finding]:
    findings: list[Finding] = []
    if text.search(_NOT_CONFIGURED):
        findings.append(
            _finding(
                text,
                "settings-not-configured",
                "Django code ran before the settings were loaded",
                "Something imported models or read settings outside a Django process: a plain "
                "`python` script, an import at module level of a non-Django tool, or pytest "
                "without DJANGO_SETTINGS_MODULE.",
                "Run it through the project: `karni shell` or `python manage.py <command>` (a "
                "management command for scripts). In a standalone script set "
                "DJANGO_SETTINGS_MODULE=config.settings and call django.setup() before importing "
                "models. For pytest, keep DJANGO_SETTINGS_MODULE in [tool.pytest.ini_options].",
            )
        )
    env = text.search(_ENV_VAR)
    if env:
        findings.append(
            _finding(
                text,
                "env-missing",
                f"The {env['name']} environment variable is not set",
                f"Settings read {env['name']} from the environment (django-environ) and it is "
                "neither in the environment nor in .env.",
                f"cp .env.example .env (the scaffold's file lists every variable), then set "
                f"{env['name']} there, or export it in the shell or the service definition.",
            )
        )
    host = text.search(_BAD_HOST)
    if host:
        findings.append(
            _finding(
                text,
                "disallowed-host",
                "The request's host is not in ALLOWED_HOSTS",
                f"Django refused the Host header '{host['host']}' (400): ALLOWED_HOSTS does not "
                "list it.",
                f"Add it to ALLOWED_HOSTS in .env (comma-separated, e.g. "
                f"ALLOWED_HOSTS={host['host']},localhost). `*` is accepted in dev only.",
            )
        )
    redis = text.search(_REDIS)
    if redis:
        where = f"{redis['host']}:{redis['port']}" if redis["host"] else redis["url"]
        reason = (redis["reason"] or "connection refused").strip()
        findings.append(
            _finding(
                text,
                "redis-unreachable",
                "Redis is not reachable (cache, throttles, Celery broker)",
                f"Nothing answered at {where} ({reason}). "
                "Karni's default cache (throttle counters, response cache) and the Celery broker "
                "are Redis at REDIS_URL.",
                "Start Redis (`karni serve -d` runs the compose stack with it) or fix REDIS_URL in "
                ".env. For a host run without Redis set KARNI_CACHE=locmem (development only), and "
                "run Celery tasks eagerly (CELERY_TASK_ALWAYS_EAGER = True) or start one.",
            )
        )
    return findings


_SPECTACULAR = re.compile(
    r"(?:(?P<path>[^\s:]+\.py):(?P<line>\d+): )?(?P<level>Warning|Error) \[(?P<view>\w+)"
    r"(?: > (?P<serializer>\w+))?\]: (?P<message>[^\n]+)"
)
_TYPE_HINT = re.compile(r'unable to resolve type hint for function "(?P<func>\w+)"')


def _schema(text: Text, ctx: _Context) -> list[Finding]:
    findings: list[Finding] = []
    for line in text.plain.splitlines():
        match = _SPECTACULAR.search(line)
        if match is None:
            continue
        frame = Frame(match["path"], int(match["line"])) if match["path"] else None
        hint = _TYPE_HINT.search(match["message"])
        owner = match["serializer"] or match["view"]
        if hint:
            findings.append(
                _finding(
                    text,
                    "schema-method-type",
                    "OpenAPI schema: a SerializerMethodField has no return type",
                    f"{owner}.{hint['func']} has no return annotation, so drf-spectacular "
                    "documents the field as a string, and `karni types` then generates the wrong "
                    "TypeScript type for it.",
                    f"Annotate the return type of {hint['func']} (def {hint['func']}(self, obj) "
                    "-> str: …, with the type it really returns), or decorate it with "
                    "@extend_schema_field(OpenApiTypes.<TYPE>) from drf_spectacular.",
                    frame=frame,
                )
            )
        else:
            findings.append(
                _finding(
                    text,
                    "schema-warning",
                    f"OpenAPI schema {match['level'].lower()} on {match['view']}",
                    f"drf-spectacular: {match['message'].strip()}",
                    "Fix what the message names on that viewset or serializer: a type hint or "
                    "@extend_schema_field for a computed field, @extend_schema(responses=...) for "
                    "a custom action that returns something other than the viewset's serializer. "
                    "`karni types` reads this schema.",
                    frame=frame,
                )
            )
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


#: The catalogue, most specific first. Each pattern returns its findings for the text.
PATTERNS: Final[tuple[Pattern, ...]] = (
    _codes,
    _rules,
    _classes,
    _query_counts,
    _csrf,
    _cors,
    _access,
    _database,
    _settings,
    _schema,
)


#: Every failure class a pattern names by key (registered codes are ``code-<code>``,
#: agent rules ``rule-<code>``): key → what it is. Each key is an anchor on
#: :data:`DOCS_PAGE` (``tests/debugging`` checks the page).
CLASSES: Final[Mapping[str, str]] = {
    "query-count": "a query-count assertion failed (assertNumQueries, django_assert_num_queries)",
    "query-budget-warning": "the dev server's query-budget warning (E117 in warn mode)",
    "query-log-duplicates": "repeated statements in the dev query log",
    "csrf": "a session-mode CSRF refusal (token missing, untrusted origin)",
    "cors": "the browser blocked a cross-origin call",
    "access-404": "404 from a Karni viewset: a row outside the read scope",
    "access-403": "403 from a Karni viewset: a readable row, a refused action",
    "access-401": "401 logged by the dev server",
    "access-unauthenticated": "a request without credentials",
    "access-denied": "403 from a viewset's access rule",
    "db-driver": "the database driver is not installed (C012)",
    "db-unreachable": "the database cannot be reached (C013)",
    "migrations-not-applied": "a table is missing, or migrations are not applied",
    "migration-missing": "a model change has no migration",
    "settings-not-configured": "Django code ran before the settings were loaded",
    "env-missing": "an environment variable the settings read is not set",
    "disallowed-host": "the request's host is not in ALLOWED_HOSTS",
    "redis-unreachable": "Redis is not reachable",
    "schema-method-type": "a SerializerMethodField has no return type (OpenAPI)",
    "schema-warning": "another OpenAPI schema warning on a viewset",
}


def _core_lookup(code: str) -> Mapping[str, str] | None:
    entry = _core_get(code)
    return entry.as_dict() if entry is not None else None


def diagnose(
    text: str,
    *,
    root: Path | str | None = None,
    lookup: Lookup | None = None,
    rules: Iterable[Mapping[str, Any]] = (),
    patterns: Sequence[Pattern] = PATTERNS,
) -> Diagnosis:
    """Recognise the Karni failure(s) in ``text``; an empty result means "not recognised".

    :param root: the project root (frames under it are project frames, shown relative).
    :param lookup: ``code -> entry dict`` (title, why, fix, url); default: Karni's
        registry and installed modules. karni-cli passes its own (adds ``C`` codes).
    :param rules: agent rules as dicts (``code``, ``summary``, ``rule``, ``fix``,
        ``rationale``, ``enforced_by``) for K codes, architecture and ESLint ids.
    :param patterns: the catalogue; extend :data:`PATTERNS` to add a class.
    """
    parsed = Text(text, Path(root) if root is not None else None)
    ctx = _Context(lookup or _core_lookup, tuple(rules))
    findings: list[Finding] = []
    seen: set[str] = set()
    for pattern in patterns:
        for finding in pattern(parsed, ctx):
            identity = finding.code or finding.key
            if identity not in seen:
                seen.add(identity)
                findings.append(finding)
    findings.sort(key=lambda finding: finding.code in _SUMMARY_CODES)
    also: list[Finding] = []
    if parsed.exception:  # a traceback: a dev log line beside it is not its explanation
        also = [finding for finding in findings if finding.key in _WEAK]
        findings = [finding for finding in findings if finding.key not in _WEAK]
    return Diagnosis(
        findings=tuple(findings[:MAX_FINDINGS]),
        exception=parsed.exception,
        where=parsed.location(parsed.where()),
        raised=parsed.location(parsed.raised()),
        also=tuple(also[:MAX_FINDINGS]),
    )


#: Findings read from log lines, which explain a traceback printed beside them only by chance.
_WEAK: Final = frozenset({"query-log-duplicates", "query-budget-warning"})
