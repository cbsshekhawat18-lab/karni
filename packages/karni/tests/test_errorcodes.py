"""The error code registry, the exception hierarchy and the code hygiene of the source.

Errors are API for AI agents: every Karni error carries a registered code, a
message that names the fix, and a docs link built from the code. These tests
keep it that way as the code base grows.
"""

from __future__ import annotations

import ast
import pickle
import re
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import ValidationError

from karni import errorcodes
from karni.changelog import DOCS_BASE_URL as CHANGELOG_DOCS_BASE_URL
from karni.exceptions import (
    KarniAssertionError,
    KarniImproperlyConfigured,
    KarniValueError,
    api_error,
    check_error,
)

PACKAGE = Path(errorcodes.__file__).resolve().parents[1]
REPO = PACKAGE.parents[2]
PAYMENTS = REPO / "modules" / "karni-payments" / "karni_payments"
SOURCES = [PACKAGE, PAYMENTS]

#: Constructing these directly would let an uncoded error escape Karni code.
BARE = {
    "Exception",
    "ValueError",
    "TypeError",
    "AssertionError",
    "RuntimeError",
    "KeyError",
    "LookupError",
    "IndexError",
    "ImportError",
    "ImproperlyConfigured",
    "CommandError",
}
#: Python protocols and stdlib-only modules (loaded by path in karni-cli).
ALLOWED_FILES = {"errorcodes/__init__.py"}
MARKER = "karni: bare-raise-ok"


def _python_files() -> list[Path]:
    return [
        path
        for root in SOURCES
        for path in sorted(root.rglob("*.py"))
        if "migrations" not in path.parts and "__pycache__" not in path.parts
    ]


def _rel(path: Path) -> str:
    for root in SOURCES:
        if path.is_relative_to(root):
            return path.relative_to(root).as_posix()
    return path.as_posix()


# the registry


def test_registry_entries_are_complete_and_well_formed() -> None:
    entries = errorcodes.registry()
    assert errorcodes.problems(entries.values()) == []
    assert len(entries) == len(errorcodes.CODES) + sum(
        1 for code in entries if not re.match(r"^[EW]\d{3}$", code)
    )


def test_module_codes_use_their_own_prefix() -> None:
    payments = [code for code in errorcodes.registry() if code.startswith("PAY")]
    assert payments, "karni-payments' codes are not registered (karni.errorcodes entry point)"
    core = {entry.code for entry in errorcodes.CODES}
    assert all(re.match(r"^[EW]\d{3}$", code) for code in core)


def test_a_code_registered_twice_is_refused() -> None:
    twin = errorcodes.CODES[0]
    with pytest.raises(errorcodes.KarniError, match="registered twice"):
        errorcodes.registry([twin])


def test_docs_links_share_the_changelog_base_url() -> None:
    assert errorcodes.DOCS_BASE_URL == CHANGELOG_DOCS_BASE_URL
    assert errorcodes.docs_url("E104") == f"{CHANGELOG_DOCS_BASE_URL}errors/#e104"


def test_lookup_is_case_insensitive() -> None:
    entry = errorcodes.get(" e104 ")
    assert entry is not None and entry.code == "E104"
    assert errorcodes.get("E999") is None


# the exception hierarchy


def test_an_error_reads_code_message_link() -> None:
    error = KarniImproperlyConfigured("Owned() needs a field.", code="E104")
    assert str(error) == f"E104: Owned() needs a field. See {errorcodes.docs_url('E104')}"
    assert error.message == "Owned() needs a field."
    assert isinstance(error, ImproperlyConfigured)


def test_a_multi_line_report_keeps_the_link_on_its_own_line() -> None:
    error = KarniAssertionError("2 problems:\n  - one\n  - two", code="E602")
    assert str(error).endswith(f"\n  - two\nSee {errorcodes.docs_url('E602')}")
    assert isinstance(error, AssertionError)


def test_errors_survive_pickling_with_their_code() -> None:
    error = KarniValueError("bad value", code="E203")
    copy = pickle.loads(pickle.dumps(error))
    assert type(copy) is KarniValueError
    assert (copy.code, copy.message, str(copy)) == (error.code, error.message, str(error))


def test_api_error_carries_the_code_in_error_detail() -> None:
    error = api_error("E126", "Unknown expand key 'venu'.", field="expand")
    assert isinstance(error, ValidationError)
    (detail,) = error.detail["expand"]
    assert detail.code == "E126"
    assert str(detail).startswith("E126: Unknown expand key 'venu'. See ")


def test_check_messages_use_the_code_as_their_id() -> None:
    message = check_error("E101", "X declares no access.", hint="Declare one.")
    assert message.id == "karni.E101"
    assert message.hint == f"Declare one. See {errorcodes.docs_url('E101')}"


# the source


def _codes_in_source() -> dict[str, list[str]]:
    """Every code literal the source passes as ``code=``, a class ``code``, or a helper arg."""
    used: dict[str, list[str]] = {}
    helpers = {"api_error", "check_error", "check_warning", "docs_url", "_fix"}
    for path in _python_files():
        if _rel(path) in ALLOWED_FILES or path.name == "errorcodes.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            found: str | None = None
            if isinstance(node, ast.keyword) and node.arg == "code":
                found = _literal(node.value)
            elif isinstance(node, ast.Call) and node.args:
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if name in helpers:
                    found = _literal(node.args[0])
            elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "code" for t in node.targets
            ):
                found = _literal(node.value)
            if found and re.match(r"^(?:[EW]\d{3}|PAY\d{3})$", found):
                used.setdefault(found, []).append(f"{_rel(path)}:{node.lineno}")  # type: ignore[attr-defined]
    return used


def _literal(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def test_every_code_the_source_uses_is_registered() -> None:
    registered = set(errorcodes.registry())
    unknown = {code: where for code, where in _codes_in_source().items() if code not in registered}
    assert not unknown, f"register these codes in karni/errorcodes (or the module's): {unknown}"


def test_every_registered_code_is_used_somewhere() -> None:
    text = "\n".join(
        path.read_text()
        for path in _python_files()
        if _rel(path) not in ALLOWED_FILES and path.name != "errorcodes.py"
    )
    unused = [code for code in errorcodes.registry() if f'"{code}"' not in text]
    assert not unused, f"registered but never raised or checked (retire or use them): {unused}"


def test_no_bare_builtin_exception_or_assert_escapes_karni_code() -> None:
    offenders: list[str] = []
    for path in _python_files():
        rel = _rel(path)
        if rel in ALLOWED_FILES:
            continue
        lines = path.read_text().splitlines()
        tree = ast.parse("\n".join(lines))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                offenders.append(f"{rel}:{node.lineno}: assert (stripped under -O; raise instead)")
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                continue
            func = node.exc.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name not in BARE or MARKER in lines[node.lineno - 1]:
                continue
            offenders.append(f"{rel}:{node.lineno}: raise {name}(...)")
    offenders += _getattr_violations()
    assert not offenders, (
        "Raise a coded karni.exceptions class (KarniImproperlyConfigured, KarniValueError, ...) "
        "with code=..., registered in karni/errorcodes:\n  " + "\n  ".join(offenders)
    )


def _getattr_violations() -> list[str]:
    """AttributeError is allowed only as the module ``__getattr__`` protocol."""
    found = []
    for path in _python_files():
        tree = ast.parse(path.read_text())
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Raise)
                    and isinstance(node.exc, ast.Call)
                    and getattr(node.exc.func, "id", "") == "AttributeError"
                    and function.name != "__getattr__"
                ):
                    found.append(f"{_rel(path)}:{node.lineno}: AttributeError outside __getattr__")
    return found
