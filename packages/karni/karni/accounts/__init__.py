"""Karni accounts: email-based users, one-time tokens and auth plumbing.

Installed by default via :func:`karni.conf.karni_settings` (app label
``karni_accounts``) together with ``AUTH_USER_MODEL = "karni_accounts.User"``.

Override / escape hatch: projects that need extra user fields subclass
:class:`karni.accounts.models.AbstractKarniUser` in their own app and set
``AUTH_USER_MODEL = "myapp.User"`` **before the first migrate** — see
``docs/accounts.md`` for the full swap path.
"""
