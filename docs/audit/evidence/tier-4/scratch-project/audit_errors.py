"""Tier 4 audit, item 3: trigger five Karni errors and print what a developer sees.

Run: python manage.py shell -c "exec(open('<this file>').read())"
"""

from django.test import override_settings

from karni.errorcodes import KarniError


def show(label, fn):
    print(f"\n### {label}")
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        print(f"type: {type(exc).__module__}.{type(exc).__name__}")
        print(f"code: {getattr(exc, 'code', '<none>')}")
        print(f"docs: {getattr(exc, 'docs_url', '<none>')}")
        print("str(exc):")
        print(str(exc))
        print(f"is KarniError: {isinstance(exc, KarniError)}")
    else:
        print("NO ERROR RAISED")


# 1. Owned() without a field
def owned_without_field():
    from karni.api.access import Owned

    Owned()


show("1. Owned() without a field (expect E104)", owned_without_field)


# 2. Can('x') — not an app_label.model:action key
def can_x():
    from karni.api.access import Can

    Can("x")


show("2. Can('x') (expect E209)", can_x)


# 3. KARNI_ROLES with a typo in a grant key (evnt instead of event)
def roles_typo():
    from karni.accounts.roles import sync_roles

    sync_roles(
        {"staff": {"name": "Staff", "grants": {"events.evnt:view": "all"}}},
        dry_run=True,
    )


show("3. KARNI_ROLES grant with a typo: 'events.evnt:view' (expect E206)", roles_typo)


# 3b. KARNI_ROLES malformed (a scope that does not exist)
def roles_malformed():
    from karni.accounts.roles import declared_roles

    declared_roles({"staff": {"grants": {"events.event:view": "everything"}}})


show("3b. KARNI_ROLES with an unknown scope 'everything' (expect E205)", roles_malformed)


# 4. A settings backend that cannot be imported
def missing_email_backend():
    from karni.accounts import emails

    with override_settings(KARNI_ACCOUNTS_EMAIL_BACKEND="myproject.mail.NoSuchBackend"):
        emails.get_email_backend()


show("4. KARNI_ACCOUNTS_EMAIL_BACKEND points at a module that does not exist (expect E201)", missing_email_backend)


def wrong_kind_of_email_backend():
    from karni.accounts import emails

    with override_settings(KARNI_ACCOUNTS_EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
        emails.get_email_backend()


show("4b. KARNI_ACCOUNTS_EMAIL_BACKEND names a Django mail backend, not an AccountsEmailBackend (expect E201)", wrong_kind_of_email_backend)


def bad_search_provider():
    from karni.api.search import get_search_provider  # noqa: F401

    with override_settings(KARNI_SEARCH_PROVIDER="nowhere.NoSuchProvider"):
        get_search_provider()


show("4c. KARNI_SEARCH_PROVIDER points at a module that does not exist", bad_search_provider)


# 5. A viewset-level declaration error raised at class creation: HasRole() with no roles
def hasrole_empty():
    from karni.api.access import HasRole

    HasRole()


show("5. HasRole() with no role names (expect E105)", hasrole_empty)


# 6. Unscoped() without a reason
def unscoped_no_reason():
    from karni.api.access import Unscoped

    Unscoped(reason="")


show("6. Unscoped(reason='') (expect E107)", unscoped_no_reason)

# 7. The E101 case (a viewset without access) is a system check: see karni-check-no-access.txt
print("\n### 7. A viewset without access (E101) — see enforcement evidence (manage.py check output)")
