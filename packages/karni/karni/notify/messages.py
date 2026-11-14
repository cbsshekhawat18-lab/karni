"""The message kinds of the notifications contract: the email of each move.

``karni.mail`` imports every installed app's ``messages.py`` the first time it
lists the kinds. This one declares the email of each move that names a
recipient (``moves.<state>.notify`` in karni.yaml) as a kind, unless a part
declared that name itself (:func:`karni.notify.moves.declare_move_kinds`).
"""

from __future__ import annotations

from karni.notify.moves import declare_move_kinds

declare_move_kinds()
