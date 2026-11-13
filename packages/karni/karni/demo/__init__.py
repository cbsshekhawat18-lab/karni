"""Experimental. Demo mode: what makes a project safe to put online for anyone to try.

One public demo has the same rules whatever the project is, so they live here
and a project only names its accounts. Demo mode is core and not a module
because it has no service and no extra memory cost: it is a few settings, one
middleware, a lock file and one management command.

Everything is read from settings on each call, so a test turns it on with a
settings override. Nothing happens while ``KARNI_DEMO_MODE`` is off.

* :mod:`karni.demo.conf`: the settings and the demo accounts
  (:class:`~karni.demo.conf.DemoAccount`, one per role).
* :mod:`karni.demo.accounts`: puts every demo account back as it was made
  (password, flags, roles, accepted terms).
* :mod:`karni.demo.guard`: who may write. Only demo accounts, and never to
  their own password, email or roles, so the next visitor can still sign in.
* :mod:`karni.demo.reset`: the data goes back to ``karni seed`` with a fixed
  seed at boot and every ``KARNI_DEMO_RESET_HOURS`` hours, by one worker.
* :mod:`karni.demo.middleware`: the reset check and the write rule, per request.
* :mod:`karni.demo.views` and :mod:`karni.demo.urls`: ``GET /api/demo/`` (what
  the sign-in notice shows) and the built React app at ``/``.
* ``manage.py karni_demo_boot``: migrate, then seed or reset (the start command).
* ``DemoNotice`` and ``DemoSignInPrompt`` in ``@karni/ui`` show the accounts.

Wiring, in the project's settings and URLs::

    INSTALLED_APPS += ["karni.demo"]
    MIDDLEWARE += [
        "karni.demo.middleware.DemoResetMiddleware",
        "karni.demo.middleware.DemoWriteGuardMiddleware",
    ]
    KARNI_DEMO_MODE = env.bool("DEMO_MODE", default=False)
    KARNI_DEMO_ACCOUNTS = [
        {"login": "demo@example.com", "label": "Staff", "can": "Everything.", "roles": "all",
         "staff": True, "superuser": True},
        {"login": "customer@example.com", "label": "Customer", "roles": ["customer"],
         "can": "Place orders and read their own history."},
    ]
    # urls.py: path("api/demo/", include("karni.demo.urls")), and last: *app_urls()

Override / escape hatch: every rule is a plain function of settings or of the
request (:func:`karni.demo.guard.refusal`, ``KARNI_DEMO_WRITE_RULE``,
``KARNI_DEMO_SEEDER``, ``KARNI_DEMO_OPEN_PATHS``, ``KARNI_DEMO_LOCKED_PATHS``),
and the middleware classes only call them, so a project swaps any one in
``MIDDLEWARE``. See docs/demo-mode.md.
"""
