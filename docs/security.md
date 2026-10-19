---
description: How to report a security problem privately, what Karni's security baseline covers, and what it does not yet provide.
---

# Security

**Do not open a public issue for a security problem.** Report it privately
through GitHub's vulnerability reporting
([Security → Report a vulnerability](https://github.com/cbsshekhawat18-lab/karni/security/advisories/new))
or by email to the maintainer with "SECURITY" in the subject; the address is
in the repository's
[SECURITY.md](https://github.com/cbsshekhawat18-lab/karni/blob/main/SECURITY.md),
together with the disclosure timeline (acknowledged within 3 working days,
assessed within 10, a fix as soon as practical, an advisory with the fix).

Security fixes go into the latest minor release of the 0.x line; upgrade with
`karni upgrade`. What counts as a Karni vulnerability — access enforcement,
soft delete and scopes, authentication, module webhooks, insecure scaffold
defaults, `karni` commands writing more than they say — is listed there too.

## What Karni does by default

The baseline a project gets from `karni_settings()` and the scaffold, with
nothing to remember. Each line names the setting or check that owns it.

**Rows and fields.** Every `BaseViewSet` has an `access` declaration (a
missing one fails `karni check` and denies every request); the declaration
is the request gate *and* the row filter, so a row outside the scope answers
404, never 403. Relation fields and `?expand=` follow the target's read
scope. Roles are data (`KARNI_ROLES`), checks are cached per request, and
`assert_isolated` proves the isolation for every resource. See
[access control](api.md#access-control) and [roles](accounts.md#roles-as-data).

**Authentication.** Email login with Django's password validators;
short-lived JWT access tokens (15 minutes) with refresh rotation and
blacklisting on logout and password reset, or cookie sessions with the CSRF
bootstrap; one-time tokens stored hashed, single-use, per purpose, with
TTLs; an email-verification gate; optional TOTP 2FA and social login. See
[accounts](accounts.md).

**Abuse.** Per-IP throttles on every auth endpoint plus a per-account
throttle on login (`KARNI_AUTH_THROTTLE_RATES`); `NUM_PROXIES` set for the
shipped Caddy; the password-reset endpoint never reveals whether an address
exists; a registration honeypot (`KARNI_ACCOUNTS_HONEYPOT_FIELD`); and
`karni.W501` warns when the throttle counters would live in a per-process
cache in production.

**Observability.** Every auth outcome is a structlog event on
`karni.accounts` with a user id or an address fingerprint, never an address
— see [bots and security events](accounts.md#bots-and-security-events).
`AuditedModel` records who created and last changed a row; field-level
change history is on the roadmap (ADR 0002).

**Transport and headers.** The production profile sets HSTS (one year,
subdomains, preload), `SECURE_SSL_REDIRECT` behind the proxy's
`X-Forwarded-Proto`, secure and HttpOnly cookies, `nosniff`, a `same-origin`
referrer policy and `X-Frame-Options: DENY`; CORS is closed unless
`CORS_ALLOWED_ORIGINS` lists an origin. Startup validation refuses a missing
`SECRET_KEY` or empty `ALLOWED_HOSTS` with `DEBUG` off.

**Admin.** Mounted at `KARNI_ADMIN_PATH` (move it off `/admin/`). Django's
model permissions decide which screens a staff user may open; the roles'
grants decide which rows those screens show and accept (row scope, ADR 0002
P2): a staff user with permissions but no grant sees nothing, and an admin
that opts out needs a reason that `karni check` lists. No logo unless
`KARNI_ADMIN_LOGO` says so.

**Modules.** `karni-payments` verifies every webhook signature before it
touches a payment and treats replays as no-ops.

**Supply chain.** Dependabot (weekly, grouped), `pip-audit` and `npm audit`
per package, and gitleaks over the whole history run in CI
(`.github/workflows/security.yml`); releases publish through trusted
publishing with attestations, no stored tokens. The scaffold's
`.env.example` holds placeholders only.

What it does **not** do yet: field-level visibility and change history,
per-field encryption (deliberately out of scope), a content security policy
header (set one at the proxy), and upload content validation beyond Django's
`ImageField` — validate uploads in the model's `clean()` until that lands.
