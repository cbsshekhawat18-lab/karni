"""Settings for karni-approvals' standalone test suite (sqlite, eager Celery).

Names defined before :func:`karni.conf.karni_settings` win; the module's own
``karni.settings`` fragment arrives through the merge. ``tests.testapp`` is
the project under test: an ``Invoice`` guarded on two fields, a ``Contract``
guarded on any change with two approvals from ``finance``, a ``Memo`` that
is never held.
"""

from __future__ import annotations

from karni.conf import karni_settings

SECRET_KEY = "karni-approvals-tests-secret-key-not-for-production"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"
ROOT_URLCONF = "tests.urls"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DEFAULT_FROM_EMAIL = "approvals@example.com"

# The project's roles: a maker (clerk), checkers (finance), a branch-scoped
# checker, and staff (system, everything).
KARNI_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    "clerk": {
        "name": "Clerk",
        "grants": {
            "testapp.invoice:view": "all",
            "testapp.invoice:add": "all",
            "testapp.invoice:change": "all",
            "testapp.invoice:delete": "all",
            "testapp.contract:*": "all",
            "testapp.memo:*": "all",
            "testapp.branch:view": "all",
            "karni_approvals.pendingchange:view": "own",
        },
    },
    "finance": {
        "name": "Finance",
        "grants": {
            "testapp.*:view": "all",
            "karni_approvals.pendingchange:view": "all",
            "karni_approvals.pendingchange:approve": "all",
            "karni_approvals.pendingchange:reject": "all",
        },
    },
    "branch_checker": {
        "name": "Branch checker",
        "grants": {
            "testapp.invoice:view": "related:branch",
            "testapp.branch:view": "all",
            "karni_approvals.pendingchange:view": "all",
            "karni_approvals.pendingchange:approve": "all",
            "karni_approvals.pendingchange:reject": "all",
        },
    },
}

karni_settings(globals(), env_name="dev")

INSTALLED_APPS += ["karni_approvals", "tests.testapp"]  # type: ignore[name-defined]  # noqa: F821
