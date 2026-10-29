"""Experimental. A versioned terms (EULA) acceptance gate, in JWT and session mode.

``KARNI_TERMS = {"version": "2026-11", "url": "/terms/", "required": True}``
asks every signed-in user to accept version ``2026-11`` of the terms found at
``/terms/`` before they use the API:

1. ``GET <auth mount>/terms/`` answers ``{"version", "url", "required",
   "accepted", "accepted_at"}`` for the signed-in user (:func:`status`), and
   the ``me/`` payload (which ``login/`` returns as ``user``) carries
   ``terms`` (:func:`me_status`).
2. ``POST <auth mount>/terms/accept/ {"version", "client"?}`` records the
   acceptance in :class:`~karni.accounts.models.TermsAcceptance`
   (:func:`accept`), with the client's IP, its user agent and what the app
   sent about itself. Accepting the same version again changes nothing.
   Another version is refused with ``E246``.
3. :class:`TermsGateMiddleware` answers 403 ``E245`` to a signed-in user who
   has not accepted the current version, on every request whose path starts
   with one of ``KARNI_TERMS["paths"]`` (default ``["/api/"]``), except the
   paths :meth:`TermsGateMiddleware.is_exempt` leaves open. Staff and
   superusers are gated like everyone.

Changing ``KARNI_TERMS["version"]`` makes everyone accept again.
``"required": False`` keeps the routes and the record and gates nothing.
Unset, there are no routes and no gate.

Whether a user accepted a version is cached per (user, version) in the
default cache, so a gated request costs no query after the first. A new
acceptance clears that answer at once and stores it when its transaction
commits (:func:`remember_acceptance`).

Override / escape hatch: subclass :class:`TermsGateMiddleware` (``covers``,
``is_exempt``, ``user_pk``, ``accepted``, ``refuse``) and list the subclass
in ``MIDDLEWARE`` in its place; call :func:`accept` and :func:`status` from a
view of your own; keep a path open with ``KARNI_TERMS["exempt"]``.
"""

from __future__ import annotations

import functools
import hashlib
import ipaddress
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import MiddlewareNotUsed
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponseBase, JsonResponse
from django.urls import NoReverseMatch, get_script_prefix, reverse

from karni.errorcodes import KarniError

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

    from karni.accounts.models import TermsAcceptance

__all__ = [
    "ACCEPTED_TTL",
    "DEFAULT_PATHS",
    "KNOWN_KEYS",
    "NOT_ACCEPTED_TTL",
    "USER_AGENT_MAX_LENGTH",
    "VERSION_MAX_LENGTH",
    "PermanentRecordError",
    "TermsConfig",
    "TermsGateMiddleware",
    "TermsRefused",
    "accept",
    "auth_mount",
    "cache_key",
    "client_ip",
    "config",
    "configured",
    "gate_on",
    "has_accepted",
    "me_status",
    "not_accepted",
    "remember_acceptance",
    "status",
    "turned_off",
    "wrong_version",
]

#: Experimental. The URL prefixes the gate covers unless ``KARNI_TERMS["paths"]`` says otherwise.
DEFAULT_PATHS: Final = ("/api/",)
#: Experimental. The keys ``KARNI_TERMS`` may have.
KNOWN_KEYS: Final = frozenset({"version", "url", "required", "paths", "exempt"})
#: Experimental. The longest ``KARNI_TERMS["version"]`` (the column's length).
VERSION_MAX_LENGTH: Final = 100
#: Experimental. ``User-Agent`` headers are stored up to this many characters.
USER_AGENT_MAX_LENGTH: Final = 1024
#: Experimental. Seconds the cache keeps "this user accepted this version".
ACCEPTED_TTL: Final = 7 * 24 * 60 * 60
#: Experimental. Seconds the cache keeps "this user has not accepted this version".
NOT_ACCEPTED_TTL: Final = 60

_CACHE_PREFIX: Final = "karni:terms"
_AUTH_MOUNT_ROUTE: Final = "karni-accounts-login"


# refusals


class TermsRefused(KarniError):
    """Experimental. A refusal of the terms flow, with its code and the HTTP answer.

    ``E245`` (403) from the gate for a user who has not accepted the current
    version, ``E246`` (400) from :func:`accept` for another version, ``E249``
    (404) from the routes while ``KARNI_TERMS`` is unset. ``version`` and
    ``url`` are the current terms, sent back so the client can show them.
    """

    def __init__(
        self, message: str, *, code: str, status: int, version: str = "", url: str = ""
    ) -> None:
        super().__init__(message, code=code)
        self.status = status
        self.version = version
        self.url = url

    def payload(self) -> dict[str, Any]:
        """The response body: ``{"code", "detail"}``, plus ``version`` and ``url`` when set."""
        body: dict[str, Any] = {"code": self.code, "detail": str(self)}
        if self.code != "E249":
            body["version"] = self.version
            body["url"] = self.url
        return body


class PermanentRecordError(KarniError):
    """Experimental. A write that would rewrite a ``TermsAcceptance`` row (``E247``).

    Raised by saving an existing row, by ``delete()``, ``hard_delete()`` and
    ``restore()``, and by ``update()`` or ``delete()`` on a queryset of them.
    """

    code = "E247"


def not_accepted(terms: TermsConfig, accept_path: str = "terms/accept/") -> TermsRefused:
    """Experimental. The gate's ``E245`` (403): the current terms are not accepted.

    ``accept_path`` is where the client accepts them, named in the message.
    """
    return TermsRefused(
        f"Accept the terms (version {terms.version}) to continue. Read them at "
        f"{terms.url or 'the url in this answer'}, then accept them with POST {accept_path} "
        f'and {{"version": "{terms.version}"}}.',
        code="E245",
        status=403,
        version=terms.version,
        url=terms.url,
    )


def wrong_version(terms: TermsConfig, sent: str) -> TermsRefused:
    """Experimental. :func:`accept`'s ``E246`` (400): ``sent`` is not the current version."""
    return TermsRefused(
        f"Version {sent!r} is not the current terms. The current version is "
        f"{terms.version!r}: show the terms at {terms.url or 'the url in this answer'} and "
        "accept that version.",
        code="E246",
        status=400,
        version=terms.version,
        url=terms.url,
    )


def turned_off() -> TermsRefused:
    """Experimental. The ``E249`` (404) the routes answer while ``KARNI_TERMS`` is unset."""
    return TermsRefused(
        "Terms acceptance is turned off: KARNI_TERMS is not set.", code="E249", status=404
    )


# settings


@dataclass(frozen=True)
class TermsConfig:
    """Experimental. ``KARNI_TERMS`` as read: the terms to accept, and where the gate applies."""

    #: The version every signed-in user must accept, e.g. ``"2026-11"``.
    version: str
    #: Where the terms are, for the client to show: a path or a full URL.
    url: str
    #: Whether the gate refuses a user who has not accepted. ``False`` gates nothing.
    required: bool = True
    #: The URL prefixes the gate covers.
    paths: tuple[str, ...] = DEFAULT_PATHS
    #: More prefixes the gate leaves open, on top of the auth mount.
    exempt: tuple[str, ...] = ()


def _prefixes(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, list | tuple):
        return tuple(str(entry) for entry in value)
    return default


def config() -> TermsConfig | None:
    """Experimental. ``KARNI_TERMS`` as a :class:`TermsConfig`, or ``None`` while it is unset.

    Read on every call, so ``override_settings`` works. Startup validation
    (``E504``) refuses a malformed value, so this never guesses.
    """
    raw = getattr(settings, "KARNI_TERMS", None)
    if not isinstance(raw, Mapping) or not raw:
        return None
    return TermsConfig(
        version=str(raw.get("version") or ""),
        url=str(raw.get("url") or ""),
        required=bool(raw.get("required", True)),
        paths=_prefixes(raw.get("paths"), DEFAULT_PATHS),
        exempt=_prefixes(raw.get("exempt"), ()),
    )


def configured() -> bool:
    """Experimental. Whether ``KARNI_TERMS`` is set: the routes exist and ``me/`` has ``terms``."""
    return config() is not None


def gate_on() -> bool:
    """Experimental. Whether ``KARNI_TERMS`` is set and requires acceptance: the gate runs."""
    terms = config()
    return terms is not None and terms.required


# the record and its cache


def cache_key(user_pk: Any, version: str) -> str:
    """Experimental. The default-cache key of "did this user accept this version"."""
    digest = hashlib.sha256(version.encode("utf-8")).hexdigest()[:16]
    return f"{_CACHE_PREFIX}:{digest}:{user_pk}"


def has_accepted(user_pk: Any, version: str) -> bool:
    """Experimental. Whether the user with this primary key accepted ``version``.

    The answer is cached per (user, version): ``ACCEPTED_TTL`` seconds for
    yes, ``NOT_ACCEPTED_TTL`` for no. Only a cache miss runs a query.
    """
    key = cache_key(user_pk, version)
    known = cache.get(key)
    if known is not None:
        return bool(known)
    from karni.accounts.models import TermsAcceptance

    accepted = TermsAcceptance.objects.filter(user_id=user_pk, version=version).exists()
    cache.set(key, accepted, ACCEPTED_TTL if accepted else NOT_ACCEPTED_TTL)
    return accepted


def remember_acceptance(user_pk: Any, version: str, *, using: str | None = None) -> None:
    """Experimental. A new acceptance: clear the cached answer now, store yes on commit.

    Clearing at once means the next request reads the row (also inside the
    transaction that wrote it). Storing on commit means a rolled-back
    acceptance is never cached. :meth:`TermsAcceptance.save` calls it.
    """
    key = cache_key(user_pk, version)
    cache.delete(key)
    transaction.on_commit(lambda: cache.set(key, True, ACCEPTED_TTL), using=using)


def _valid_ip(value: Any) -> str | None:
    try:
        return str(ipaddress.ip_address(str(value or "").strip()))
    except ValueError:
        return None


def client_ip(request: Any) -> str | None:
    """Experimental. The caller's IP address the way Karni's throttles read it, or ``None``.

    DRF's ``get_ident`` honours ``NUM_PROXIES`` (``KARNI_NUM_PROXIES``): with
    a proxy in front, the address it appended to ``X-Forwarded-For``.
    Anything that is not an IP address falls back to ``REMOTE_ADDR``.
    """
    from rest_framework.throttling import BaseThrottle

    meta = getattr(request, "META", {}) or {}
    for candidate in (BaseThrottle().get_ident(request), meta.get("REMOTE_ADDR")):
        found = _valid_ip(candidate)
        if found is not None:
            return found
    return None


def accept(
    user: AbstractBaseUser,
    version: str,
    *,
    ip: str | None = None,
    user_agent: str = "",
    client: Any = None,
) -> tuple[TermsAcceptance, bool]:
    """Experimental. Record that ``user`` accepted ``version``: ``(row, created)``.

    ``version`` must be the current ``KARNI_TERMS["version"]``, else
    :class:`TermsRefused` ``E246``. A version the user already accepted
    returns the existing row with ``created`` False (also when a parallel
    request wrote it first). ``ip`` must be an IP address (anything else is
    stored as ``None``), ``user_agent`` is cut to ``USER_AGENT_MAX_LENGTH``
    characters, and ``client`` is stored as given (JSON).
    """
    terms = config()
    if terms is None:
        raise turned_off()
    if version != terms.version:
        raise wrong_version(terms, version)
    from karni.accounts.models import TermsAcceptance

    found = TermsAcceptance.objects.filter(user=user, version=version).first()
    if found is not None:
        return found, False
    try:
        with transaction.atomic():
            row = TermsAcceptance.objects.create(
                user=user,
                version=version,
                ip=_valid_ip(ip),
                user_agent=str(user_agent or "")[:USER_AGENT_MAX_LENGTH],
                client=client,
            )
    except IntegrityError:
        # A parallel request recorded the same acceptance first.
        found = TermsAcceptance.objects.filter(user=user, version=version).first()
        if found is None:
            raise
        return found, False
    return row, True


def status(user: AbstractBaseUser) -> dict[str, Any]:
    """Experimental. The ``terms/`` answer for ``user``: the terms, and whether they accepted them.

    ``{"version", "url", "required", "accepted", "accepted_at"}`` with
    ``accepted_at`` ``None`` when they have not. Needs ``KARNI_TERMS`` set
    (:func:`turned_off` otherwise).
    """
    terms = config()
    if terms is None:
        raise turned_off()
    from karni.accounts.models import TermsAcceptance

    row = (
        TermsAcceptance.objects.filter(user=user, version=terms.version).only("accepted_at").first()
    )
    return {
        "version": terms.version,
        "url": terms.url,
        "required": terms.required,
        "accepted": row is not None,
        "accepted_at": row.accepted_at if row is not None else None,
    }


def me_status(user: AbstractBaseUser) -> dict[str, Any] | None:
    """Experimental. The ``terms`` of ``me/``: ``{"required", "version", "url", "accepted"}``.

    ``None`` while ``KARNI_TERMS`` is unset. ``accepted`` comes from the same
    cache as the gate, so it costs no query once the gate has answered.
    """
    terms = config()
    if terms is None:
        return None
    return {
        "required": terms.required,
        "version": terms.version,
        "url": terms.url,
        "accepted": has_accepted(user.pk, terms.version),
    }


# the gate


@functools.lru_cache(maxsize=32)
def _mount(urlconf: Any, script_prefix: str) -> str | None:
    try:
        login = reverse(_AUTH_MOUNT_ROUTE, urlconf=urlconf)
    except NoReverseMatch:
        return None
    if script_prefix != "/" and login.startswith(script_prefix):
        login = "/" + login[len(script_prefix) :]
    if not login.endswith("/login/"):
        return None
    mount = login[: -len("login/")]
    # Mounted at the root, every path would be "under" it: the accounts views
    # are still left open by their module (_always_open).
    return mount if mount != "/" else None


def auth_mount(urlconf: Any = None) -> str | None:
    """Experimental. Where ``karni.accounts.urls`` is mounted (``"/api/auth/"``), or ``None``.

    Found by reversing ``login/``, so it follows the project's URLconf. The
    gate leaves every path under it open. ``None`` when the accounts URLs
    are not included, or are included at the root.
    """
    key = urlconf if urlconf is not None else settings.ROOT_URLCONF
    return _mount(key, get_script_prefix())


def _accept_path(urlconf: Any) -> str:
    """The path of ``terms/accept/`` for the refusal's message, or the bare route."""
    try:
        return reverse("karni-accounts-terms-accept", urlconf=urlconf)
    except NoReverseMatch:
        return "terms/accept/"


def _always_open(view_func: Any) -> bool:
    """Karni's account API views wherever they are mounted, and the OpenAPI schema and docs.

    Only class-based views count: Karni's admin pages (functions and admin
    methods) follow ``paths`` like any page. The schema is per role
    metadata, not data, and @karni/ui reads the auth mode from it before
    anyone can accept anything.
    """
    view = getattr(view_func, "cls", None) or getattr(view_func, "view_class", None)
    if not isinstance(view, type):
        return False
    if str(view.__module__).startswith("karni.accounts."):
        return True
    try:
        from drf_spectacular.views import (
            SpectacularAPIView,
            SpectacularRedocView,
            SpectacularSwaggerView,
        )
    except ImportError:  # pragma: no cover - drf-spectacular is a karni dependency
        return False
    return issubclass(view, SpectacularAPIView | SpectacularRedocView | SpectacularSwaggerView)


def _jwt_authenticator() -> Any | None:
    """An instance of the JWT class in DRF's ``DEFAULT_AUTHENTICATION_CLASSES``, or ``None``."""
    from rest_framework.settings import api_settings
    from rest_framework_simplejwt.authentication import JWTAuthentication

    for authentication in api_settings.DEFAULT_AUTHENTICATION_CLASSES:
        if isinstance(authentication, type) and issubclass(authentication, JWTAuthentication):
            return authentication()
    return None


def _token_user_pk(authenticator: Any, token: Any) -> Any | None:
    """The primary key of the token's user, read from its claim without a query when possible."""
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.settings import api_settings as jwt_settings

    user_id = token.get(jwt_settings.USER_ID_CLAIM)
    if user_id is None:
        return None
    if jwt_settings.USER_ID_FIELD in ("pk", get_user_model()._meta.pk.name):
        return user_id
    return authenticator.get_user(token).pk


class TermsGateMiddleware:
    """Experimental. Refuses a signed-in user who has not accepted the current terms (403 ``E245``).

    ``karni_settings()`` lists it in ``MIDDLEWARE`` after Django's
    ``AuthenticationMiddleware``. It removes itself from the chain at startup
    (``MiddlewareNotUsed``) unless ``KARNI_TERMS`` requires acceptance, so
    it costs nothing otherwise. It runs once the URL is resolved
    (``process_view``):

    1. a path that starts with none of ``KARNI_TERMS["paths"]`` passes
       (:meth:`covers`), so the admin and a public site are not gated by
       default;
    2. an exempt path passes (:meth:`is_exempt`): the auth mount and every
       route under it, ``KARNI_TERMS["exempt"]``, Karni's account views
       wherever they are mounted, and drf-spectacular's schema and docs;
    3. the user comes from a Bearer token, validated by the JWT class DRF
       authenticates with, else from the session (``request.user``). A
       request without a user, or with a token DRF would refuse, passes:
       the view decides (:meth:`user_pk`);
    4. a user who accepted the current version passes (:meth:`accepted`,
       cached), and everyone else, staff and superusers included, gets the
       403 of :meth:`refuse`: ``{"code": "E245", "detail", "version", "url"}``.

    Override / escape hatch: subclass it, override any of those methods, and
    list the subclass in ``MIDDLEWARE`` in its place (``karni.E248`` accepts
    a subclass). ``KARNI_TERMS["exempt"]`` keeps a path open without code.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        if not gate_on():
            raise MiddlewareNotUsed
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        return self.get_response(request)

    def process_view(
        self,
        request: HttpRequest,
        view_func: Callable[..., Any],
        view_args: Any,
        view_kwargs: Any,
    ) -> HttpResponseBase | None:
        terms = config()
        if terms is None or not terms.required:
            return None
        if not self.covers(request, terms) or self.is_exempt(request, view_func, terms):
            return None
        user_pk = self.user_pk(request)
        if user_pk is None or self.accepted(user_pk, terms):
            return None
        return self.refuse(request, terms)

    def covers(self, request: HttpRequest, terms: TermsConfig) -> bool:
        """Whether the request's path starts with one of ``KARNI_TERMS["paths"]``."""
        path = request.path_info
        return any(path.startswith(prefix) for prefix in terms.paths)

    def is_exempt(
        self, request: HttpRequest, view_func: Callable[..., Any], terms: TermsConfig
    ) -> bool:
        """Whether the request stays open before acceptance (see the class docstring)."""
        path = request.path_info
        mount = auth_mount(getattr(request, "urlconf", None))
        if mount is not None and path.startswith(mount):
            return True
        if any(path.startswith(prefix) for prefix in terms.exempt):
            return True
        return _always_open(view_func)

    def user_pk(self, request: HttpRequest) -> Any | None:
        """The signed-in user's primary key, or ``None`` for a request the view must decide."""
        from rest_framework.exceptions import AuthenticationFailed

        authenticator = _jwt_authenticator()
        if authenticator is not None:
            try:
                header = authenticator.get_header(request)
                raw = authenticator.get_raw_token(header) if header is not None else None
                if raw is not None:
                    return _token_user_pk(authenticator, authenticator.get_validated_token(raw))
            except AuthenticationFailed:
                return None  # DRF answers 401 in the view
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return user.pk
        return None

    def accepted(self, user_pk: Any, terms: TermsConfig) -> bool:
        """Whether that user accepted the current version (:func:`has_accepted`, cached)."""
        return has_accepted(user_pk, terms.version)

    def refuse(self, request: HttpRequest, terms: TermsConfig) -> HttpResponseBase:
        """The 403 ``E245`` answer: ``{"code", "detail", "version", "url"}``."""
        refused = not_accepted(terms, _accept_path(getattr(request, "urlconf", None)))
        response = JsonResponse(refused.payload(), status=refused.status)
        response["Cache-Control"] = "no-store"
        return response
