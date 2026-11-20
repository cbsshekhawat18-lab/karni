"""karni-game (experimental): the server side of a game, for any game a project hosts.

A game's player is a person of the people contract (:mod:`karni.people`): a
guest first, with a token the server issues, then an account, keeping the
guest's progress. Each game (:class:`~karni_game.models.Game`) has versioned
cloud saves, leaderboards with plausible ranges, a soft-currency wallet with
a ledger, daily content on the server's date, achievements and missions,
remote config and feature flags, analytics through the family events, and a
contract for a realtime server of the project's own. The server decides
every reward and every balance: a client only reports and asks.

The client's HTTP contract is docs/game-api.md. Project code talks to the
service modules (:mod:`karni_game.players`, :mod:`karni_game.saves`,
:mod:`karni_game.scores`, :mod:`karni_game.wallet`, ...).
"""

from __future__ import annotations

from importlib import metadata as _metadata

#: The version of the game contract (the HTTP API of docs/game-api.md, the hooks of
#: :mod:`karni_game.hooks` and the family events of :mod:`karni_game.events`).
#: Experimental.
CONTRACT = 1

try:
    __version__ = _metadata.version("karni-game")  # [project] version in pyproject.toml
except _metadata.PackageNotFoundError:  # a source tree on sys.path, never installed
    __version__ = "0+unknown"
