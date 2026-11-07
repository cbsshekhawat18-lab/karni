"""The web server's files, published by the release step: ``manage.py karni_publish_web``.

In the production stack Caddy serves files itself (the built staff app, static
files, media) and proxies everything else to Django. Its configuration comes
from the one production image, through the shared volume, so a release or a
rollback changes the Caddyfile, the staff app and the headers together:

* ``<root>/Caddyfile``: the project's ``Caddyfile``, copied.
* ``<root>/karni-headers.caddy``: a Caddy snippet, ``(karni_headers)``, with the
  security headers Django sends (the Content-Security-Policy and
  Permissions-Policy of :mod:`karni.security.headers`, HSTS, nosniff,
  X-Frame-Options, Referrer-Policy, Cross-Origin-Opener-Policy), computed from
  this project's settings. The Caddyfile imports it for the files Caddy serves,
  so the staff app gets the same policy as a Django page.
* ``<root>/app/``: the built staff app (``frontend/dist``). Files from earlier
  builds stay for ``keep_days`` after their last build, so a browser still
  holding the previous ``index.html`` loads its scripts during an update.
  ``index.html`` is written last.

Override / escape hatch: every path is an argument (and a command option),
and :func:`caddy_headers` is a plain function a project may call to write its
own snippet. A project without a staff app or a Caddyfile skips that part.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["HEADERS_FILE", "Published", "caddy_headers", "publish", "security_headers"]

HEADERS_FILE = "karni-headers.caddy"
APP_DIR = "app"
SEEN_FILE = ".karni-app-files.json"
SNIPPET = "karni_headers"


def security_headers() -> dict[str, str]:
    """The headers Django adds to a page, from the current settings (needs Django set up)."""
    from django.conf import settings

    from karni.security.headers import (
        csp_directives,
        csp_header_name,
        permissions_policy,
        render_csp,
    )

    headers: dict[str, str] = {}
    directives = csp_directives()
    if directives is not None:
        headers[csp_header_name()] = render_csp(directives)
    policy = permissions_policy()
    if policy:
        headers["Permissions-Policy"] = policy
    seconds = int(getattr(settings, "SECURE_HSTS_SECONDS", 0) or 0)
    if seconds:
        hsts = f"max-age={seconds}"
        if getattr(settings, "SECURE_HSTS_INCLUDE_SUBDOMAINS", False):
            hsts += "; includeSubDomains"
        if getattr(settings, "SECURE_HSTS_PRELOAD", False):
            hsts += "; preload"
        headers["Strict-Transport-Security"] = hsts
    if getattr(settings, "SECURE_CONTENT_TYPE_NOSNIFF", True):
        headers["X-Content-Type-Options"] = "nosniff"
    middleware = list(getattr(settings, "MIDDLEWARE", []) or [])
    if "django.middleware.clickjacking.XFrameOptionsMiddleware" in middleware:
        headers["X-Frame-Options"] = str(getattr(settings, "X_FRAME_OPTIONS", "DENY"))
    referrer = getattr(settings, "SECURE_REFERRER_POLICY", "same-origin")
    if referrer:
        if not isinstance(referrer, str):
            referrer = ",".join(str(value) for value in referrer)
        headers["Referrer-Policy"] = referrer
    opener = getattr(settings, "SECURE_CROSS_ORIGIN_OPENER_POLICY", "same-origin")
    if opener:
        headers["Cross-Origin-Opener-Policy"] = str(opener)
    return headers


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def caddy_headers(headers: dict[str, str]) -> str:
    """A Caddyfile snippet, ``(karni_headers)``, that sets ``headers`` on a response."""
    lines = [
        "# Written by `manage.py karni_publish_web` from this project's settings: the",
        "# security headers Django sends, for the files Caddy serves itself. It is",
        "# rewritten on every release, so change the settings (KARNI_CSP, ...), not this file.",
        f"({SNIPPET}) {{",
        "\theader {",
        *(f"\t\t{name} {_quoted(value)}" for name, value in headers.items()),
        "\t}",
        "}",
    ]
    return "\n".join(lines) + "\n"


@dataclass
class Published:
    """What :func:`publish` wrote, and what it skipped (for the command's output)."""

    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _copy_app(source: Path, target: Path, keep_days: float, now: float) -> int:
    files = sorted(path for path in source.rglob("*") if path.is_file())
    # Scripts and styles first, the HTML that points at them last.
    files.sort(key=lambda path: path.suffix == ".html")
    target.mkdir(parents=True, exist_ok=True)
    seen_path = target / SEEN_FILE
    try:
        seen: dict[str, float] = json.loads(seen_path.read_text())
    except (OSError, ValueError):
        seen = {}
    current = set()
    for path in files:
        rel = path.relative_to(source).as_posix()
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged = destination.with_name(f".{destination.name}.new")
        shutil.copy2(path, staged)
        staged.replace(destination)
        seen[rel] = now
        current.add(rel)
    for rel, last in list(seen.items()):
        if rel not in current and now - last > keep_days * 86400:
            (target / rel).unlink(missing_ok=True)
            del seen[rel]
    seen_path.write_text(json.dumps(seen, indent=0, sort_keys=True) + "\n")
    return len(files)


def publish(
    root: Path,
    *,
    app: Path | None,
    caddyfile: Path | None,
    headers: dict[str, str] | None = None,
    keep_days: float = 7.0,
    now: float | None = None,
) -> Published:
    """Write the Caddyfile, the headers snippet and the staff app under ``root``."""
    result = Published()
    root.mkdir(parents=True, exist_ok=True)
    snippet = root / HEADERS_FILE
    snippet.write_text(caddy_headers(security_headers() if headers is None else headers))
    result.written.append(str(snippet))
    if caddyfile is not None and caddyfile.is_file():
        shutil.copyfile(caddyfile, root / "Caddyfile")
        result.written.append(str(root / "Caddyfile"))
    else:
        result.skipped.append(f"no Caddyfile at {caddyfile}")
    if app is not None and (app / "index.html").is_file():
        count = _copy_app(app, root / APP_DIR, keep_days, time.time() if now is None else now)
        result.written.append(f"{root / APP_DIR} ({count} files from {app})")
    else:
        result.skipped.append(f"no built staff app at {app} (no index.html)")
    return result


def describe(paths: Iterable[str]) -> str:
    return "\n".join(f"  {path}" for path in paths)
