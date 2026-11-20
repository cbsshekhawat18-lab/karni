"""Fixtures of the notifications suite: message kinds over a folder of templates, roles, users."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.mail import register_kind, unregister_kind
from tests.people.conftest import make_user

ROLES = {
    "admin": {"system": True, "grants": {"*": "all"}},
    # Edits the emails, nothing else.
    "writer": {"grants": {"notify.emailtemplate:*": "all"}},
    "customer": {"grants": {}},
}

#: The kinds this suite declares: a receipt on both channels, a note for the inbox only, a
#: newsletter (marketing) and a code nobody may switch off.
KINDS = ("club.receipt", "club.note", "club.news", "club.code")
#: The receipt's merge fields.
RECEIPT_FIELDS = {"order.number": "The order's number", "order.total": "Its total", "link": "Page"}


@pytest.fixture(autouse=True)
def club(tmp_path: Path) -> Iterator[Path]:
    """The club's templates and kinds, the suite's URLconf and roles."""
    folder = tmp_path / "club" / "email"
    folder.mkdir(parents=True)
    for stem, subject, body in (
        ("receipt", "Receipt {{ order.number }}", "Paid {{ order.total }}. {{ link }}"),
        ("note", "A note from {{ who }}", "{{ text }}"),
        ("news", "Club news", "News for you. Leave: {{ unsubscribe_url }}"),
        ("code", "Your code", "{{ code }}"),
    ):
        (folder / f"{stem}_subject.txt").write_text(subject)
        (folder / f"{stem}_body.txt").write_text(body)
    templates = [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [str(tmp_path)],
            "APP_DIRS": True,
        }
    ]
    register_kind(
        "club.receipt",
        title="Receipt",
        template="club/email/receipt",
        audience="the member",
        fields=RECEIPT_FIELDS,
        channels=("email", "inbox"),
    )
    register_kind(
        "club.note",
        title="Note",
        template="club/email/note",
        fields={"who": "Who wrote", "text": "The note"},
        channels=("inbox",),
    )
    register_kind(
        "club.news",
        title="Club news",
        template="club/email/news",
        transactional=False,
        channels=("email", "inbox"),
    )
    register_kind(
        "club.code",
        title="Code",
        template="club/email/code",
        fields={"code": "The code"},
        switchable=False,
        channels=("email", "inbox"),
    )
    with override_settings(
        TEMPLATES=templates,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        KARNI_FRONTEND_URL="https://club.example.com",
        KARNI_ROLES=ROLES,
        ROOT_URLCONF="tests.notify.urls",
        KARNI_API_ROUTER="tests.notify.urls.get_router",
    ):
        sync_roles()
        yield tmp_path
    for name in KINDS:
        unregister_kind(name)


def person(email: str, *roles: str) -> Any:
    found = make_user(email)
    for role in roles:
        assign_role(found, role)
    return found


def as_user(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def ana() -> Any:
    return person("ana@example.com", "customer")


@pytest.fixture
def ben() -> Any:
    return person("ben@example.com", "customer")


@pytest.fixture
def writer() -> Any:
    return person("writer@example.com", "writer")
