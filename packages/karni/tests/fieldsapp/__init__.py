"""Fixture app for the typed field layer (``karni.fields``, ``tests/fields/``).

``tests/settings.py`` appends ``"tests.fieldsapp"`` to ``INSTALLED_APPS``. It
has no viewsets module on purpose: the API, its schema snapshot and the
router never see these models; the field tests build viewsets locally.
"""
