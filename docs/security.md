---
description: How to report a security problem privately, what Karni's security baseline covers, and what it does not yet provide.
---

# Security

**Do not open a public issue for a security problem.** Report it privately
through GitHub's vulnerability reporting
([Security → Report a vulnerability](https://github.com/cbsshekhawat18-lab/karni/security/advisories/new))
or by email to the maintainer with "SECURITY" in the subject. The address is
in the repository's
[SECURITY.md](https://github.com/cbsshekhawat18-lab/karni/blob/main/SECURITY.md),
together with the disclosure timeline (acknowledged within 3 working days,
assessed within 10, a fix as soon as practical, an advisory with the fix).

Security fixes go into the latest minor release of the 0.x line. Upgrade with
`karni upgrade`. SECURITY.md also lists what counts as a Karni vulnerability:
access enforcement, soft delete and scopes, authentication, module webhooks,
insecure scaffold defaults, and `karni` commands writing more than they say.

## What Karni does by default

This is the baseline a project gets from `karni_settings()` and the scaffold,
with nothing to remember. Each line names the setting or check that owns it.

**Rows and fields.** Every `BaseViewSet` has an `access` declaration. A
missing one fails `karni check` and denies every request. The declaration
is the request gate *and* the row filter, so a row outside the scope answers
404, never 403. Relation fields and `?expand=` follow the target's read
scope on every response, writes and exports included. Roles are data
(`KARNI_ROLES`) and checks are cached per request. `assert_isolated` proves the
isolation for every resource, and `assert_row_hidden` proves one row stays
hidden from one client on every surface (`assert_admin_row_hidden` in the
admin). See
[access control](api.md#access-control) and [roles](accounts.md#roles-as-data).

**Authentication.** Email login uses Django's password validators. Access
tokens are short-lived JWTs (15 minutes) with refresh rotation and
blacklisting on logout and password reset. Cookie sessions with the CSRF
bootstrap are the alternative. One-time tokens are stored hashed, single-use,
per purpose, with TTLs. There is an email-verification gate, plus optional
TOTP 2FA and social login. See [accounts](accounts.md).

**Abuse.** Every auth endpoint has per-IP throttles, and login has a
per-account throttle as well (`KARNI_AUTH_THROTTLE_RATES`). `NUM_PROXIES` is
set for the shipped Caddy (`KARNI_NUM_PROXIES`, default 1). Set it to `0`
whenever Django is exposed without a proxy that rewrites `X-Forwarded-For`,
or a spoofed header defeats the per-IP throttles. The password-reset endpoint
never reveals whether an address exists. Registration has a honeypot
(`KARNI_ACCOUNTS_HONEYPOT_FIELD`), and `karni.W501` warns when the throttle
counters would live in a per-process cache in production. Registration is
open by default. While it is, `karni.W102` warns for every viewset that lets
any signed-in user change and delete every row, and
`KARNI_ACCOUNTS_REGISTRATION = False` closes it
([closing registration](accounts.md#closing-registration)).

**Observability.** Every auth outcome is a structlog event on
`karni.accounts` with a user id or an address fingerprint, never an address.
See [bots and security events](accounts.md#bots-and-security-events).
`AuditedModel` records who created and last changed a row. Models with
`class Karni: audit = True` also keep a field-level change history
([change history](change-history.md)). Every request has an id
(`X-Request-ID`) that its logs, tasks, email and history entries carry. With
`DEBUG` off, a client's `X-Request-ID` is never trusted unless
`KARNI_REQUEST_ID_TRUST_HEADER` says the proxy overwrites it (and
`NUM_PROXIES` is not 0). The development capture under `.karni/` runs only
with `DEBUG` on and redacts credentials, secret-named fields and known
secret values ([capture](debugging/capture.md)).

**Transport and headers.** The production profile sets HSTS (one year,
subdomains, preload), `SECURE_SSL_REDIRECT` behind the proxy's
`X-Forwarded-Proto`, secure and HttpOnly cookies, `nosniff`, a `same-origin`
referrer policy and `X-Frame-Options: DENY`. CORS is closed unless
`CORS_ALLOWED_ORIGINS` lists an origin. With `DEBUG` off, startup validation
refuses a missing `SECRET_KEY` or an empty `ALLOWED_HOSTS`.

**Admin.** It is mounted at `KARNI_ADMIN_PATH` (move it off `/admin/`).
Django's model permissions decide which screens a staff user may open. The
roles' grants decide which rows those screens show and accept (row scope, ADR
0002 P2). A staff user with permissions but no grant sees nothing, and an
admin that opts out needs a reason that `karni check` lists. There is no logo
unless `KARNI_ADMIN_LOGO` says so.

**Welcome page.** `/` on first boot (`karni.welcome`) is served only while
`DEBUG` is on and only until the project defines its own root route. With
`DEBUG` off the route is not mounted, the view answers 404, and system check
`karni.E505` fails the boot if it is reachable anyway. It shows the presence
or absence of configuration (a database, Redis, a worker), never a value.

**Modules.** `karni-payments` verifies every webhook signature before it
touches a payment and treats replays as no-ops.

**Supply chain.** Dependabot (weekly, grouped), `pip-audit` and `npm audit`
per package, and gitleaks over the whole history run in CI
(`.github/workflows/security.yml`). Releases publish through trusted
publishing with attestations, with no stored tokens. The scaffold's
`.env.example` holds placeholders only.

What it does **not** do yet: field-level visibility and change history,
per-field encryption (deliberately out of scope), a content security policy
header (set one at the proxy), and upload content validation beyond Django's
`ImageField`. Until that lands, validate uploads in the model's `clean()`.
