"""Email plumbing for :mod:`karni.accounts`.

Every message the accounts app sends (verification, password reset, email
change) goes through exactly one seam: :func:`get_email_backend` resolves the
``KARNI_ACCOUNTS_EMAIL_BACKEND`` setting to an :class:`AccountsEmailBackend`
and nothing in Karni sends account mail any other way.

Override / escape hatches, from lightest to heaviest:

* **Templates** — :class:`DjangoEmailBackend` renders ordinary Django
  templates under ``karni_accounts/email/``; put same-named templates in one
  of your project's template ``DIRS`` (which Django searches before app
  directories) to replace subject or body without touching Python.
* **Links** — override ``KARNI_FRONTEND_URL`` or any entry in the
  ``KARNI_ACCOUNTS_LINKS`` dict of format strings to change where the emailed
  links point.
* **Backend** — set ``KARNI_ACCOUNTS_EMAIL_BACKEND`` to a dotted path of your
  own :class:`AccountsEmailBackend` subclass (queue it through Celery, call an
  ESP API, ...). :class:`InMemoryEmailBackend` is the test double.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

from karni.exceptions import KarniImproperlyConfigured
from karni.imports import import_setting

__all__ = [
    "DEFAULT_EMAIL_BACKEND",
    "DEFAULT_LINKS",
    "AccountsEmail",
    "AccountsEmailBackend",
    "DjangoEmailBackend",
    "InMemoryEmailBackend",
    "build_link",
    "get_email_backend",
]

DEFAULT_EMAIL_BACKEND = "karni.accounts.emails.DjangoEmailBackend"
"""Dotted path used when ``KARNI_ACCOUNTS_EMAIL_BACKEND`` is not set."""

DEFAULT_FRONTEND_URL = "http://localhost:5173"
"""Fallback frontend origin when ``KARNI_FRONTEND_URL`` is not set."""

DEFAULT_LINKS: dict[str, str] = {
    "verify_email": "{frontend}/auth/verify-email?token={token}",
    "reset_password": "{frontend}/auth/reset-password?token={token}",
    "change_email": "{frontend}/auth/confirm-email-change?token={token}",
}
"""Default link format strings, keyed by token purpose.

Override / escape hatch: define ``KARNI_ACCOUNTS_LINKS`` in settings; entries
you provide are merged over these defaults key by key, so overriding one link
does not require repeating the others. Each value is a :meth:`str.format`
template receiving ``frontend`` (``KARNI_FRONTEND_URL`` without its trailing
slash) and ``token`` (the URL-safe secret).
"""


@dataclass
class AccountsEmail:
    """One account email, independent of how it gets delivered.

    ``template`` names the message kind (``"verify_email"``,
    ``"reset_password"`` or ``"change_email"``) and doubles as the template
    stem for :class:`DjangoEmailBackend`. ``to`` is the recipient address and
    ``context`` the template context (services always include ``user``,
    ``token`` and ``link``).

    Override / escape hatch: custom backends receive this object untouched,
    so services can put extra keys into ``context`` and a project backend can
    read them.
    """

    template: str
    to: str
    context: dict[str, Any] = field(default_factory=dict)


class AccountsEmailBackend(ABC):
    """Delivery seam for every email the accounts app sends.

    Override / escape hatch: subclass, implement :meth:`send`, and point the
    ``KARNI_ACCOUNTS_EMAIL_BACKEND`` setting at your class's dotted path.
    Backends are instantiated per :func:`get_email_backend` call with no
    arguments, so keep configuration in settings.
    """

    @abstractmethod
    def send(self, email: AccountsEmail) -> None:
        """Deliver ``email``. Implementations may raise to abort the caller."""


class DjangoEmailBackend(AccountsEmailBackend):
    """Default backend: render Django templates, send through ``EMAIL_BACKEND``.

    For a message with template stem ``<name>`` it renders::

        karni_accounts/email/<name>_subject.txt   (required)
        karni_accounts/email/<name>_body.txt      (required)
        karni_accounts/email/<name>_body.html     (optional alternative)

    and sends an :class:`~django.core.mail.EmailMultiAlternatives` through
    whatever ``EMAIL_BACKEND`` the project configured (console in the dev
    profile). The rendered subject is collapsed to a single line as a
    header-injection guard, so subject templates may span lines freely.

    Override / escape hatch: shadow the templates from your project's
    template ``DIRS`` (Django's normal template-override mechanism — no
    Python needed), override :attr:`template_prefix` in a subclass to relocate
    them, or replace the backend entirely via ``KARNI_ACCOUNTS_EMAIL_BACKEND``.
    """

    template_prefix = "karni_accounts/email/"
    """Directory (inside template loaders) holding the message templates."""

    def send(self, email: AccountsEmail) -> None:
        """Render the three templates for ``email.template`` and send the mail."""
        stem = f"{self.template_prefix}{email.template}"
        raw_subject = render_to_string(f"{stem}_subject.txt", email.context)
        # Header-injection guard: a subject must be exactly one header line.
        subject = " ".join(raw_subject.split())
        body = render_to_string(f"{stem}_body.txt", email.context)
        message = EmailMultiAlternatives(subject=subject, body=body, to=[email.to])
        try:
            html = render_to_string(f"{stem}_body.html", email.context)
        except TemplateDoesNotExist:
            html = None
        if html is not None:
            message.attach_alternative(html, "text/html")
        message.send()


class InMemoryEmailBackend(AccountsEmailBackend):
    """Test double that records every email instead of delivering it.

    Activate with::

        override_settings(
            KARNI_ACCOUNTS_EMAIL_BACKEND="karni.accounts.emails.InMemoryEmailBackend"
        )

    then inspect :attr:`outbox` and call :meth:`clear` between tests. The
    outbox is class-level state shared by every instance, mirroring Django's
    ``locmem`` mail outbox.
    """

    outbox: ClassVar[list[AccountsEmail]] = []
    """Every :class:`AccountsEmail` sent since the last :meth:`clear`."""

    def send(self, email: AccountsEmail) -> None:
        """Append ``email`` to the class-level :attr:`outbox`."""
        type(self).outbox.append(email)

    @classmethod
    def clear(cls) -> None:
        """Empty the outbox (call between tests)."""
        cls.outbox.clear()


def get_email_backend() -> AccountsEmailBackend:
    """Instantiate the configured accounts email backend.

    Resolves the ``KARNI_ACCOUNTS_EMAIL_BACKEND`` setting (default
    :data:`DEFAULT_EMAIL_BACKEND`) with ``import_string`` and returns a fresh
    instance, so ``override_settings`` in tests takes effect immediately.
    Nothing in :mod:`karni.accounts` sends mail except through this function.

    Override / escape hatch: set ``KARNI_ACCOUNTS_EMAIL_BACKEND`` to the
    dotted path of any :class:`AccountsEmailBackend` subclass.
    """
    path: str = getattr(settings, "KARNI_ACCOUNTS_EMAIL_BACKEND", DEFAULT_EMAIL_BACKEND)
    backend_cls = import_setting("KARNI_ACCOUNTS_EMAIL_BACKEND", path, code="E201")
    backend = backend_cls()
    if not isinstance(backend, AccountsEmailBackend):
        raise KarniImproperlyConfigured(
            f"KARNI_ACCOUNTS_EMAIL_BACKEND ({path!r}) must name an AccountsEmailBackend subclass.",
            code="E201",
        )
    return backend


def build_link(purpose: str, token: str) -> str:
    """Build the frontend URL a recipient clicks to complete ``purpose``.

    Looks up the format string for ``purpose`` in ``KARNI_ACCOUNTS_LINKS``
    (merged over :data:`DEFAULT_LINKS`) and fills in ``frontend`` (the
    ``KARNI_FRONTEND_URL`` setting, trailing slash stripped) and ``token``.

    Override / escape hatch: change ``KARNI_FRONTEND_URL`` to move all links
    to another origin, or override individual ``KARNI_ACCOUNTS_LINKS`` entries
    to change a single route.

    :raises ImproperlyConfigured: when ``purpose`` has no configured link.
    """
    frontend: str = getattr(settings, "KARNI_FRONTEND_URL", DEFAULT_FRONTEND_URL)
    links: dict[str, str] = {
        **DEFAULT_LINKS,
        **getattr(settings, "KARNI_ACCOUNTS_LINKS", {}),
    }
    try:
        template = links[purpose]
    except KeyError as exc:
        raise KarniImproperlyConfigured(
            f"No KARNI_ACCOUNTS_LINKS entry for token purpose {purpose!r}. "
            f"Known purposes: {sorted(links)}.",
            code="E202",
        ) from exc
    return template.format(frontend=frontend.rstrip("/"), token=token)
