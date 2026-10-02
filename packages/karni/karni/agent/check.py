"""Single-file static checks behind ``karni rules --check <file>``.

A fast pre-commit view of the enforced rules for ONE file, with no Django and
no project import: AST for Python, a comment-aware scan for TS/JS. It is a
subset of the real enforcement — ``karni check`` (architecture tests) and the
``@karni/ui`` ESLint preset stay authoritative; cross-file rules (duplicates,
registry-based admin checks) are not attempted here. Path allowances use the
documented defaults of ``KARNI_ARCHITECTURE`` / the ESLint preset, because
project settings are not readable without Django.

Opt-outs are honoured exactly as the real rules spell them:
``# karni: allow(<rule-id>): <reason>`` (same line, the line above, or the
line above a class / its first decorator) and
``// eslint-disable-next-line karni/<rule> -- <reason>``. A marker without a
reason is itself a finding (K005).
"""

from __future__ import annotations

import ast
import fnmatch
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .rules import ENFORCEMENT_CODES, rules_by_code

#: Defaults mirrored from karni.testing._source.DEFAULTS (KARNI_ARCHITECTURE).
SQL_ALLOWED: tuple[str, ...] = ("*/sql/*", "*/migrations/*")
HTTP_ALLOWED: tuple[str, ...] = ("*/services/*", "*/providers/*", "*/tests/*", "conftest.py")
HTTP_BANNED: frozenset[str] = frozenset({"requests", "httpx", "urllib.request"})
#: Any of these as a base satisfies model-base (BaseModel or its mixins).
KARNI_MODEL_BASES: frozenset[str] = frozenset(
    {"BaseModel", "UUIDModel", "TimestampedModel", "SoftDeleteModel", "AuditedModel"}
)
_DRF_VIEWSETS = frozenset({"GenericViewSet", "ModelViewSet", "ReadOnlyModelViewSet"})

PY_SUFFIXES = frozenset({".py"})
TS_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs"})
JSX_SUFFIXES = frozenset({".tsx", ".jsx"})
PAGE_MAX_LINES = 50

_PY_ALLOW = re.compile(r"#\s*karni:\s*allow\(([^)]*)\)\s*(?::\s*(.*))?$")
_ESLINT_DIRECTIVE = re.compile(
    r"eslint-disable(?P<kind>-next-line|-line)?\s+(?P<rules>[^*\n]*?)\s*(?:--\s*(?P<reason>.*?))?\s*(?:\*/)?\s*$"
)


@dataclass(frozen=True)
class Finding:
    code: str
    rule_id: str
    line: int
    message: str
    fix: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finding(rule_id: str, line: int, message: str) -> Finding:
    code = ENFORCEMENT_CODES[rule_id]
    return Finding(code, rule_id, line, message, rules_by_code()[code].fix)


def _matches(path: str, globs: Iterable[str]) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(name, g) for g in globs)


# --- Python -------------------------------------------------------------------


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


class SqlVisitor(ast.NodeVisitor):
    """``.raw()`` / ``.execute()`` / ``.executemany()`` / ``RawSQL(...)`` calls."""

    def __init__(self) -> None:
        self.hits: list[tuple[int, str]] = []
        self._rawsql_names = {"RawSQL"}

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "RawSQL":
                self._rawsql_names.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {"raw", "execute", "executemany"}:
            self.hits.append((node.lineno, f".{func.attr}(...)"))
        elif isinstance(func, ast.Name | ast.Attribute) and (
            _dotted(func).rsplit(".", 1)[-1] in self._rawsql_names
        ):
            self.hits.append((node.lineno, "RawSQL(...)"))
        self.generic_visit(node)


def _is_abstract(cls: ast.ClassDef) -> bool:
    for stmt in cls.body:
        if isinstance(stmt, ast.ClassDef) and stmt.name == "Meta":
            for item in stmt.body:
                if (
                    isinstance(item, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "abstract" for t in item.targets)
                    and isinstance(item.value, ast.Constant)
                    and item.value.value is True
                ):
                    return True
    return False


def _class_lines(cls: ast.ClassDef) -> list[int]:
    first = min([cls.lineno, *(d.lineno for d in cls.decorator_list)])
    return sorted({cls.lineno, cls.lineno - 1, first, first - 1})


def _is_meta_only(cls: ast.ClassDef) -> bool:
    body = [
        s
        for s in cls.body
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
        and not isinstance(s, ast.Pass)
    ]
    return bool(body) and all(isinstance(s, ast.ClassDef) and s.name == "Meta" for s in body)


def _assigned_names(cls: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            names |= {t.id for t in stmt.targets if isinstance(t, ast.Name)}
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
        elif isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(stmt.name)
    return names


def _lacks_access(cls: ast.ClassDef) -> bool:
    """A routable direct ``BaseViewSet`` subclass (``model``/``queryset``) without ``access``.

    Subclasses of other viewsets inherit their parent's declaration, which a
    single-file scan cannot see; ``karni check`` judges those.
    """
    names = _assigned_names(cls)
    routable = bool(names & {"model", "queryset"})
    return routable and not names & {"access", "get_access"}


def access_override_defs(tree: ast.AST) -> list[tuple[int, list[int]]]:
    """``(def line, opt-out marker lines)`` for each ``filter_queryset_for_user`` in a class.

    Shared by the ``access-override`` architecture rule and ``karni rules
    --check``. Markers count on the ``def`` line, the line above it, or the
    line above its first decorator.
    """
    hits: list[tuple[int, list[int]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if (
                isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef)
                and stmt.name == "filter_queryset_for_user"
            ):
                first = min([stmt.lineno, *(d.lineno for d in stmt.decorator_list)])
                hits.append((stmt.lineno, sorted({stmt.lineno, stmt.lineno - 1, first - 1})))
    return sorted(hits)


def _python(path: str, text: str) -> list[tuple[Finding, list[int]]]:
    tree = ast.parse(text, filename=path)
    model_names = {"models.Model", "django.db.models.Model"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "django.db.models":
            model_names |= {a.asname or a.name for a in node.names if a.name == "Model"}
    found: list[tuple[Finding, list[int]]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = {_dotted(b) for b in node.bases}
            short = {b.rsplit(".", 1)[-1] for b in bases}
            if bases & model_names and not short & KARNI_MODEL_BASES and not _is_abstract(node):
                found.append(
                    (
                        _finding(
                            "model-base",
                            node.lineno,
                            f"{node.name} inherits django.db.models.Model directly",
                        ),
                        _class_lines(node),
                    )
                )
            if short & _DRF_VIEWSETS and "BaseViewSet" not in short:
                found.append(
                    (
                        _finding("viewset-base", node.lineno, f"{node.name} bypasses BaseViewSet"),
                        _class_lines(node),
                    )
                )
            if "ModelAdmin" in short and "KarniModelAdmin" not in short:
                found.append(
                    (
                        _finding(
                            "admin-convention",
                            node.lineno,
                            f"{node.name} is a plain ModelAdmin, not derived from AdminMeta",
                        ),
                        _class_lines(node),
                    )
                )
            if "BaseViewSet" in short and _lacks_access(node):
                found.append(
                    (
                        _finding(
                            "viewset-access",
                            node.lineno,
                            f"{node.name} declares no `access` — every request is denied",
                        ),
                        _class_lines(node),
                    )
                )
            if "ModelSerializer" in short and _is_meta_only(node):
                found.append(
                    (
                        _finding(
                            "redundant-serializer",
                            node.lineno,
                            f"{node.name} is a Meta-only ModelSerializer — "
                            "BaseViewSet(model=X) already generates it",
                        ),
                        _class_lines(node),
                    )
                )
        elif (
            isinstance(node, ast.Call)
            and _dotted(node.func) == "admin.site.register"
            and len(node.args) == 1
        ):
            found.append(
                (
                    _finding(
                        "admin-convention",
                        node.lineno,
                        "admin.site.register() with the default ModelAdmin",
                    ),
                    [node.lineno, node.lineno - 1],
                )
            )

    for lineno, candidates in access_override_defs(tree):
        found.append(
            (
                _finding(
                    "access-override",
                    lineno,
                    "filter_queryset_for_user overridden — express row rules in `access`",
                ),
                candidates,
            )
        )

    if not _matches(path, SQL_ALLOWED):
        visitor = SqlVisitor()
        visitor.visit(tree)
        for lineno, what in visitor.hits:
            found.append(
                (
                    _finding("raw-sql", lineno, f"raw SQL via {what} outside a sql/ directory"),
                    [lineno, lineno - 1],
                )
            )

    if not _matches(path, HTTP_ALLOWED):
        for lineno, name in http_client_imports(tree):
            found.append(
                (
                    _finding("http-client", lineno, f"direct HTTP client import: {name}"),
                    [lineno, lineno - 1],
                )
            )
    return found


def http_client_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """``(lineno, name)`` for each import of a banned HTTP client (one per statement)."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        else:
            continue
        for name in names:
            if name in HTTP_BANNED or any(name.startswith(f"{b}.") for b in HTTP_BANNED):
                hits.append((node.lineno, name))
                break
    return sorted(hits)


def _python_optouts(lines: list[str], found: list[tuple[Finding, list[int]]]) -> list[Finding]:
    markers: dict[int, tuple[set[str], str]] = {}
    for i, text in enumerate(lines, start=1):
        m = _PY_ALLOW.search(text)
        if m:
            rules = {r.strip() for r in m.group(1).split(",") if r.strip()}
            markers[i] = (rules, (m.group(2) or "").strip())
    result: list[Finding] = []
    for i, (rules, reason) in sorted(markers.items()):
        if not reason:
            result.append(
                _finding(
                    "opt-out-reason",
                    i,
                    f"karni: allow({', '.join(sorted(rules))}) requires a non-empty reason",
                )
            )
    for finding, candidates in found:
        allowed = any(
            finding.rule_id in markers.get(line, (set(), ""))[0] and markers[line][1]
            for line in candidates
        )
        if not allowed:
            result.append(finding)
    return result


# --- TypeScript / JavaScript --------------------------------------------------

_RAW_ELEMENT = re.compile(r"<(table|form|input|select|textarea)(?=[\s/>])")
_DEEP_IMPORT = re.compile(
    r"""(?:from\s+|import\s*\(\s*|require\s*\(\s*|import\s+)["']@karni/ui/(?:dist|src)(?:/[^"']*)?["']"""
)
_FETCH = re.compile(r"(?<![\w$.])(?:(?:window|globalThis|self)\.)?fetch\s*\(")
_IMPORT_SOURCE = r"""(?:from\s+|import\s*\(\s*|require\s*\(\s*|import\s+)["']"""
_AXIOS = re.compile(_IMPORT_SOURCE + r"""axios(?:/[^"']*)?["']""")
_NEW_TRANSPORT = re.compile(
    r"(?<![\w$.])new\s+(?:(?:window|globalThis|self)\.)?(XMLHttpRequest|WebSocket)\b"
)
_REPLACEMENTS = {
    "table": "ResourceTable",
    "form": "ResourceForm",
    "input": "Input (or ResourceForm)",
    "select": "Select / ResourceSelect",
    "textarea": "Textarea (or ResourceForm)",
}


def _split_comments(text: str) -> tuple[list[str], list[tuple[int, str]]]:
    """Code lines with comments blanked (line numbers kept) + (line, comment) pairs.

    String literals are skipped so ``"//"`` inside a string is not a comment;
    template literals are treated like strings (no nested ``${}`` parsing).
    """
    out: list[str] = []
    comments: list[tuple[int, str]] = []
    i, n, line = 0, len(text), 1
    buf: list[str] = []
    block: list[str] | None = None
    block_line = 0
    quote = ""
    while i < n:
        ch = text[i]
        if block is not None:
            if text.startswith("*/", i):
                block.append("*/")
                comments.append((block_line, "".join(block)))
                block = None
                i += 2
                continue
            if ch == "\n":
                out.append("".join(buf))
                buf = []
                line += 1
            block.append(ch)
            i += 1
            continue
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            elif ch == "\n":
                out.append("".join(buf))
                buf = []
                line += 1
                if quote != "`":
                    quote = ""
            i += 1
            continue
        if text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end == -1 else end
            comments.append((line, text[i:end]))
            i = end
            continue
        if text.startswith("/*", i):
            block = ["/*"]
            block_line = line
            i += 2
            continue
        if ch in "\"'`":
            quote = ch
        if ch == "\n":
            out.append("".join(buf))
            buf = []
            line += 1
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out, comments


_STRING = re.compile(r""""(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`""")


def _blank_strings(lines: list[str]) -> list[str]:
    """String literal contents replaced by spaces (quotes and line count kept)."""

    def blank(match: re.Match[str]) -> str:
        body = match.group(0)
        inner = "".join("\n" if ch == "\n" else " " for ch in body[1:-1])
        return body[0] + inner + body[-1]

    return _STRING.sub(blank, "\n".join(lines)).split("\n")


def _ts(path: str, text: str) -> list[Finding]:
    code_lines, comments = _split_comments(text)
    bare_lines = _blank_strings(code_lines)
    suffix = Path(path).suffix
    findings: list[Finding] = []
    # eslint directives: line -> set of suppressed rule names ("*" = all)
    suppressed: dict[int, set[str]] = {}
    file_wide: set[str] = set()
    for line, comment in comments:
        m = _ESLINT_DIRECTIVE.search(comment)
        if not m:
            continue
        rules = {r.strip() for r in m.group("rules").split(",") if r.strip()} or {"*"}
        if not (m.group("reason") or "").strip():
            findings.append(
                _finding(
                    "eslint-comments/require-description",
                    line,
                    "eslint-disable comment without a `-- <reason>`",
                )
            )
            continue
        kind = m.group("kind")
        if kind == "-next-line":
            suppressed.setdefault(line + 1, set()).update(rules)
        elif kind == "-line":
            suppressed.setdefault(line, set()).update(rules)
        else:
            file_wide |= rules

    def report(rule_id: str, line: int, message: str) -> None:
        active = suppressed.get(line, set()) | file_wide
        if rule_id in active or "*" in active:
            return
        findings.append(_finding(rule_id, line, message))

    posix = Path(path).as_posix()
    parts = posix.split("/")
    if suffix in JSX_SUFFIXES:
        for number, code in enumerate(bare_lines, start=1):
            for m in _RAW_ELEMENT.finditer(code):
                element = m.group(1)
                report(
                    "karni/no-raw-elements",
                    number,
                    f"raw <{element}> — compose {_REPLACEMENTS[element]} from @karni/ui",
                )
    if "pages" in parts[:-1]:
        physical = text.split("\n")
        count = len(physical) - 1 if physical[-1] == "" else len(physical)
        if count > PAGE_MAX_LINES:
            report(
                "karni/max-page-lines",
                1,
                f"page file is {count} physical lines (max {PAGE_MAX_LINES})",
            )
    for number, code in enumerate(code_lines, start=1):
        if _DEEP_IMPORT.search(code):
            report("karni/no-deep-imports", number, "deep import from @karni/ui internals")
    http_exempt = (
        "api" in parts[:-1]
        or "mocks" in parts[:-1]
        or fnmatch.fnmatch(parts[-1], "*.test.*")
        or fnmatch.fnmatch(parts[-1], "vitest.setup.*")
    )
    if not http_exempt:
        for number, (code, bare) in enumerate(zip(code_lines, bare_lines, strict=True), 1):
            if _FETCH.search(bare):
                report("karni/no-direct-http", number, "direct fetch() outside src/api/")
            if _AXIOS.search(code):
                report("karni/no-direct-http", number, "axios import — Karni ships the HTTP layer")
            for m in _NEW_TRANSPORT.finditer(bare):
                report("karni/no-direct-http", number, f"new {m.group(1)}() outside src/api/")
    return findings


# --- entry points ---------------------------------------------------------------


def supported(path: str | Path) -> bool:
    suffix = Path(path).suffix
    return suffix in PY_SUFFIXES or suffix in TS_SUFFIXES


def check_source(path: str | Path, text: str) -> list[Finding]:
    """Findings for ``text`` as if it lived at ``path`` (the path drives allowances)."""
    posix = Path(path).as_posix()
    suffix = Path(path).suffix
    if suffix in PY_SUFFIXES:
        try:
            found = _python(posix, text)
        except SyntaxError as exc:
            raise ValueError(f"{path}:{exc.lineno}: cannot parse: {exc.msg}") from None
        findings = _python_optouts(text.splitlines(), found)
    elif suffix in TS_SUFFIXES:
        findings = _ts(posix, text)
    else:
        return []
    return sorted(findings, key=lambda f: (f.line, f.code, f.message))


def scoped_path(path: Path, root: Path | None = None) -> str:
    """The path the allowances match against: relative to ``root`` (else the cwd) when
    inside it, as ``./<rel>`` — so a ``tests/`` or ``api/`` directory ABOVE the project
    never changes the verdict — otherwise the absolute path."""
    absolute = path.resolve()
    for base in (root, Path.cwd()):
        if base is None:
            continue
        try:
            return "./" + absolute.relative_to(Path(base).resolve()).as_posix()
        except ValueError:
            continue
    return absolute.as_posix()


def check_file(
    path: str | Path, enabled: Iterable[str] | None = None, root: str | Path | None = None
) -> list[Finding]:
    """Read and check one file; ``enabled`` (codes) filters out disabled rules."""
    path = Path(path)
    scope = scoped_path(path, Path(root) if root is not None else None)
    findings = check_source(scope, path.read_text(encoding="utf-8"))
    if enabled is not None:
        allowed = set(enabled)
        findings = [f for f in findings if f.code in allowed]
    return findings
