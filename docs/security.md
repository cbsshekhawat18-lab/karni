---
description: How to report a security problem privately, what Karni does to keep a project safe by default (with the setting and the check for each), the security headers, the deploy checks, and what it does not yet provide.
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

## Secure by default

A project is safe without anyone in it knowing security: an AI agent that
writes only the domain and the pages gets every row below for free. Each row
names what Karni does out of the box, the setting that changes it, and the
check that fails or warns when it is weakened. The `karni.W51x` checks run
with `karni check --deploy` ([deploy checks](#deploy-checks)).

| What | Out of the box | Change it with | Guarded by |
|---|---|---|---|
| Every resource has a gate | a viewset without `access` denies every request | `access = ...` on the viewset | `karni.E101` |
| Public content is not writable by any account | `--access public-read` writes `write=HasRole("staff")` | `--access public-read:<role>` | `karni.W102` |
| Signing up grants no write | registration is open, and a `write` every signed-in user passes is reported | `KARNI_ACCOUNTS_REGISTRATION = False` closes `register/` | `karni.W102` |
| Auth endpoints are rate-limited | per IP, and per account for login | `KARNI_AUTH_THROTTLE_RATES` | `karni.W501` (shared counters) |
| Public forms are rate-limited | a public `create` allows 10 an hour per caller | `KARNI_PUBLIC_CREATE_RATE`, `throttle = Throttle(create=...)` | `x-karni-throttle` in the schema |
| Bots fill honeypots | `register/` (`website`) and public creates (`homepage`) answer 202 and save nothing | `KARNI_ACCOUNTS_HONEYPOT_FIELD`, `KARNI_PUBLIC_CREATE_HONEYPOT_FIELD` | `x-karni-honeypot` in the schema |
| A public form takes no file of rows | imports need a signed-in user when `create` or `write` is public | the declaration | the access gate |
| Scripts are pinned | a Content-Security-Policy on every response, report-only while `DEBUG` is on | `KARNI_CSP`, `KARNI_CSP_REPORT_ONLY`, `@csp_extend` | `karni.W518`, `karni.W519` |
| Powerful browser features are off | `Permissions-Policy` turns off camera, microphone, location, payment, USB and motion sensors | `KARNI_PERMISSIONS_POLICY` | |
| Referrers stay on the site | `Referrer-Policy: same-origin`, `nosniff` and `Cross-Origin-Opener-Policy`, from Django | `SECURE_REFERRER_POLICY` | Django's `security.W022` |
| No other site frames the pages | `X-Frame-Options: DENY` and `frame-ancestors 'none'` | `X_FRAME_OPTIONS` (`SAMEORIGIN` makes both `'self'`) | Django's `security.W002` |
| Production runs without `DEBUG` | `DJANGO_ENV=prod` turns it off | `DEBUG` | `karni.W510` |
| The secret key is secret | startup refuses the scaffold's key with `DEBUG` off | `SECRET_KEY` | `karni.W511`, `karni.E504` |
| Only the site's host names are answered | the production profile allows none until set, and startup refuses an empty list | `ALLOWED_HOSTS` | `karni.W512`, `karni.E504` |
| Cross-site forms are refused | Django's CSRF check, and session mode trusts `KARNI_FRONTEND_URL` | `CSRF_TRUSTED_ORIGINS` | `karni.W513` |
| Browsers use https only | HSTS for a year with subdomains and preload, and a redirect to https | `SECURE_HSTS_SECONDS` | `karni.W514`, Django's `security.W008` |
| Cookies never travel over http | secure session and CSRF cookies in production | `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | `karni.W515` |
| The admin is off the scanners' path | mounted at `KARNI_ADMIN_PATH` | `KARNI_ADMIN_PATH` | `karni.W516` |
| Other sites cannot call the API | CORS is closed in production unless `CORS_ALLOWED_ORIGINS` lists an origin | `CORS_ALLOWED_ORIGINS` | `karni.W517` |
| The welcome page is development only | served only while `DEBUG` is on | your own `path("", ...)` | `karni.E505` |
| Admin screens are row-scoped | the roles' grants decide which rows the admin shows | `scope_exempt` with a reason | `karni.E210` |

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
TOTP 2FA, social login, and (experimental) [sign-in with a Google, Microsoft
or Apple ID token](accounts.md#sign-in-with-an-id-token-google-microsoft-apple),
verified offline against the audience, issuer, nonce and verified email. Also
experimental, [sign-in with a code sent by
email](accounts.md#sign-in-with-a-code-sent-by-email) stores only an HMAC of
each code, keyed by `SECRET_KEY`, and kills a code after one use, its TTL or
`KARNI_EMAIL_OTP_MAX_ATTEMPTS` wrong guesses. See [accounts](accounts.md).

**Terms acceptance.** With `KARNI_TERMS` (experimental), the API refuses every
signed-in user, staff and superusers included, with a 403 (`E245`) until
they accept the current version of the terms
([terms acceptance](accounts.md#terms-acceptance)). The record is
append-only: each acceptance keeps the version, the time, the IP (read like
the throttles read it, so `NUM_PROXIES` must be right here too) and the user
agent, and code that tries to change or delete one gets `E247`. The IP and
the user agent are personal data, so name them in your privacy policy. The
gate covers `/api/` by default: the admin and a public site are not gated
unless `KARNI_TERMS["paths"]` lists them. It is a legal record, not an
access control: grant access with `access` and roles.

**Abuse.** Every auth endpoint has per-IP throttles, and login has a
per-account throttle as well (`KARNI_AUTH_THROTTLE_RATES`). Sign-in with a
code adds a per-address throttle on the codes one address receives. `NUM_PROXIES` is
set for the shipped Caddy (`KARNI_NUM_PROXIES`, default 1). Set it to `0`
whenever Django is exposed without a proxy that rewrites `X-Forwarded-For`,
or a spoofed header defeats the per-IP throttles. The password-reset endpoint
and sign-in with a code never reveal whether an address exists. Registration has a honeypot
(`KARNI_ACCOUNTS_HONEYPOT_FIELD`), and `karni.W501` warns when the throttle
counters would live in a per-process cache in production. A public form of
your own (`create=Public()`) is limited to 10 creates an hour per caller
(`KARNI_PUBLIC_CREATE_RATE`), has a honeypot field
(`KARNI_PUBLIC_CREATE_HONEYPOT_FIELD`) and accepts no anonymous imports, with
nothing declared ([rate limits](api.md#rate-limits)). `karni make form` writes
such a form, and the page's `{% karni_form %}` posts through Django's CSRF
check for signed-in and anonymous visitors alike
([public forms](public-site.md#public-forms)). Registration is open by
default. While it is, `karni.W102` warns for every viewset that lets any
signed-in user change and delete every row, and
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
referrer policy and `X-Frame-Options: DENY`. Every profile sends a
Content-Security-Policy and a Permissions-Policy
([security headers](#security-headers)). CORS is closed unless
`CORS_ALLOWED_ORIGINS` lists an origin. With `DEBUG` off, startup validation
refuses a missing `SECRET_KEY` or an empty `ALLOWED_HOSTS`, and
`karni check --deploy` reports every development value that is left
([deploy checks](#deploy-checks)).

**Admin.** It is mounted at `KARNI_ADMIN_PATH` (move it off `/admin/`).
Only staff users (`is_staff`) sign in. A role's grant, or Django's model
permission, decides which screens a staff user may open
(`KARNI_ADMIN_GRANTS_OPEN_PAGES = False` keeps Django's permissions only).
The roles' grants decide which rows those screens show and accept (row
scope, ADR 0002 P2). A staff user with permissions but no grant sees
nothing, and an admin that opts out needs a reason that `karni check` lists.
Only a superuser makes or edits a superuser. There is no logo unless
`KARNI_ADMIN_LOGO` says so.

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
per-field encryption (deliberately out of scope), a collector for CSP
violation reports (point `report-uri` at your own endpoint with `KARNI_CSP`),
and upload content validation beyond Django's `ImageField`. Until that
lands, validate uploads in the model's `clean()`.

## Security headers

`karni.security.SecurityHeadersMiddleware` sits right after Django's
`SecurityMiddleware` in the `MIDDLEWARE` that `karni_settings()` builds. It
adds two headers to every response Django sends: pages, the API and errors.
Django itself already sends `Referrer-Policy: same-origin`,
`X-Content-Type-Options: nosniff`, `Cross-Origin-Opener-Policy` and
`X-Frame-Options`, so the middleware does not repeat them.

In the production stack Caddy serves some files itself: the staff app, static
files and uploads. On every release `manage.py karni_publish_web` writes the
headers Django would send, computed from the same settings, into a snippet the
`Caddyfile` imports, so the staff app gets the same policy as a Django page
([deploying to a server](deploy.md#the-staff-app)).

### The Content-Security-Policy

| Directive | Default | Why |
|---|---|---|
| `default-src` | `'self'` | Anything without its own directive loads only from the site. |
| `script-src` | `'self'` and the hash of `@karni/ui`'s theme script | Scripts come from the site's own files. No inline script runs except the pre-paint theme script `karniTheme()` puts in `index.html`, so an injected `<script>` or `onclick=` does nothing. |
| `style-src` | `'self' 'unsafe-inline'` | The admin, the browsable API, Swagger UI and Radix (inside `@karni/ui`) set inline styles. A style cannot run code. |
| `img-src` | `'self' data: blob:` | Images from the site, `data:` icons in stylesheets, and `blob:` previews of a file picked for upload. With `KARNI_STORAGE = "s3"` the bucket's origin is added, and to `media-src` too. |
| `font-src` | `'self' data:` | The admin ships its own fonts. Inline fonts in stylesheets. |
| `connect-src` | `'self'` | `fetch` and XHR go to the site's own API. |
| `object-src` | `'none'` | No plugins (`<object>`, `<embed>`). |
| `base-uri` | `'self'` | An injected `<base>` cannot send relative URLs elsewhere. |
| `form-action` | `'self'` | Forms submit to the site only. |
| `frame-ancestors` | `'none'` | No other site may frame a page (clickjacking). It follows `X_FRAME_OPTIONS`: `SAMEORIGIN` makes it `'self'`. |

While `DEBUG` is on, the policy is sent as
`Content-Security-Policy-Report-Only`: the browser lists in its console
what the policy would block and blocks nothing, so development never breaks
and you still see what production would refuse. `KARNI_CSP_REPORT_ONLY =
True` or `False` overrides that either way.

`KARNI_CSP` adds to the policy. Each key is a directive. A list adds sources
to it (adding to `'none'` replaces the `'none'`), and `None` removes the
directive. Adding `'unsafe-inline'` drops the directive's hashes and nonces,
because browsers ignore `'unsafe-inline'` next to either. For Google Fonts:

```python
# config/settings.py, after karni_settings(globals())
KARNI_CSP = {
    "style-src": ["https://fonts.googleapis.com"],
    "font-src": ["https://fonts.gstatic.com"],
}
```

or the same JSON in `.env`:
`KARNI_CSP={"style-src": ["https://fonts.googleapis.com"], "font-src": ["https://fonts.gstatic.com"]}`.
An analytics script is `{"script-src": ["https://plausible.io"],
"connect-src": ["https://plausible.io"]}`. `KARNI_CSP = None` sends no
policy at all, for a proxy that sets its own.

Some pages need more than the site-wide policy, and get it on that page only:

| Page | Added | Why |
|---|---|---|
| the admin (any URL in the `admin` namespace) | `script-src 'unsafe-eval'` | django-unfold runs Alpine.js, which evaluates its `x-data` expressions with `new Function`. |
| drf-spectacular's Swagger UI | its CDN (`SPECTACULAR_SETTINGS["SWAGGER_UI_DIST"]`) for scripts, styles and images, and `'unsafe-inline'` for its start-up script | `SpectacularSwaggerSplitView`, which a new project's `urls.py` uses, serves that script as a file and gets no `'unsafe-inline'`. |
| drf-spectacular's Redoc | its CDN, `'unsafe-inline'`, Google Fonts, Redocly's logo (`https://cdn.redoc.ly`) and `worker-src blob:` | Redoc's page loads its fonts from Google, shows Redocly's logo and starts with an inline script. |
| django-allauth's provider pages | `form-action https:` | Their form redirects to the provider (Google, GitHub and so on). |
| the welcome page | the hashes of its two inline scripts | Nothing else inline runs there either. |

A view of your own adds sources with `@csp_extend({...})` (the format of
`KARNI_CSP`), sends no policy with `@csp_exempt`, or sets the header itself,
which the middleware then leaves alone. For an inline script, allow its
hash: `karni.security.script_hash(source)`. Code that runs while the
response is built and has the request but not the response, a template tag
for example, adds sources for that response with
`karni.security.extend_request_csp(request, {...})`. A public site built
from a designer's pages uses it through the `karni-site` module's tags:
`{% csp_hash %}` around an inline script allows exactly that script by its
hash, and `{% csp_allow "font-src https://fonts.gstatic.com" %}` declares
an origin next to the markup that loads from it, so the design runs under
the policy without `'unsafe-inline'`
([public pages](public-site.md#the-design-under-the-content-security-policy)).
A hash added to a directive that already allows `'unsafe-inline'` is left
out, because a browser that sees a hash ignores the `'unsafe-inline'`. For
anything else, subclass the middleware, override `csp_directives()` or
`page_directives()`, and list the subclass in `MIDDLEWARE` in its place.

The `@karni/ui` app is served by Vite in development and by your static host
in production, so Django's header does not reach its `index.html`. The
default policy is written so the app works under it: the theme script's
hash, inline styles, `blob:` previews and `'self'` for the API. To send the
same policy from the host, print it:

```bash
python manage.py shell -c "from karni.security import csp_directives, render_csp; print(render_csp(csp_directives()))"
```

and set it there, for example with `header Content-Security-Policy "<that value>"`
in the Caddyfile block that serves the frontend.

### The Permissions-Policy

`accelerometer`, `camera`, `geolocation`, `gyroscope`, `magnetometer`,
`microphone`, `payment` and `usb` are switched off for every page and
anything it embeds. No Karni page uses them, and a hosted checkout
(`karni-payments`) runs on the provider's site. Allow one back with
`KARNI_PERMISSIONS_POLICY`, which maps a feature to the origins that may use
it (`"self"`, `"*"` or an origin), or to `None` to leave it out:

```python
KARNI_PERMISSIONS_POLICY = {"geolocation": ["self"]}
```

`KARNI_PERMISSIONS_POLICY = None` sends no header.

## Deploy checks

`karni check --deploy` runs Django's `check --deploy` and Karni's own deploy
checks, prints every finding with its code and its fix, and fails on a
warning as well as an error. Run it with the production environment, in CI
before a release or on the server:

```bash
DJANGO_ENV=prod SECRET_KEY=... ALLOWED_HOSTS=example.com \
CSRF_TRUSTED_ORIGINS=https://example.com KARNI_ADMIN_PATH=staff-7f3a9c/ \
karni check --deploy
```

With the scaffold's development values it fails, one code per problem:

| Code | Reports |
|---|---|
| [karni.W510](errors.md#w510-debug-is-on-in-a-deployment) | `DEBUG` is on |
| [karni.W511](errors.md#w511-secret_key-is-weak-or-a-development-key) | `SECRET_KEY` is the scaffold's, contains "insecure", or has fewer than 50 characters or fewer than 5 different ones |
| [karni.W512](errors.md#w512-allowed_hosts-is-empty-or-allows-every-host) | `ALLOWED_HOSTS` is empty or contains `*` |
| [karni.W513](errors.md#w513-csrf_trusted_origins-is-missing-a-wildcard-or-plain-http) | `CSRF_TRUSTED_ORIGINS` is empty, a wildcard or plain http |
| [karni.W514](errors.md#w514-hsts-is-off) | `SECURE_HSTS_SECONDS` is 0 |
| [karni.W515](errors.md#w515-the-session-or-csrf-cookie-is-not-marked-secure) | the session or CSRF cookie is not secure |
| [karni.W516](errors.md#w516-the-admin-is-at-admin) | the admin answers at `/admin/` |
| [karni.W517](errors.md#w517-cors-allows-every-origin) | CORS allows every origin |
| [karni.W518](errors.md#w518-no-enforced-content-security-policy) | no Content-Security-Policy, or only a report-only one |
| [karni.W519](errors.md#w519-the-content-security-policy-lets-any-script-run) | `script-src` allows `*`, `http:`, `https:`, `data:`, `'unsafe-eval'` or `'unsafe-inline'` |
| [karni.W520](errors.md#w520-production-email-is-not-set-up) | `EMAIL_BACKEND` is the console, locmem, dummy or file backend, or `DEFAULT_FROM_EMAIL` is an address at localhost (Django's `webmaster@localhost`) |

The checks are Django system checks registered for deployment
(`@register(Tags.security, deploy=True)`), so `python manage.py check
--deploy` runs them too. Where one covers a Django warning (`security.W018`
for `DEBUG`, `W009` for the key, `W020` for hosts, `W004` for HSTS, `W012`
and `W016` for the cookies), `karni check --deploy` prints only Karni's,
whose fix names the setting to change in a Karni project. The other
warnings `karni check` knows, such as `karni.W102` for a resource any
signed-in user may change, fail a deploy check too. Silence one you accept
on purpose with `SILENCED_SYSTEM_CHECKS += ["karni.W516"]`.

### At container start

The production image runs the same checks before any command it starts
(`python -m karni.deploy.entrypoint`, the `ENTRYPOINT` of the scaffold's
`prod` target, and the `entrypoint` of `docker-compose.prod.yml`). A failing
check stops the container with [`E520`](errors.md#e520-the-deploy-checks-failed-when-the-container-started),
so a deployment with a development value never serves a request.
`KARNI_SKIP_DEPLOY_CHECK=1` starts it anyway in an emergency, and every
start then logs that the checks did not run. `KARNI_DEPLOY_CHECK_COMMAND`
replaces the check command. See [deploying to a server](deploy.md).
