"""HTTP surface of :mod:`karni.accounts`: serializers, views and throttles.

Kept import-light on purpose — importing this package must never pull in
models or settings-dependent code, so Django's app loading and lazy URLconf
imports stay safe. Import the concrete pieces from their modules::

    from karni.accounts.api.serializers import MeSerializer
    from karni.accounts.api.throttles import AccountRateThrottle
    from karni.accounts.api.views import LoginView

Override / escape hatch: every endpoint can be replaced by declaring your own
``path("api/auth/<endpoint>/", YourView.as_view())`` *before*
``include("karni.accounts.urls")`` — first match wins. Subclass the views or
serializers here to change one behaviour and keep the rest.
"""
