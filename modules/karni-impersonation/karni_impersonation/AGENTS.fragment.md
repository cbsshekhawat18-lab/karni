## Impersonation (karni-impersonation)
- "Log in as user" for support. Wire it twice: MIDDLEWARE gets
  `karni_impersonation.middleware.ImpersonationMiddleware` right after
  AuthenticationMiddleware, and config/urls.py gets
  `path("impersonation/", include("karni_impersonation.urls"))` (`karni check`
  fails without both, IMP007).
- Starting needs the explicit `karni_impersonation.impersonationsession:impersonate`
  grant. Being staff never implies it. A target who holds anything the actor
  lacks is refused (IMP002). Start/stop only through the API
  (`/api/impersonation-sessions/start/`, `stop/`, `current/`) or the admin page.
- While impersonating, `KARNI_IMPERSONATION_BLOCKED` wins over everything
  (deletes, exports, payments, credential paths by default). Never work
  around it. Every write joins the session's audit batch naming both people.
- Settings: KARNI_IMPERSONATION_MAX_MINUTES, _BLOCKED, _REQUIRE_REASON,
  _NOTIFY_TARGET. The target is emailed. The hourly sweep needs Celery beat.
