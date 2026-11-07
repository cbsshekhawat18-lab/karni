"""Experimental. Sign-in with a Google, Microsoft or Apple ID token, in JWT and session mode.

A mobile app or a single-page app signs the user in with the provider's own
SDK (Google Identity Services, MSAL, Sign in with Apple), receives an OpenID
Connect ID token, and posts it to ``POST <auth mount>/social/<provider>/``.
Karni verifies the token offline and answers exactly like ``login/``: a token
pair in JWT mode, a session in session mode, or the 2FA gate. Nothing here
calls the provider except to fetch its public signing keys.

The pieces, each an escape hatch:

* **Providers** are small classes (:class:`IdTokenProvider`, with
  :class:`GoogleProvider`, :class:`MicrosoftProvider` and
  :class:`AppleProvider` built in) that say where the keys are, which issuer
  and algorithms to accept and how to read the email and name. A project adds
  or replaces one with ``"class": "<dotted path>"`` in its
  ``KARNI_SOCIAL_TOKEN_PROVIDERS`` entry.
* **Key sets** (JWKS) are fetched by the function
  ``KARNI_SOCIAL_TOKEN_JWKS_FETCHER`` names (:func:`fetch_jwks` by default)
  and kept in the default cache for ``KARNI_SOCIAL_TOKEN_JWKS_TTL`` seconds.
  A token whose ``kid`` is not in the cached set fetches it again, at most
  once a minute per provider (:func:`signing_key`).
* :func:`verify_id_token` checks the signature, ``exp``, ``iat``, ``nbf``,
  ``iss``, ``aud`` (one of the configured client ids) and the nonce.
* :func:`sign_in` applies the sign-up and linking policy
  (``KARNI_SOCIAL_TOKEN_SIGNUP``, ``KARNI_SOCIAL_TOKEN_LINK_VERIFIED``) and
  links the identity in :class:`karni.accounts.models.SocialIdentity`.

Every refusal is a :class:`SocialTokenRefused` with a stable code
(``E215``-``E227``) and the HTTP status the view answers with.

RS256 and ES256 need the ``cryptography`` package:
``pip install 'karni[social-token]'`` (``E509`` without it).
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import re
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Final, cast

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from karni.errorcodes import KarniError
from karni.exceptions import KarniImportError, KarniImproperlyConfigured, KarniValueError
from karni.imports import import_setting

if TYPE_CHECKING:
    from karni.accounts.models import AbstractKarniUser, SocialIdentity

__all__ = [
    "BUILTIN_PROVIDERS",
    "SIGNUP_POLICIES",
    "AppleProvider",
    "GoogleProvider",
    "IdTokenProvider",
    "MicrosoftProvider",
    "SignInResult",
    "SocialTokenRefused",
    "configured_providers",
    "fetch_jwks",
    "get_provider",
    "mark_used",
    "sign_in",
    "signing_key",
    "signup_policy",
    "verify_id_token",
]

#: Experimental. The providers Karni ships, by the name their route uses.
BUILTIN_PROVIDERS: Final[dict[str, str]] = {
    "google": "karni.accounts.social_token.GoogleProvider",
    "microsoft": "karni.accounts.social_token.MicrosoftProvider",
    "apple": "karni.accounts.social_token.AppleProvider",
}

#: Experimental. The values ``KARNI_SOCIAL_TOKEN_SIGNUP`` takes (``None`` follows registration).
SIGNUP_POLICIES: Final[tuple[str, ...]] = ("open", "approval", "existing")

#: Route names a provider may not take: allauth's own pages live under ``social/`` too
#: (``social/signup/``, ``social/login/cancelled/``, ``social/login/error/``).
RESERVED_NAMES: Final[frozenset[str]] = frozenset({"login", "signup"})

#: A provider name: the URL segment of its route and ``SocialIdentity.provider``.
PROVIDER_NAME_RE: Final = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

_GUID_RE: Final = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
_EMAIL_RE: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DEFAULT_FETCHER: Final = "karni.accounts.social_token.fetch_jwks"
_FETCH_TIMEOUT: Final = 5.0
_MAX_JWKS_BYTES: Final = 1_000_000
#: Seconds between two fetches of a provider's key set for an unknown ``kid``.
REFETCH_INTERVAL: Final = 60
_JWKS_KEY: Final = "karni:social-token:jwks:{provider}"
_REFETCH_KEY: Final = "karni:social-token:jwks-refetch:{provider}"


# refusals


class SocialTokenRefused(KarniError):
    """Experimental. A refused ID-token sign-in, with its code and the HTTP answer.

    ``code`` is the registry code (``E215``-``E227``), ``status`` the HTTP
    status the view answers with (401 for the token, 400 for the policy, 404
    for an unknown provider, 202 for an account awaiting approval) and
    ``reason`` a short word for the ``accounts.social.refused`` log event.
    ``email`` is the token's address when it was read, so the log can carry
    its fingerprint (never the address itself).
    """

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        code: str,
        status: int,
        email: str | None = None,
    ) -> None:
        super().__init__(message, code=code)
        self.reason = reason
        self.status = status
        self.email = email

    def payload(self) -> dict[str, Any]:
        """The response body: ``{"code", "detail"}`` (plus ``awaiting_approval`` for E224)."""
        body: dict[str, Any] = {"code": self.code, "detail": str(self)}
        if self.code == "E224":
            body["awaiting_approval"] = True
        return body


def _refused(reason: str, message: str, code: str, status: int = 401) -> SocialTokenRefused:
    return SocialTokenRefused(reason, message, code=code, status=status)


# providers


def _truthy(value: Any) -> bool:
    """A boolean claim: ``True``, or the strings ``"true"`` / ``"1"`` (Apple sends a string)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return isinstance(value, str) and value.strip().lower() in {"true", "1"}


def _email_shaped(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and _EMAIL_RE.match(value.strip()) else None


def _string_list_errors(
    setting: str, value: Any, *, required: bool, allow_empty: bool = False
) -> list[str]:
    if value is None and not required:
        return []
    if (
        not isinstance(value, list | tuple)
        or (required and not value and not allow_empty)
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        need = "a non-empty list" if required else "a list"
        return [f"{setting} = {value!r} must be {need} of non-empty strings"]
    return []


class IdTokenProvider:
    """Experimental. One identity provider whose ID tokens Karni accepts.

    A subclass sets :attr:`jwks_url`, :attr:`issuers` and, when the provider
    does not sign with RS256, :attr:`algorithms`. The methods read the claims
    Karni needs. Override them when a provider names them differently.

    An instance holds the provider's entry of ``KARNI_SOCIAL_TOKEN_PROVIDERS``
    (``config``) and the name its route uses (``name``).

    Override / escape hatch: subclass, then name the class in the entry,
    ``{"myidp": {"class": "myapp.idtokens.MyProvider", "client_ids": [...]}}``.
    The same key replaces a built-in provider.
    """

    #: Where the provider publishes its signing keys (a JWKS document).
    jwks_url: ClassVar[str] = ""
    #: The ``iss`` values a token may carry.
    issuers: ClassVar[tuple[str, ...]] = ()
    #: The signature algorithms accepted. Never ``none`` or an HMAC algorithm.
    algorithms: ClassVar[tuple[str, ...]] = ("RS256",)
    #: The keys an entry of ``KARNI_SOCIAL_TOKEN_PROVIDERS`` may hold for this provider.
    config_keys: ClassVar[frozenset[str]] = frozenset({"client_ids", "require_nonce", "class"})

    def __init__(self, name: str, config: Mapping[str, Any]) -> None:
        self.name = name
        self.config: dict[str, Any] = dict(config)

    @classmethod
    def config_errors(cls, name: str, config: Mapping[str, Any]) -> list[str]:
        """Problems with the entry ``config`` for this provider, as startup validation lines."""
        setting = f"KARNI_SOCIAL_TOKEN_PROVIDERS[{name!r}]"
        errors = _string_list_errors(
            f"{setting}['client_ids']", config.get("client_ids"), required=True, allow_empty=True
        )
        if "require_nonce" in config and not isinstance(config["require_nonce"], bool):
            errors.append(
                f"{setting}['require_nonce'] = {config['require_nonce']!r} must be a bool"
            )
        unknown = sorted(str(key) for key in config if key not in cls.config_keys)
        if unknown:
            errors.append(
                f"{setting} has unknown keys {unknown}: {cls.__name__} reads "
                f"{sorted(cls.config_keys)}"
            )
        return errors

    @property
    def client_ids(self) -> list[str]:
        """The audiences a token may be issued to: every web, iOS and Android client id."""
        return [str(value) for value in self.config.get("client_ids") or ()]

    @property
    def require_nonce(self) -> bool:
        """Whether a request must send a nonce (``"require_nonce": True`` in the entry)."""
        return bool(self.config.get("require_nonce", False))

    def check_issuer(self, claims: Mapping[str, Any]) -> None:
        """Refuse a token whose ``iss`` is not one of :attr:`issuers` (``E217``)."""
        if claims.get("iss") not in self.issuers:
            raise _refused(
                "wrong_issuer",
                f"The token's issuer {claims.get('iss')!r} is not {self.name}'s "
                f"({', '.join(self.issuers)}).",
                "E217",
            )

    def subject(self, claims: Mapping[str, Any]) -> str:
        """The provider's stable id for the person: ``sub``."""
        return str(claims["sub"])

    def email(self, claims: Mapping[str, Any]) -> str | None:
        """The token's email address, or ``None``."""
        return _email_shaped(claims.get("email"))

    def email_verified(self, claims: Mapping[str, Any]) -> bool:
        """Whether the provider verified :meth:`email` (the ``email_verified`` claim)."""
        return _truthy(claims.get("email_verified"))

    def names(self, claims: Mapping[str, Any]) -> tuple[str, str]:
        """``(first name, last name)`` from ``given_name`` and ``family_name``."""
        first, last = claims.get("given_name"), claims.get("family_name")
        return (
            first.strip() if isinstance(first, str) else "",
            last.strip() if isinstance(last, str) else "",
        )


class GoogleProvider(IdTokenProvider):
    """Experimental. Google ID tokens (Google Identity Services, Sign-In for iOS and Android).

    ``iss`` is ``accounts.google.com`` or ``https://accounts.google.com``, and
    the ``email_verified`` claim says whether the address is verified.
    """

    jwks_url = "https://www.googleapis.com/oauth2/v3/certs"
    issuers = ("accounts.google.com", "https://accounts.google.com")


class MicrosoftProvider(IdTokenProvider):
    """Experimental. Microsoft identity platform v2.0 ID tokens (MSAL), work, school or personal.

    The issuer carries the tenant: ``https://login.microsoftonline.com/{tid}/v2.0``
    must match the token's own ``tid``, and the tenant must be one the entry's
    ``tenants`` allows: ``common`` (any, the default), ``organizations`` (any
    work or school tenant), ``consumers`` (personal accounts) or tenant ids.

    Microsoft ID tokens carry no reliable ``email_verified``: an address
    counts as verified only when the token has the optional ``xms_edov``
    claim true, or comes from a tenant listed in ``trusted_tenants``. The
    email is ``email``, else ``preferred_username`` when it is an address.
    The subject is ``<tid>:<oid>`` (stable across app registrations of one
    tenant), or ``sub`` when the token has no ``oid``.
    """

    jwks_url = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
    config_keys = IdTokenProvider.config_keys | {"tenants", "trusted_tenants"}
    #: The tenant id of personal Microsoft accounts.
    CONSUMERS_TENANT: ClassVar[str] = "9188040d-6c67-4c5b-b112-36a304b66dad"
    #: The ``tenants`` values that are not tenant ids.
    TENANT_GROUPS: ClassVar[frozenset[str]] = frozenset({"common", "organizations", "consumers"})

    @classmethod
    def config_errors(cls, name: str, config: Mapping[str, Any]) -> list[str]:
        errors = super().config_errors(name, config)
        setting = f"KARNI_SOCIAL_TOKEN_PROVIDERS[{name!r}]"
        for key, groups in (("tenants", cls.TENANT_GROUPS), ("trusted_tenants", frozenset())):
            value = config.get(key)
            problems = _string_list_errors(f"{setting}[{key!r}]", value, required=False)
            if problems:
                errors += problems
                continue
            for tenant in value or ():
                if tenant.lower() not in groups and not _GUID_RE.match(tenant):
                    allowed = f"{', '.join(sorted(groups))} or " if groups else ""
                    errors.append(
                        f"{setting}[{key!r}] entry {tenant!r} is not {allowed}a tenant id "
                        "(a GUID such as 72f988bf-86f1-41af-91ab-2d7cd011db47)"
                    )
        return errors

    @property
    def tenants(self) -> list[str]:
        return [str(t).lower() for t in self.config.get("tenants") or ("common",)]

    @property
    def trusted_tenants(self) -> list[str]:
        return [str(t).lower() for t in self.config.get("trusted_tenants") or ()]

    def tenant_allowed(self, tid: str) -> bool:
        """Whether ``tenants`` lets the tenant ``tid`` in."""
        tid, allowed = tid.lower(), set(self.tenants)
        consumer = tid == self.CONSUMERS_TENANT
        return (
            "common" in allowed
            or ("consumers" in allowed and consumer)
            or ("organizations" in allowed and not consumer)
            or tid in allowed
        )

    def check_issuer(self, claims: Mapping[str, Any]) -> None:
        tid = claims.get("tid")
        if not isinstance(tid, str) or not _GUID_RE.match(tid):
            raise _refused(
                "wrong_issuer", "The Microsoft token has no tenant id (tid claim).", "E217"
            )
        expected = f"https://login.microsoftonline.com/{tid}/v2.0"
        if claims.get("iss") != expected:
            raise _refused(
                "wrong_issuer",
                f"The Microsoft token's issuer {claims.get('iss')!r} is not {expected!r}, the "
                "v2.0 issuer of its own tenant.",
                "E217",
            )
        if not self.tenant_allowed(tid):
            raise _refused(
                "tenant_not_allowed",
                f"The Microsoft tenant {tid} is not in KARNI_SOCIAL_TOKEN_PROVIDERS"
                f"[{self.name!r}]['tenants'] ({', '.join(self.tenants)}).",
                "E217",
            )

    def subject(self, claims: Mapping[str, Any]) -> str:
        oid = claims.get("oid")
        if isinstance(oid, str) and oid:
            return f"{str(claims['tid']).lower()}:{oid.lower()}"
        return str(claims["sub"])

    def email(self, claims: Mapping[str, Any]) -> str | None:
        return _email_shaped(claims.get("email")) or _email_shaped(claims.get("preferred_username"))

    def email_verified(self, claims: Mapping[str, Any]) -> bool:
        if _truthy(claims.get("xms_edov")):
            return True
        return str(claims.get("tid", "")).lower() in self.trusted_tenants

    def names(self, claims: Mapping[str, Any]) -> tuple[str, str]:
        first, last = super().names(claims)
        display = claims.get("name")
        if not first and not last and isinstance(display, str):
            return display.strip(), ""
        return first, last


class AppleProvider(IdTokenProvider):
    """Experimental. Sign in with Apple ID tokens (native apps and the web).

    ``iss`` is ``https://appleid.apple.com``. ``email_verified`` may be the
    string ``"true"``, and private relay addresses
    (``...@privaterelay.appleid.com``) are accepted like any other. Apple
    puts no name in the token: the app sends it in the request body on the
    user's first sign-in, and Karni uses it only for a new account.
    ``client_ids`` holds the service id (web) and the bundle id (iOS).
    """

    jwks_url = "https://appleid.apple.com/auth/keys"
    issuers = ("https://appleid.apple.com",)

    def names(self, claims: Mapping[str, Any]) -> tuple[str, str]:
        return "", ""


def configured_providers() -> dict[str, Mapping[str, Any]]:
    """Experimental. ``KARNI_SOCIAL_TOKEN_PROVIDERS``: provider name -> its entry."""
    value = getattr(settings, "KARNI_SOCIAL_TOKEN_PROVIDERS", None) or {}
    return dict(value) if isinstance(value, Mapping) else {}


def provider_class(name: str, config: Mapping[str, Any]) -> type[IdTokenProvider]:
    """The class an entry names (``"class"``), else the built-in one for ``name``."""
    path = config.get("class") or BUILTIN_PROVIDERS.get(name)
    if not path:
        raise KarniImproperlyConfigured(
            f"KARNI_SOCIAL_TOKEN_PROVIDERS[{name!r}] is not a built-in provider "
            f"({', '.join(BUILTIN_PROVIDERS)}). Add 'class': '<dotted path of an "
            "IdTokenProvider subclass>' to the entry.",
            code="E504",
        )
    cls = import_setting(f"KARNI_SOCIAL_TOKEN_PROVIDERS[{name!r}]['class']", path)
    if not (isinstance(cls, type) and issubclass(cls, IdTokenProvider)):
        raise KarniImproperlyConfigured(
            f"KARNI_SOCIAL_TOKEN_PROVIDERS[{name!r}]['class'] ({path!r}) is not a subclass of "
            "karni.accounts.social_token.IdTokenProvider.",
            code="E506",
        )
    return cls


def get_provider(name: str) -> IdTokenProvider | None:
    """Experimental. The configured provider called ``name``, or ``None`` when there is none."""
    config = configured_providers().get(name)
    if not isinstance(config, Mapping):
        return None
    return provider_class(name, config)(name, config)


# key sets


def fetch_jwks(url: str) -> dict[str, Any]:
    """Experimental. Fetch the JWKS document at ``url`` (HTTPS, 5 second timeout).

    The default ``KARNI_SOCIAL_TOKEN_JWKS_FETCHER``. Override / escape hatch:
    name another function ``(url) -> dict`` in that setting, for a proxy, a
    pinned set of keys or tests (Karni's own tests never touch the network).
    """
    if not url.startswith("https://"):
        raise KarniValueError(f"A JWKS URL must use https, got {url!r}.", code="E219")
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "karni"}
    )
    with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT) as response:
        document = json.loads(response.read(_MAX_JWKS_BYTES))
    if not isinstance(document, dict):
        raise KarniValueError(f"{url} did not return a JSON object.", code="E219")
    return document


def _fetcher() -> Callable[[str], Mapping[str, Any]]:
    path = getattr(settings, "KARNI_SOCIAL_TOKEN_JWKS_FETCHER", None) or _DEFAULT_FETCHER
    return cast(
        "Callable[[str], Mapping[str, Any]]",
        import_setting("KARNI_SOCIAL_TOKEN_JWKS_FETCHER", path),
    )


def _jwks_ttl() -> int:
    return int(getattr(settings, "KARNI_SOCIAL_TOKEN_JWKS_TTL", 21600))


def _fetch_keys(provider: IdTokenProvider) -> list[dict[str, Any]]:
    """Fetch the provider's key set and cache it. A failure is ``E219`` (503).

    A fetcher setting that does not import is a configuration error (``E506``),
    raised as such, not a 503.
    """
    fetcher = _fetcher()
    try:
        document = fetcher(provider.jwks_url)
    except Exception as exc:  # the network, a proxy, a bad document: all a 503
        raise _refused(
            "keys_unavailable",
            f"Karni could not fetch {provider.name}'s signing keys from {provider.jwks_url} "
            f"({type(exc).__name__}).",
            "E219",
            status=503,
        ) from exc
    raw = document.get("keys") if isinstance(document, Mapping) else None
    keys = [dict(key) for key in raw or () if isinstance(key, Mapping)]
    cache.set(_JWKS_KEY.format(provider=provider.name), keys, _jwks_ttl())
    return keys


def _find_key(keys: list[dict[str, Any]], kid: Any, alg: str) -> dict[str, Any] | None:
    usable = [key for key in keys if key.get("use", "sig") == "sig" and key.get("alg", alg) == alg]
    if kid is None:
        return usable[0] if len(usable) == 1 else None
    return next((key for key in usable if key.get("kid") == kid), None)


def signing_key(provider: IdTokenProvider, kid: Any, alg: str) -> Any:
    """Experimental. The public key with id ``kid`` from the provider's key set.

    The set comes from the default cache, fetched on a miss. An unknown
    ``kid`` fetches the set again, at most once every
    :data:`REFETCH_INTERVAL` seconds per provider (the provider rotated its
    keys), then refuses with ``E219``.
    """
    cached = cache.get(_JWKS_KEY.format(provider=provider.name))
    keys = cached if isinstance(cached, list) else _fetch_keys(provider)
    jwk = _find_key(keys, kid, alg)
    if jwk is None and cached is not None:
        if cache.add(_REFETCH_KEY.format(provider=provider.name), 1, REFETCH_INTERVAL):
            jwk = _find_key(_fetch_keys(provider), kid, alg)
    if jwk is None:
        raise _refused(
            "unknown_key",
            f"The token's signing key {kid!r} is not in {provider.name}'s key set.",
            "E219",
        )
    try:
        return jwt.PyJWK(jwk, algorithm=alg).key
    except jwt.PyJWTError as exc:
        raise _refused(
            "invalid_token", f"{provider.name}'s key {kid!r} is not a usable {alg} key.", "E215"
        ) from exc


# verification


def _require_cryptography() -> None:
    if importlib.util.find_spec("cryptography") is None:
        raise KarniImportError(
            "Sign-in with an ID token needs the cryptography package to verify RS256 and "
            "ES256 signatures. Run: pip install 'karni[social-token]'.",
            code="E509",
        )


def _leeway() -> int:
    return int(getattr(settings, "KARNI_SOCIAL_TOKEN_LEEWAY", 60))


def _check_nonce(provider: IdTokenProvider, claims: Mapping[str, Any], nonce: str | None) -> None:
    if not nonce:
        if provider.require_nonce:
            raise _refused(
                "nonce_missing",
                f"KARNI_SOCIAL_TOKEN_PROVIDERS[{provider.name!r}] requires a nonce, and the "
                "request sent none.",
                "E220",
            )
        return
    token_nonce = claims.get("nonce")
    hashed = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    if not isinstance(token_nonce, str) or not (
        hmac.compare_digest(token_nonce, nonce) or hmac.compare_digest(token_nonce, hashed)
    ):
        raise _refused(
            "nonce_mismatch",
            "The token's nonce is neither the nonce sent nor its SHA-256 hex digest.",
            "E220",
        )


def verify_id_token(
    provider: IdTokenProvider, token: str, *, nonce: str | None = None
) -> dict[str, Any]:
    """Experimental. Verify ``token`` for ``provider`` offline and return its claims.

    Checks, in order: the header's algorithm (one of the provider's
    :attr:`~IdTokenProvider.algorithms`), the signature against the key
    set, ``exp`` (``E218``), ``iat`` and ``nbf`` not in the future and the
    required claims (``E215``), ``aud`` against the client ids (``E216``,
    and ``azp`` when there are several audiences), the issuer (``E217``)
    and the nonce (``E220``). ``KARNI_SOCIAL_TOKEN_LEEWAY`` seconds of clock
    skew are allowed on the times.

    :raises SocialTokenRefused: on any failure.
    """
    _require_cryptography()
    if not provider.client_ids:
        # An empty list is a provider the project has not configured yet (the build writes
        # env.list(..., default=[])): nothing else stops, only signing in with it does.
        raise _refused(
            "not_configured",
            f"Sign-in with {provider.name} is not configured: "
            f"KARNI_SOCIAL_TOKEN_PROVIDERS[{provider.name!r}]['client_ids'] is empty. Set the "
            "client ids (for the build's settings block, KARNI_SOCIAL_"
            f"{provider.name.upper()}_CLIENT_IDS in the environment).",
            "E216",
            status=503,
        )
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise _refused("invalid_token", "The ID token is not a well-formed JWT.", "E215") from exc
    alg = header.get("alg")
    if alg not in provider.algorithms:
        raise _refused(
            "invalid_token",
            f"The token is signed with {alg!r}, and {provider.name} tokens use "
            f"{', '.join(provider.algorithms)}.",
            "E215",
        )
    key = signing_key(provider, header.get("kid"), str(alg))
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=[str(alg)],
            audience=provider.client_ids,
            leeway=_leeway(),
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise _refused("expired", "The ID token has expired.", "E218") from exc
    except jwt.InvalidAudienceError as exc:
        raise _refused(
            "wrong_audience",
            f"The token was issued to another application, not to one of "
            f"KARNI_SOCIAL_TOKEN_PROVIDERS[{provider.name!r}]['client_ids'].",
            "E216",
        ) from exc
    except jwt.ImmatureSignatureError as exc:
        raise _refused("not_yet_valid", f"The ID token is not valid yet ({exc}).", "E215") from exc
    except jwt.MissingRequiredClaimError as exc:
        raise _refused(
            "invalid_token", f"The ID token has no {exc.claim!r} claim.", "E215"
        ) from exc
    except jwt.PyJWTError as exc:
        raise _refused(
            "invalid_token", f"The ID token does not verify ({type(exc).__name__}).", "E215"
        ) from exc
    audiences = claims.get("aud")
    if isinstance(audiences, list) and len(audiences) > 1:
        if claims.get("azp") not in provider.client_ids:
            raise _refused(
                "wrong_audience",
                "The token names several audiences and its azp is not one of the client ids.",
                "E216",
            )
    provider.check_issuer(claims)
    _check_nonce(provider, claims, nonce)
    return claims


# the sign-up and linking policy


def signup_policy(setting: str = "KARNI_SOCIAL_TOKEN_SIGNUP") -> str:
    """Experimental. A sign-up policy setting, with ``None`` resolved from registration.

    ``setting`` is ``KARNI_SOCIAL_TOKEN_SIGNUP`` (the default) or
    ``KARNI_EMAIL_OTP_SIGNUP`` (sign-in with a code). Its value is one of
    :data:`SIGNUP_POLICIES`. ``None`` means ``"open"`` while
    ``KARNI_ACCOUNTS_REGISTRATION`` is on and ``"existing"`` when it is off.
    Read per request, so a setting assigned anywhere works.
    """
    value = getattr(settings, setting, None)
    if value:
        return str(value)
    return "open" if getattr(settings, "KARNI_ACCOUNTS_REGISTRATION", True) else "existing"


@dataclass(frozen=True)
class SignInResult:
    """Experimental. What :func:`sign_in` decided.

    ``user`` signs in unless ``awaiting_approval`` (a new, inactive account
    under the ``approval`` policy). ``created`` and ``linked`` say whether
    this sign-in created the account or linked the identity to an existing
    one.
    """

    user: AbstractKarniUser
    identity: SocialIdentity
    created: bool = False
    linked: bool = False
    awaiting_approval: bool = False


def _identity_model() -> type[SocialIdentity]:
    from karni.accounts.models import SocialIdentity

    return SocialIdentity


def _check_active(user: AbstractKarniUser, identity: SocialIdentity | None) -> None:
    """Refuse an inactive or deleted user: ``E224`` while awaiting approval, else ``E226``."""
    if user.is_active and user.deleted_at is None:
        return
    if user.deleted_at is None and identity is not None and identity.last_used_at is None:
        raise _refused(
            "awaiting_approval",
            "The account was created and awaits an administrator's approval.",
            "E224",
            status=202,
        )
    raise _refused("inactive", "This account is inactive.", "E226")


def _link(
    provider: IdTokenProvider, subject: str, user: AbstractKarniUser, email: str
) -> SocialIdentity:
    """Link the identity to ``user``, whose address the provider just verified.

    An account whose address was never verified may have been opened by
    someone else in that person's name. The provider has now proved who owns
    the address, so the account becomes verified and loses a password whoever
    opened it may know (and its refresh tokens).
    """
    from karni.accounts.api.views import email_fingerprint
    from karni.accounts.services import prove_address

    with transaction.atomic():
        cleared = prove_address(user)
        identity = _identity_model().objects.create(
            provider=provider.name, subject=subject, user=user, email_at_link=email
        )
    _log().info(
        "accounts.social.linked",
        provider=provider.name,
        user_id=str(user.pk),
        email=email_fingerprint(email),
        cleared_password=cleared,
    )
    return identity


def _create(
    provider: IdTokenProvider,
    subject: str,
    claims: Mapping[str, Any],
    email: str,
    name: Mapping[str, Any] | None,
    *,
    active: bool,
) -> tuple[AbstractKarniUser, SocialIdentity]:
    """Create the account (email verified by the provider) and its identity."""
    from karni.accounts.permissions import assign_role

    first, last = provider.names(claims)
    if not first and not last and name:
        first = str(name.get("first_name") or "").strip()
        last = str(name.get("last_name") or "").strip()
    user_model = cast("type[AbstractKarniUser]", get_user_model())
    with transaction.atomic():
        user = user_model.objects.create_user(
            email=email,
            password=None,
            first_name=first[:150],
            last_name=last[:150],
            email_verified=True,
            is_active=active,
        )
        for role in getattr(settings, "KARNI_ACCOUNTS_DEFAULT_ROLES", None) or ():
            assign_role(user, role)
        identity = _identity_model().objects.create(
            provider=provider.name, subject=subject, user=user, email_at_link=email
        )
    _log().info(
        "accounts.social.created",
        provider=provider.name,
        user_id=str(user.pk),
        active=active,
    )
    return user, identity


def _log() -> Any:
    import structlog

    return structlog.get_logger("karni.accounts")


def _sign_in_once(
    provider: IdTokenProvider, claims: Mapping[str, Any], name: Mapping[str, Any] | None
) -> SignInResult:
    identity_model = _identity_model()
    subject = provider.subject(claims)
    identity = (
        identity_model.objects.select_related("user")
        .filter(provider=provider.name, subject=subject)
        .first()
    )
    if identity is not None:
        user = cast("AbstractKarniUser", identity.user)
        _check_active(user, identity)
        return SignInResult(user=user, identity=identity)

    email = provider.email(claims)
    if email is None:
        raise _refused(
            "email_missing",
            f"The {provider.name} token carries no email address, so it matches no account.",
            "E221",
            status=400,
        )
    try:
        verified = provider.email_verified(claims)
        user_model = cast("type[AbstractKarniUser]", get_user_model())
        email = user_model.objects.normalize_email(email)
        existing = user_model.objects.filter(email__iexact=email).first()
        if existing is not None:
            if not verified:
                raise _refused(
                    "email_unverified",
                    f"{provider.name} did not verify the address, so the token is not linked "
                    "to the account that has it.",
                    "E222",
                    status=400,
                )
            _check_active(existing, None)
            link_verified = getattr(settings, "KARNI_SOCIAL_TOKEN_LINK_VERIFIED", True)
            if not link_verified and existing.has_usable_password():
                raise _refused(
                    "not_linked",
                    "An account with this address exists. KARNI_SOCIAL_TOKEN_LINK_VERIFIED is "
                    "False, so sign in with its password.",
                    "E227",
                    status=400,
                )
            identity = _link(provider, subject, existing, email)
            return SignInResult(user=existing, identity=identity, linked=True)

        policy = signup_policy()
        if policy == "existing":
            raise _refused(
                "signup_closed",
                "No account has this identity or address, and KARNI_SOCIAL_TOKEN_SIGNUP is "
                "'existing'.",
                "E223",
                status=400,
            )
        if not verified:
            raise _refused(
                "email_unverified",
                f"{provider.name} did not verify the address, so no account is created for it.",
                "E222",
                status=400,
            )
        user, identity = _create(
            provider, subject, claims, email, name, active=policy != "approval"
        )
        return SignInResult(
            user=user, identity=identity, created=True, awaiting_approval=policy == "approval"
        )
    except SocialTokenRefused as exc:
        exc.email = email
        raise


def sign_in(
    provider: IdTokenProvider,
    claims: Mapping[str, Any],
    *,
    name: Mapping[str, Any] | None = None,
) -> SignInResult:
    """Experimental. The account a verified token signs in, by the sign-up and linking policy.

    1. An identity already linked (``SocialIdentity`` by provider and
       subject) signs its user in, whatever the email is now.
    2. Otherwise the token's email is required (``E221``). An account with
       that address is linked when the provider verified it (``E222``
       otherwise) and ``KARNI_SOCIAL_TOKEN_LINK_VERIFIED`` allows it
       (``E227`` refuses an account with a password when it is False).
    3. Otherwise ``KARNI_SOCIAL_TOKEN_SIGNUP`` decides: ``open`` creates an
       active account, ``approval`` an inactive one (the result says
       ``awaiting_approval``), ``existing`` refuses (``E223``). A new account
       needs a verified address (``E222``), starts with
       ``KARNI_ACCOUNTS_DEFAULT_ROLES`` and has no password. ``name``
       (``{"first_name", "last_name"}``, Apple's first sign-in) fills the name
       only when the token has none, and only for a new account.

    An inactive user never signs in (``E226``, or ``E224`` while a new
    account awaits approval). Two first sign-ins racing for one identity or
    address resolve to the same account.

    Override / escape hatch: call it from your own view after
    :func:`verify_id_token`, or replace the view (declare
    ``path("api/auth/social/<provider>/", ...)`` before the include).
    """
    try:
        return _sign_in_once(provider, claims, name)
    except IntegrityError:
        # Another request created the identity or the account first: use it.
        return _sign_in_once(provider, claims, name)


def mark_used(identity: SocialIdentity) -> None:
    """Experimental. Record a completed sign-in through ``identity`` (``last_used_at``)."""
    identity.last_used_at = timezone.now()
    identity.save(update_fields=["last_used_at", "updated_at"])
