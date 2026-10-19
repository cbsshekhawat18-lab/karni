# karni-impersonation

"Log in as user" for support, done safely, for
[Karni](https://github.com/cbsshekhawat18-lab/karni) projects. A support
person with the explicit permission acts as a customer to see what they
see — with a banner on every page, a session record, both identities in the
audit trail, a time limit and a hard block on dangerous actions.

## Install

```sh
pip install karni-impersonation
karni add impersonation
karni migrate
```

Then wire it twice (the module cannot do this for you; `karni check` fails
with `IMP007` until both are in place):

```python
# config/settings.py — right after AuthenticationMiddleware
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware") + 1,
    "karni_impersonation.middleware.ImpersonationMiddleware",
)

# config/urls.py — the banner's exit
path("impersonation/", include("karni_impersonation.urls")),
```

Grant the permission to the role that does support:

```python
KARNI_ROLES = {
    ...
    "support": {"grants": {"karni_impersonation.impersonationsession:impersonate": "all", ...}},
}
```

Keep the Celery worker and beat running: the target's notification is a
task and an hourly sweep closes abandoned sessions.

## Threat model

**What it allows.** A user holding `karni_impersonation.impersonationsession:impersonate`
(the *actor*) acts as another user (the *target*) for at most
`KARNI_IMPERSONATION_MAX_MINUTES` (60): every request is evaluated as the
target — their roles, their row scope, their field visibility — through the
admin (session auth) or the API (session or JWT). The actor sees what the
target sees and may change what the target may change, minus the blocked
list.

**What it blocks.**

- *Starting without the permission* (`IMP001`). Staff and superuser status
  never imply it; only a role with the grant (superusers hold every grant by
  Karni's convention — treat superuser accounts accordingly).
- *Privilege escalation* (`IMP002`). The target may not be a superuser or
  staff unless the actor is, may not hold any role grant at a scope the
  actor does not hold (`all` covers all), and may not hold any Django
  permission the actor lacks. Checked in `services.start`, before anything
  is written, whoever calls it.
- *Impersonating yourself, an inactive account, or starting a second
  session* (`IMP004`); *starting without a reason* when
  `KARNI_IMPERSONATION_REQUIRE_REASON` is on (`IMP003`, the default).
- *Dangerous actions during the session* (`IMP006`), whatever the target
  may do: `KARNI_IMPERSONATION_BLOCKED` lists viewset and admin action
  names, `app.model` labels, `app.model:action` permission keys and URL
  paths; by default deleting (`destroy`, `*:delete`, `delete_selected`, …),
  exporting and importing, everything in `karni_payments`, and the
  credential paths (`/api/auth/password/*`, `/api/auth/email/*`,
  `/api/auth/2fa/*`, `/api/auth/register/`). Enforced through Karni's veto
  registry at the API gate and the admin's permissions and action list, and
  by the middleware for paths — not in a UI.
- *Outliving the limit.* In session mode the middleware ends the session
  on the first request past `expires_at`; in JWT mode the tokens issued for
  the session expire with it and the middleware refuses a token whose
  session has ended. The hourly sweep closes what no request touched.
- *Silent use.* The target is emailed on start (`KARNI_IMPERSONATION_NOTIFY_TARGET`,
  default on).

**What it logs.** An `ImpersonationSession` row per session: actor, target,
reason, start, limit, end and why it ended (stopped, expired, logout,
swept), IP and user agent. The row is itself audited (`karni.audit`). At
start the module opens a `karni.audit` `ChangeBatch` of kind
`impersonation` whose actor is the impersonator; every request of the
session runs inside it, so every change made while impersonating has
`actor` = the target (the row's history) **and** `batch` → the
impersonator — both identities, on every write.

**How to tell after the fact whether it was used.**

- Admin → Karni impersonation → Impersonation sessions (read-only; nobody
  can delete a record through the admin or the API).
- `ImpersonationSession.objects.filter(target=user)` — who acted as this
  user, when, why.
- `ChangeLog.objects.filter(batch__kind="impersonation")` — every change
  made under impersonation; `.filter(batch__actor=support_user)` — by whom;
  a row's history shows `batch` on each entry.
- `ImpersonationSession.objects.filter(ended_at__isnull=True)` — sessions
  open right now.

**What it does not do.** It does not hide the actor: the banner names both
people on every page and `GET /api/impersonation-sessions/current/` says so
to a SPA. It does not grant the actor anything the target lacks, and it
does not grant the target anything. It cannot block an action a project
exposes outside Karni's gates (a plain Django view that writes); list its
path in `KARNI_IMPERSONATION_BLOCKED`.

## Where it shows

| Surface | What |
| --- | --- |
| Admin → user change page → **Impersonate** (django-unfold) / Impersonation sessions → **Impersonate a user** | the reason form, then the site as the target with the banner |
| the banner (every HTML page, session mode) | both identities, minutes left, **Stop impersonating** |
| `POST /api/impersonation-sessions/start/` `{"user": <id or email>, "reason"}` | the session; JWT mode adds `access`/`refresh` tokens for the target, bounded by the limit |
| `POST /api/impersonation-sessions/stop/` | ends it; JWT mode returns fresh tokens for the actor |
| `GET /api/impersonation-sessions/current/` | the session this request belongs to, or `null` |
| `GET /api/impersonation-sessions/` | the log (needs the `view` grant; an actor sees their own) |
| `@karni/impersonation-ui` | `<ImpersonationBanner/>` and `useImpersonation()` for SPAs |

## Settings

| Setting | Env var | Default | Meaning |
| --- | --- | --- | --- |
| `KARNI_IMPERSONATION_MAX_MINUTES` | same | `60` | hard limit on a session |
| `KARNI_IMPERSONATION_BLOCKED` | same (comma list) | deletes, exports/imports, `karni_payments.*`, credential paths | what is blocked while impersonating |
| `KARNI_IMPERSONATION_REQUIRE_REASON` | same | `True` | a reason is required to start |
| `KARNI_IMPERSONATION_NOTIFY_TARGET` | same | `True` | email the impersonated user on start |
| `KARNI_IMPERSONATION_FROM_EMAIL` | same | `""` | sender; `""` uses `DEFAULT_FROM_EMAIL` |
| `KARNI_IMPERSONATION_BANNER` | same | `True` | inject the banner into HTML pages |
| `KARNI_IMPERSONATION_LANDING` | same | `/` | where the admin's start page sends the impersonator |

## Escape hatches

- Every setting above; `KARNI_IMPERSONATION_BLOCKED` narrows or widens
  what is blocked per project (never empty in production).
- `services.start`, `stop`, `can_impersonate`, `privilege_gap`,
  `is_blocked`, `sweep` are plain functions for your own views and tasks;
  `karni_impersonation.middleware.current_session(request)` tells a view
  whether it runs impersonated.
- The banner template `karni_impersonation/banner.html` and the start page
  `karni_impersonation/start.html` can be overridden in the project's
  templates.
- `services.find_user` resolves the start form's input; subclass the
  viewset (`auto_register = False`) to change the API.
- This module ships an explicit `admin.py` (the session log and the start
  page) and, when the user admin is a django-unfold one, adds an
  **Impersonate** button to it.
