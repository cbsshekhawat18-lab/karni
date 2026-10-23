"""Security headers on every response: Content-Security-Policy and Permissions-Policy.

:class:`SecurityHeadersMiddleware` (in ``MIDDLEWARE`` right after Django's
``SecurityMiddleware``) adds both headers to every response Django sends.
Django's own ``SecurityMiddleware`` already sends ``Referrer-Policy``
(``SECURE_REFERRER_POLICY``, ``same-origin``), ``X-Content-Type-Options``
and ``Cross-Origin-Opener-Policy``, so this middleware does not repeat them.

The Content-Security-Policy is :data:`DEFAULT_CSP` with
``KARNI_CSP`` merged in. With ``DEBUG`` on it is sent as
``Content-Security-Policy-Report-Only``: the browser reports what the policy
would block in its console and blocks nothing. ``KARNI_CSP_REPORT_ONLY``
overrides that choice either way.

Some pages need more than the default, and get it for that page only:

* The admin gets ``script-src 'unsafe-eval'``. django-unfold runs Alpine.js,
  which evaluates its ``x-data`` expressions with ``new Function``.
* drf-spectacular's Swagger UI and Redoc pages may load their scripts and
  styles from the CDN in ``SPECTACULAR_SETTINGS`` and run an inline start-up
  script. ``SpectacularSwaggerSplitView`` has none.
* django-allauth's provider pages may submit forms that redirect to the provider.
* Any view adds sources with :func:`csp_extend`, or sends no policy with
  :func:`csp_exempt`.

A response that already carries the header (set by the view) is left alone.

Override / escape hatch: ``KARNI_CSP`` (merged directives, ``None`` turns
the header off), ``KARNI_CSP_REPORT_ONLY``, ``KARNI_PERMISSIONS_POLICY``
(``None`` turns it off), the two view decorators, or a subclass of the
middleware overriding :meth:`SecurityHeadersMiddleware.csp_directives` or
:meth:`SecurityHeadersMiddleware.page_directives`, listed in ``MIDDLEWARE``
in place of this one.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable, Iterable, Mapping
from functools import wraps
from typing import Any, Final
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpRequest, HttpResponseBase

__all__ = [
    "DEFAULT_CSP",
    "DEFAULT_PERMISSIONS_POLICY",
    "THEME_SCRIPT",
    "SecurityHeadersMiddleware",
    "csp_directives",
    "csp_exempt",
    "csp_extend",
    "csp_header_name",
    "permissions_policy",
    "render_csp",
    "script_hash",
]

#: @karni/ui's pre-paint theme script (``KARNI_THEME_SCRIPT`` in
#: ``src/theme/script.ts``), which ``karniTheme()`` inlines into index.html.
#: A test keeps this copy identical to the TypeScript one.
THEME_SCRIPT: Final = (
    '(function(){try{var t=localStorage.getItem("karni-theme");var d=t==="dark"||'
    '((t===null||t==="system")&&matchMedia("(prefers-color-scheme: dark)").matches);'
    'document.documentElement.classList.toggle("dark",d);'
    'document.documentElement.style.colorScheme=d?"dark":"light"}catch(e){}})();'
)


def script_hash(source: str) -> str:
    """The CSP source that allows exactly this inline script: ``'sha256-<base64>'``."""
    digest = hashlib.sha256(source.encode("utf-8")).digest()
    return f"'sha256-{base64.b64encode(digest).decode('ascii')}'"


#: The policy every response gets, before ``KARNI_CSP``. Each directive, and why:
#:
#: * ``default-src 'self'``: anything not listed below loads only from the site itself.
#: * ``script-src 'self'`` plus the hash of @karni/ui's theme script: scripts come from
#:   the site's own files. No inline script runs except that one, so an injected
#:   ``<script>`` or ``onclick=`` does nothing.
#: * ``style-src 'self' 'unsafe-inline'``: stylesheets from the site, and inline styles.
#:   The admin, the browsable API, Swagger UI and Radix (in @karni/ui) all set inline
#:   styles, and a style cannot run code.
#: * ``img-src 'self' data: blob:``: images from the site, ``data:`` icons in CSS, and
#:   ``blob:`` previews of a file chosen for upload. Media on S3 is added for you.
#: * ``font-src 'self' data:``: fonts from the site (unfold ships its own) and inline fonts.
#: * ``connect-src 'self'``: fetch and XHR go to the site's own API.
#: * ``object-src 'none'``: no plugins (``<object>``, ``<embed>``).
#: * ``base-uri 'self'``: an injected ``<base>`` cannot redirect relative URLs.
#: * ``form-action 'self'``: forms submit to the site only.
#: * ``frame-ancestors 'none'``: no other site may frame these pages (clickjacking).
#:   It follows ``X_FRAME_OPTIONS``: ``SAMEORIGIN`` makes it ``'self'``.
DEFAULT_CSP: Final[Mapping[str, tuple[str, ...]]] = {
    "default-src": ("'self'",),
    "script-src": ("'self'", script_hash(THEME_SCRIPT)),
    "style-src": ("'self'", "'unsafe-inline'"),
    "img-src": ("'self'", "data:", "blob:"),
    "font-src": ("'self'", "data:"),
    "connect-src": ("'self'",),
    "object-src": ("'none'",),
    "base-uri": ("'self'",),
    "form-action": ("'self'",),
    "frame-ancestors": ("'none'",),
}

#: Powerful browser features no Karni page uses, switched off for every page and
#: anything it embeds. ``KARNI_PERMISSIONS_POLICY`` allows one back, e.g.
#: ``{"geolocation": ["self"]}``.
DEFAULT_PERMISSIONS_POLICY: Final[Mapping[str, tuple[str, ...]]] = {
    "accelerometer": (),
    "camera": (),
    "geolocation": (),
    "gyroscope": (),
    "magnetometer": (),
    "microphone": (),
    "payment": (),
    "usb": (),
}

#: django-unfold's admin runs Alpine.js, which evaluates ``x-data``/``x-init``
#: expressions with ``new Function``. Without this the admin's menus, tabs and theme
#: switch stop working.
ADMIN_DIRECTIVES: Final[Mapping[str, tuple[str, ...]]] = {"script-src": ("'unsafe-eval'",)}

#: django-allauth's provider pages submit a form that redirects to the provider
#: (accounts.google.com, github.com, ...), and browsers apply ``form-action`` to it.
SOCIAL_DIRECTIVES: Final[Mapping[str, tuple[str, ...]]] = {"form-action": ("https:",)}

_HEADER = "Content-Security-Policy"
_REPORT_ONLY_HEADER = "Content-Security-Policy-Report-Only"
_KEYWORDS: Final = frozenset({"self", "*", "src"})

Directives = dict[str, list[str]]


def _sources(value: Any) -> list[str]:
    """``"a b"``, ``["a", "b"]`` or ``("a", "b")`` as a list of sources."""
    if isinstance(value, str):
        return value.split()
    return [str(item) for item in value]


_PINNED_PREFIXES: Final = ("'sha256-", "'sha384-", "'sha512-", "'nonce-")


def merge_directives(base: Mapping[str, Iterable[str]], extra: Mapping[str, Any]) -> Directives:
    """``base`` with ``extra`` merged in: sources are added, ``None`` removes a directive.

    Adding to a directive that is only ``'none'`` replaces the ``'none'``.
    Adding ``'unsafe-inline'`` drops the directive's hashes and nonces:
    browsers ignore ``'unsafe-inline'`` next to either, so keeping them would
    block the inline code the addition is meant to allow. Sources are not
    repeated.
    """
    merged: Directives = {name: list(sources) for name, sources in base.items()}
    for name, value in extra.items():
        if value is None:
            merged.pop(name, None)
            continue
        added = _sources(value)
        current = merged.get(name, [])
        if current == ["'none'"]:
            current = []
        if "'unsafe-inline'" in added:
            current = [source for source in current if not source.startswith(_PINNED_PREFIXES)]
        for source in added:
            if source not in current:
                current.append(source)
        merged[name] = current or ["'none'"]
    return merged


def storage_origins() -> list[str]:
    """Where uploaded media comes from when it is not the site (``KARNI_STORAGE = "s3"``)."""
    if getattr(settings, "KARNI_STORAGE", "local") != "s3":
        return []
    protocol = str(getattr(settings, "AWS_S3_URL_PROTOCOL", "https:") or "https:").rstrip(":")
    custom = str(getattr(settings, "AWS_S3_CUSTOM_DOMAIN", "") or "")
    if custom:
        return [f"{protocol}://{custom.split('/')[0]}"]
    bucket = str(getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or "")
    endpoint = urlsplit(str(getattr(settings, "AWS_S3_ENDPOINT_URL", "") or ""))
    if endpoint.scheme and endpoint.netloc:
        origins = [f"{endpoint.scheme}://{endpoint.netloc}"]
        if bucket:
            origins.append(f"{endpoint.scheme}://{bucket}.{endpoint.netloc}")
        return origins
    if not bucket:
        return []
    origins = [f"https://{bucket}.s3.amazonaws.com"]
    region = str(getattr(settings, "AWS_S3_REGION_NAME", "") or "")
    if region:
        origins.append(f"https://{bucket}.s3.{region}.amazonaws.com")
    return origins


def csp_directives() -> Directives | None:
    """The site-wide policy: :data:`DEFAULT_CSP`, media origins, then ``KARNI_CSP``.

    ``None`` when ``KARNI_CSP`` is ``None`` (no Content-Security-Policy header).
    """
    configured = getattr(settings, "KARNI_CSP", {})
    if configured is None:
        return None
    directives = merge_directives(DEFAULT_CSP, {})
    if str(getattr(settings, "X_FRAME_OPTIONS", "DENY")).upper() == "SAMEORIGIN":
        directives["frame-ancestors"] = ["'self'"]
    media = storage_origins()
    if media:
        directives = merge_directives(
            directives, {"img-src": media, "media-src": ["'self'", *media]}
        )
    return merge_directives(directives, configured or {})


def render_csp(directives: Mapping[str, Iterable[str]]) -> str:
    """The header value: ``"default-src 'self'; script-src 'self' ..."``."""
    return "; ".join(
        " ".join([name, *sources]) if sources else name for name, sources in directives.items()
    )


def csp_header_name() -> str:
    """The header name: report-only per ``KARNI_CSP_REPORT_ONLY``, else while ``DEBUG`` is on."""
    report_only = getattr(settings, "KARNI_CSP_REPORT_ONLY", None)
    if report_only is None:
        report_only = bool(getattr(settings, "DEBUG", False))
    return _REPORT_ONLY_HEADER if report_only else _HEADER


def _allowlist(entry: str) -> str:
    if entry in _KEYWORDS or entry.startswith('"'):
        return entry
    return f'"{entry}"'


def permissions_policy() -> str | None:
    """The ``Permissions-Policy`` value, ``None`` when ``KARNI_PERMISSIONS_POLICY`` is ``None``."""
    configured = getattr(settings, "KARNI_PERMISSIONS_POLICY", {})
    if configured is None:
        return None
    features: dict[str, list[str]] = {
        name: list(allow) for name, allow in DEFAULT_PERMISSIONS_POLICY.items()
    }
    for name, allow in (configured or {}).items():
        if allow is None:
            features.pop(name, None)
        else:
            features[name] = _sources(allow)
    return ", ".join(
        f"{name}=({' '.join(_allowlist(entry) for entry in allow)})"
        for name, allow in features.items()
    )


def _origin(url: str) -> str | None:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else None


def _docs_directives(view_class: type[Any]) -> Directives | None:
    """What drf-spectacular's Swagger UI and Redoc pages load, or ``None`` for another view."""
    try:
        from drf_spectacular.settings import spectacular_settings
        from drf_spectacular.views import (
            SpectacularRedocView,
            SpectacularSwaggerSplitView,
            SpectacularSwaggerView,
        )
    except ImportError:  # pragma: no cover - drf-spectacular is a karni dependency
        return None
    if issubclass(view_class, SpectacularRedocView):
        cdn = [o for o in [_origin(str(spectacular_settings.REDOC_DIST))] if o]
        return {
            # The page starts Redoc with an inline script.
            "script-src": [*cdn, "'unsafe-inline'"],
            "style-src": ["https://fonts.googleapis.com"],
            "font-src": ["https://fonts.gstatic.com"],
            # Its footer shows Redocly's logo from their CDN.
            "img-src": [*cdn, "https://cdn.redoc.ly"],
            # Redoc runs its search index in a worker it builds from a blob.
            "worker-src": ["'self'", "blob:"],
        }
    if issubclass(view_class, SpectacularSwaggerView):
        cdn = [
            origin
            for origin in {
                _origin(str(spectacular_settings.SWAGGER_UI_DIST)),
                _origin(str(spectacular_settings.SWAGGER_UI_FAVICON_HREF or "")),
            }
            if origin
        ]
        inline = [] if issubclass(view_class, SpectacularSwaggerSplitView) else ["'unsafe-inline'"]
        return {
            "script-src": [*sorted(cdn), *inline],
            "style-src": sorted(cdn),
            "img-src": sorted(cdn),
        }
    return None


class SecurityHeadersMiddleware:
    """Adds ``Content-Security-Policy`` and ``Permissions-Policy`` to every response.

    See the module docstring for the policy, the per-page additions and the
    settings. Override / escape hatch: subclass it, override
    :meth:`csp_directives` (the site-wide policy) or :meth:`page_directives`
    (the additions for one request), and list the subclass in ``MIDDLEWARE``
    in its place.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        response = self.get_response(request)
        self.add_headers(request, response)
        return response

    def csp_directives(self, request: HttpRequest) -> Directives | None:
        """The site-wide policy for this request (:func:`csp_directives`)."""
        return csp_directives()

    def page_directives(self, request: HttpRequest, response: HttpResponseBase) -> Directives:
        """Sources this page adds: the admin, the API docs, allauth, :func:`csp_extend`."""
        extra: Directives = {}
        match = getattr(request, "resolver_match", None)
        if match is not None:
            if "admin" in (match.app_names or ()):
                extra = merge_directives(extra, ADMIN_DIRECTIVES)
            func = match.func
            view_class = getattr(func, "view_class", None) or getattr(func, "cls", None)
            if isinstance(view_class, type):
                docs = _docs_directives(view_class)
                if docs:
                    extra = merge_directives(extra, docs)
            module = getattr(view_class or func, "__module__", "") or ""
            if module.startswith("allauth."):
                extra = merge_directives(extra, SOCIAL_DIRECTIVES)
        declared = getattr(response, "karni_csp_extend", None)
        if declared:
            extra = merge_directives(extra, declared)
        return extra

    def add_headers(self, request: HttpRequest, response: HttpResponseBase) -> None:
        """Set both headers unless the response has them or is exempt."""
        if not getattr(response, "karni_csp_exempt", False) and not (
            response.has_header(_HEADER) or response.has_header(_REPORT_ONLY_HEADER)
        ):
            directives = self.csp_directives(request)
            if directives is not None:
                extra = self.page_directives(request, response)
                policy = merge_directives(directives, extra) if extra else directives
                response.headers[csp_header_name()] = render_csp(policy)
        if not response.has_header("Permissions-Policy"):
            value = permissions_policy()
            if value:
                response.headers["Permissions-Policy"] = value


ViewFunc = Callable[..., HttpResponseBase]


def csp_extend(directives: Mapping[str, Any]) -> Callable[[ViewFunc], ViewFunc]:
    """``@csp_extend({"img-src": ["https://tiles.example.com"]})``: sources one view adds.

    Merged like ``KARNI_CSP`` (sources added, ``None`` removes a directive),
    for that view's responses only. On a class-based view, wrap ``dispatch``
    with ``method_decorator``.
    """

    def decorator(view: ViewFunc) -> ViewFunc:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> HttpResponseBase:
            response = view(*args, **kwargs)
            current = getattr(response, "karni_csp_extend", None) or {}
            response.karni_csp_extend = merge_directives(  # type: ignore[attr-defined]
                {name: _sources(value) for name, value in current.items() if value is not None},
                directives,
            )
            return response

        return wrapped

    return decorator


def csp_exempt(view: ViewFunc) -> ViewFunc:
    """``@csp_exempt``: this view's responses get no Content-Security-Policy from Karni."""

    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> HttpResponseBase:
        response = view(*args, **kwargs)
        response.karni_csp_exempt = True  # type: ignore[attr-defined]
        return response

    return wrapped
