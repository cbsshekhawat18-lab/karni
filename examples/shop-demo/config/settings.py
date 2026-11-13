"""Django settings for Shop Demo.

karni_settings() fills this module with Karni's defaults: INSTALLED_APPS,
middleware, DRF, Celery, Redis cache, storage, logging, security headers,
CORS and Sentry, all read from environment variables (see .env.example).

Overriding: anything assigned *after* the call wins, and any name defined
*before* the call is never overwritten by Karni. The call also leaves `env`
here: the django-environ reader Karni reads its defaults with, so a setting
added below can come from .env the same way.

The exception: the call reads KARNI_AUTH_MODE, KARNI_2FA, KARNI_SOCIAL_AUTH,
KARNI_SOCIAL_PROVIDERS, KARNI_FRONTEND_URL, KARNI_AUTH_THROTTLE_RATES,
KARNI_JSON_LOGS, KARNI_CACHE and KARNI_STORAGE to compute other settings.
Set those in .env, above the call, or as karni_settings(globals(), NAME=...).
Assigned below the call they change nothing, and startup fails with
karni.E508. See docs/settings.md.
"""

from pathlib import Path

from karni.conf import karni_settings

# The project folder. Karni reads relative paths from it (MEDIA_ROOT in
# development, content/site.json in tests), whatever folder a command runs in.
BASE_DIR = Path(__file__).resolve().parent.parent

# karni:spec start
# Roles, features and module options from karni.yaml. Change them there and run
# karni build: it rewrites the lines between the markers.
KARNI_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    "customer": {
        "name": "Customer",
        "grants": {
            "shop.cart:*": "own",
            "shop.cartitem:*": "own",
            "shop.order:*": "own",
            "shop.orderitem:*": "own",
        },
    },
}
KARNI_ACCOUNTS_DEFAULT_ROLES = ["customer"]
KARNI_2FA = False
KARNI_EMAIL_OTP = True
KARNI_SOCIAL_TOKEN_PROVIDERS = {}
KARNI_TERMS = {"version": "2026-01", "url": "/terms/"}
KARNI_USER_GRANTS = False
KARNI_PAYMENTS_PROVIDER = "stripe"
KARNI_PAYMENTS_CURRENCY = "usd"
# karni:spec end

karni_settings(globals())

# --- Project apps ------------------------------------------------------------
INSTALLED_APPS += [  # noqa: F821
    # "myapp",
    "karni_payments",
    "shop",
    "karni.demo",
]  # karni:apps

# --- Project middleware (runs after Karni's stack) ----------------------------
MIDDLEWARE += [  # noqa: F821
    # "myapp.middleware.MyMiddleware",
    "karni.demo.middleware.DemoResetMiddleware",
    "karni.demo.middleware.DemoWriteGuardMiddleware",
]  # karni:middleware

# A new project never read the deprecated X-Karni-Cache header, so it is not sent.
# Existing projects keep sending it, with a deprecation warning, until 1.0.
KARNI_API_CACHE_LEGACY_HEADER = env.bool("KARNI_API_CACHE_LEGACY_HEADER", default=False)  # noqa: F821

# --- Project overrides -------------------------------------------------------
# Any Django/Karni setting assigned here beats the Karni default, e.g.:
# REST_FRAMEWORK["PAGE_SIZE"] = 25
# CELERY_TASK_TIME_LIMIT = 600
# FEATURE_X = env.bool("FEATURE_X", default=False)
# SILENCED_SYSTEM_CHECKS starts empty. Extend it to silence a check on purpose:
# SILENCED_SYSTEM_CHECKS += ["karni.W967"]

# --- One small service (render.yaml at the repository root, docs/demo.md) -----
# The demo runs as one service on a small instance: SQLite on the instance's
# disk, Celery tasks inside the request, Karni's in-process cache
# (KARNI_CACHE=locmem) and WhiteNoise serving the React build and the static
# files. Each part is a setting read from the environment, so the same project
# still runs on the usual stack (docker-compose.prod.yml).

# SQLite with several worker processes: WAL lets reads go on during a write,
# BEGIN IMMEDIATE takes the write lock when a transaction starts (no deadlock
# when a reading transaction starts to write), and a write waits up to 20
# seconds for the lock instead of failing.
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":  # noqa: F821
    DATABASES["default"].setdefault("OPTIONS", {}).update(  # noqa: F821
        {"init_command": "PRAGMA journal_mode=WAL", "transaction_mode": "IMMEDIATE", "timeout": 20}
    )

# Render generates 256-bit random values, 44 characters long, and the deploy
# check asks for a SECRET_KEY of 50 characters or more: render.yaml generates
# two values, and the key is both together.
SECRET_KEY += env.str("SECRET_KEY_PART_2", default="")  # noqa: F821

# A cache every worker process shares, without Redis: CACHE_URL in
# django-environ's format (filecache:///data/cache) replaces the cache
# KARNI_CACHE picks, so the sign-in throttles count per client, not per worker.
if env.str("CACHE_URL", default=""):  # noqa: F821
    CACHES = {"default": env.cache_url("CACHE_URL")}  # noqa: F821

# Without a Celery worker, tasks run inside the request that queues them.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)  # noqa: F821

# karni.yaml names Stripe. The demo takes no money: KARNI_PAYMENTS_PROVIDER=test
# opens checkouts with karni-payments' test provider instead.
KARNI_PAYMENTS_PROVIDER = env("KARNI_PAYMENTS_PROVIDER", default=KARNI_PAYMENTS_PROVIDER)  # noqa: F821

# WhiteNoise serves the collected static files, and the React build's own files
# (frontend/dist: /assets/..., /favicon.svg) at the site's root. Django answers
# every other path of the app with its index.html (karni.demo.urls).
MIDDLEWARE.insert(  # noqa: F821
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,  # noqa: F821
    "whitenoise.middleware.WhiteNoiseMiddleware",
)
_APP_BUILD = BASE_DIR / "frontend" / "dist"
if _APP_BUILD.is_dir():
    WHITENOISE_ROOT = _APP_BUILD
# The build's hashed files (/assets/index-B2xk9aQe.js) never change: cached for a year.
WHITENOISE_IMMUTABLE_FILE_TEST = r"^/assets/.+-[0-9A-Za-z_-]{8}\.[0-9a-z]+$"
# The React build's index.html is served by karni.demo.urls.app_urls() (KARNI_DEMO_APP_INDEX
# defaults to frontend/dist/index.html).

# Demo mode (karni.demo, docs/demo-mode.md). KARNI_DEMO_MODE is read from DEMO_MODE (or
# KARNI_DEMO_MODE), the reset period from DEMO_RESET_HOURS and the seed from DEMO_SEED, as
# render.yaml sets them. Only the demo accounts write, never to their own password, email or
# roles. The data resets to `karni seed` with the fixed seed every KARNI_DEMO_RESET_HOURS
# hours. The sign-in pages list the accounts below with what each can do. Off by default:
# the project is a plain shop until DEMO_MODE=True.
KARNI_DEMO_ACCOUNTS = [
    {
        "login": "demo@example.com",
        "label": "Staff",
        "can": "Manage categories, products, carts and orders, and open the admin.",
        "roles": "all",
        "staff": True,
        "superuser": True,
    },
    {
        "login": "customer@example.com",
        "label": "Customer",
        "can": "Fill a cart, check out with the test provider and read their own orders.",
        "roles": ["customer"],
    },
]
# The payment webhook stays Django's, not the app's page.
KARNI_DEMO_APP_RESERVED = ["payments"]
if KARNI_DEMO_MODE:  # noqa: F821
    # No sign-up: nobody opens an account, and a sign-in code goes only to an existing one.
    KARNI_ACCOUNTS_REGISTRATION = False
    KARNI_EMAIL_OTP_SIGNUP = "existing"
    SILENCED_SYSTEM_CHECKS += [  # noqa: F821
        # The demo sends no email: sign-up, password resets and sign-in codes are
        # closed (karni.demo.guard), and Render's free plan blocks the SMTP ports.
        "karni.W520",
        # The admin stays at /admin/ on purpose: the sign-in page shows it to every
        # visitor, and the only account that can change anything there is the
        # public demo account.
        "karni.W516",
        # SQLite on purpose (no paid database, and the data resets every day):
        # prices are exact to 15 significant digits, and product search matches
        # the fields instead of a full-text index.
        "karni.W964",
    ]
