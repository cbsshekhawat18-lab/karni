"""The public demo: what makes this shop safe to put online for anyone to try.

Everything here is switched on by ``DEMO_MODE`` (settings, from the environment)
and read per request, so a test turns it on with a settings override:

* :mod:`demo.account`: the demo login, the account every visitor signs in with
  (``karni seed``'s ``demo@example.com`` / ``karni-password``).
* :mod:`demo.guard`: who may write. Only the demo account, and never to its own
  password, email or roles, so the next visitor can still sign in.
* :mod:`demo.reset`: the data goes back to ``karni seed --seed DEMO_SEED`` at
  boot and every ``DEMO_RESET_HOURS`` hours.
* :mod:`demo.middleware`: the two above, on every request.
* :mod:`demo.views`: the built React app at ``/``, with the demo login in its page.
* ``manage.py demo_boot``: migrate, then seed or reset (the start command runs it).

Settings (``config/settings.py``): ``DEMO_MODE``, ``DEMO_SEED`` (42),
``DEMO_RESET_HOURS`` (24), ``DEMO_RESET_STAMP`` (where the last reset is
recorded), ``DEMO_RESET_CHECK_SECONDS`` (60), ``DEMO_RESET_KEEP_APPS`` and
``DEMO_APP_INDEX`` (the built ``index.html``). See docs/demo.md.
"""
