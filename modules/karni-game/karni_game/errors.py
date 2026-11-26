"""The errors the game API answers with: a status, a code and the fix.

Every refusal the server decides is a :class:`GameError`. The player views
answer it as ``{"detail": "GAME008: ... See <docs url>", "code": "GAME008",
...extra}`` with its status (docs/game-api.md, Errors). A service raises it
the same way, so a project's own view or task that calls a service gets the
same refusal.

Override / escape hatch: catch :class:`GameError` in your own view and shape
the answer yourself; ``error.payload()`` is the body the game API sends.
"""

from __future__ import annotations

from typing import Any

from karni.errorcodes import docs_url
from rest_framework.exceptions import APIException

__all__ = ["GameError", "game_error"]


class GameError(APIException):
    """A refusal of the game API: ``status_code``, ``code`` and extra fields for the body."""

    status_code = 400
    default_detail = "The game refused the request."
    default_code = "game"

    def __init__(self, code: str, message: str, *, status: int = 400, **extra: Any) -> None:
        self.game_code = code
        self.message = message
        self.status_code = status
        self.extra = extra
        super().__init__(detail=f"{code}: {message} See {docs_url(code)}", code=code)

    def payload(self) -> dict[str, Any]:
        """The body the API answers: ``detail``, ``code`` and the extra fields."""
        return {"detail": str(self.detail), "code": self.game_code, **self.extra}

    def __str__(self) -> str:
        return str(self.detail)


def game_error(code: str, message: str, *, status: int = 400, **extra: Any) -> GameError:
    """A :class:`GameError` to raise: ``raise game_error("GAME006", "...", status=404)``."""
    return GameError(code, message, status=status, **extra)
