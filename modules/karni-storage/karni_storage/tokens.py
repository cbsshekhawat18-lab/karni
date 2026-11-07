"""The signed tokens of the direct upload flow and of local download links.

Three kinds, each signed with ``SECRET_KEY`` under its own salt, so one can
never stand in for another:

* the **upload** token the upload step gives: the file's name in the storage,
  the model and field, the user, the size limit and the declared type. Only
  confirm takes it, within ``KARNI_STORAGE_UPLOAD_EXPIRY`` (plus a minute).
* the **confirmed** token confirm gives once the object passed its checks:
  the name, model, field and user. Only a row's create or update takes it,
  within :data:`CONFIRMED_MAX_AGE`, and only from the same user for the same
  field, so nobody can point a row at an object somebody else uploaded.
* the **download** token of a local-storage link (``?sig=``): the row, the
  field, the size and the file's name, for ``KARNI_STORAGE_URL_EXPIRY``
  seconds. A replaced file invalidates it.

Override / escape hatch: rotate ``SECRET_KEY`` (with ``SECRET_KEY_FALLBACKS``)
to invalidate every token at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from django.core import signing

from karni_storage import conf
from karni_storage.errorcodes import coded

__all__ = [
    "CONFIRMED_MAX_AGE",
    "TokenError",
    "Upload",
    "confirmed_token",
    "download_token",
    "read_confirmed",
    "read_download",
    "read_upload",
    "upload_token",
    "user_key",
]

#: Seconds a confirmed upload may wait for the row that takes it (a form left open).
CONFIRMED_MAX_AGE: Final[int] = 24 * 60 * 60

_UPLOAD_SALT: Final = "karni_storage.upload"
_CONFIRMED_SALT: Final = "karni_storage.confirmed"
_DOWNLOAD_SALT: Final = "karni_storage.download"


class TokenError(ValueError):
    """A token that is altered, expired or not for this user and field (``STORE013``)."""

    def __init__(self, message: str, code: str = "STORE013") -> None:
        super().__init__(coded(code, message))
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Upload:
    """Experimental. What an upload or confirmed token says."""

    name: str
    model: str
    field: str
    user: str | None
    max_size: int = 0
    content_type: str = ""


def _user(user: Any) -> str | None:
    pk = getattr(user, "pk", None)
    return None if pk is None or not getattr(user, "is_authenticated", False) else str(pk)


def upload_token(upload: Upload) -> str:
    """Experimental. The token the upload step answers with."""
    return signing.dumps(
        {
            "n": upload.name,
            "m": upload.model,
            "f": upload.field,
            "u": upload.user,
            "s": upload.max_size,
            "t": upload.content_type,
        },
        salt=_UPLOAD_SALT,
    )


def confirmed_token(upload: Upload) -> str:
    """Experimental. The token confirm answers with, which a row's create or update takes."""
    return signing.dumps(
        {"n": upload.name, "m": upload.model, "f": upload.field, "u": upload.user},
        salt=_CONFIRMED_SALT,
    )


def _read(token: str, salt: str, max_age: int, what: str) -> dict[str, Any]:
    try:
        data = signing.loads(str(token), salt=salt, max_age=max_age)
    except signing.SignatureExpired:
        raise TokenError(f"The {what} token expired. Upload the file again.") from None
    except signing.BadSignature:
        raise TokenError(f"That is not a valid {what} token.") from None
    if not isinstance(data, dict) or not isinstance(data.get("n"), str):
        raise TokenError(f"That is not a valid {what} token.")
    return data


def _check(data: dict[str, Any], model: str, field: str, user: Any, what: str) -> Upload:
    if data.get("m") != model or data.get("f") != field:
        target = f"{data.get('m')}.{data.get('f')}"
        raise TokenError(f"The {what} token is for {target}, not this field.")
    if data.get("u") != _user(user):
        raise TokenError(f"The {what} token was given to another user.")
    return Upload(
        name=str(data["n"]),
        model=model,
        field=field,
        user=data.get("u"),
        max_size=int(data.get("s") or 0),
        content_type=str(data.get("t") or ""),
    )


def read_upload(token: str, *, model: str, field: str, user: Any) -> Upload:
    """Experimental. The upload ``token`` says, checked for ``model``, ``field`` and ``user``.

    :raises TokenError: ``STORE013``.
    """
    max_age = int(conf.get("KARNI_STORAGE_UPLOAD_EXPIRY")) + 60
    return _check(_read(token, _UPLOAD_SALT, max_age, "upload"), model, field, user, "upload")


def read_confirmed(token: str, *, model: str, field: str, user: Any) -> Upload:
    """Experimental. The confirmed upload ``token`` says, checked like :func:`read_upload`.

    :raises TokenError: ``STORE013``.
    """
    data = _read(token, _CONFIRMED_SALT, CONFIRMED_MAX_AGE, "upload")
    return _check(data, model, field, user, "upload")


def user_key(user: Any) -> str | None:
    """Experimental. How a token names ``user``: the primary key, ``None`` for anonymous."""
    return _user(user)


def download_token(*, model: str, pk: Any, field: str, size: str, name: str) -> str:
    """Experimental. The ``?sig=`` of a local-storage download link."""
    return signing.dumps(
        {"m": model, "p": str(pk), "f": field, "z": size, "n": name}, salt=_DOWNLOAD_SALT
    )


def read_download(token: str, *, model: str, pk: Any, field: str, size: str, name: str) -> None:
    """Experimental. Check a ``?sig=`` against the row, field, size and current file name.

    :raises TokenError: ``STORE019``.
    """
    max_age = int(conf.get("KARNI_STORAGE_URL_EXPIRY"))
    try:
        data = signing.loads(str(token), salt=_DOWNLOAD_SALT, max_age=max_age)
    except signing.SignatureExpired:
        raise TokenError("The download link expired.", code="STORE019") from None
    except signing.BadSignature:
        raise TokenError("That is not a valid download link.", code="STORE019") from None
    expected = {"m": model, "p": str(pk), "f": field, "z": size, "n": name}
    if data != expected:
        raise TokenError(
            "The download link is for another file (or the file was replaced).", code="STORE019"
        )
