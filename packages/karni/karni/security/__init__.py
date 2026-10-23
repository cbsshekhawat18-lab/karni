"""Security that every Karni project gets without asking: response headers and deploy checks.

* :class:`SecurityHeadersMiddleware` adds a Content-Security-Policy
  (report-only while ``DEBUG`` is on) and a Permissions-Policy to every
  response (:mod:`karni.security.headers`). ``karni_settings()`` puts it in
  ``MIDDLEWARE`` right after Django's ``SecurityMiddleware``.
* :mod:`karni.security.checks` holds the deploy checks ``karni.W510`` to
  ``karni.W519`` that ``manage.py check --deploy`` and
  ``karni check --deploy`` run.

Override / escape hatch: the settings ``KARNI_CSP``,
``KARNI_CSP_REPORT_ONLY`` and ``KARNI_PERMISSIONS_POLICY``, the view
decorators :func:`csp_extend` and :func:`csp_exempt`, a subclass of the
middleware, and ``SILENCED_SYSTEM_CHECKS`` for a deploy check.
"""

from __future__ import annotations

from karni.security.headers import (
    DEFAULT_CSP,
    DEFAULT_PERMISSIONS_POLICY,
    SecurityHeadersMiddleware,
    csp_directives,
    csp_exempt,
    csp_extend,
    permissions_policy,
    render_csp,
    script_hash,
)

__all__ = [
    "DEFAULT_CSP",
    "DEFAULT_PERMISSIONS_POLICY",
    "SecurityHeadersMiddleware",
    "csp_directives",
    "csp_exempt",
    "csp_extend",
    "permissions_policy",
    "render_csp",
    "script_hash",
]
