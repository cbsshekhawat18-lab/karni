"""The URLs of protected files, mounted next to the API with one include::

    path("api/", include("karni_storage.urls")),

which gives, for every resource the API routes:

* ``api/<resource>/<id>/files/<field>/``: the file (``karni_storage:download``),
* ``api/<resource>/files/<field>/upload/``: a direct upload (``karni_storage:upload``),
* ``api/<resource>/files/<field>/confirm/``: its check (``karni_storage:confirm``).

A ``<resource>`` is the router prefix of the model's viewset and may contain
``/``. The routes cannot match the API's own (they end in ``files/...``), so
the include goes before or after ``karni.api.urls``.

Override / escape hatch: declare your own ``path()`` for one of them before
the include, since the first match wins.
"""

from __future__ import annotations

from django.urls import re_path

from karni_storage.views import ConfirmView, FileView, UploadView

app_name = "karni_storage"

_RESOURCE = r"(?P<resource>[^.]+?)"
_FIELD = r"(?P<field>[A-Za-z_][A-Za-z0-9_]*)"

urlpatterns = [
    re_path(rf"^{_RESOURCE}/files/{_FIELD}/upload/$", UploadView.as_view(), name="upload"),
    re_path(rf"^{_RESOURCE}/files/{_FIELD}/confirm/$", ConfirmView.as_view(), name="confirm"),
    re_path(rf"^{_RESOURCE}/(?P<pk>[^/.]+)/files/{_FIELD}/$", FileView.as_view(), name="download"),
]
