"""The family events karni-game publishes (``karni.events``).

Another part subscribes by name and never imports karni-game::

    from karni.events import Event, subscribe


    @subscribe("game.achievement.unlocked", version=1)
    def congratulate(event: Event) -> None:
        ...  # event["game"], event["achievement"], event["title"], event.person

=============================  ==========================================================
Event                          Declared fields
=============================  ==========================================================
``game.player.joined``         player, game (blank: the player is not of one game), guest
``game.player.upgraded``       player, user, adopted
``game.achievement.unlocked``  game, player, achievement, title
``game.mission.completed``     game, player, mission, title, period_start
``game.item.bought``           game, player, item, currency, price
``game.score.flagged``         game, player, board, score, value
``game.analytics.tracked``     game, player, event, props
``game.match.reported``        game, match, players
=============================  ==========================================================

The person of each is the player's person (the match's has none). The
upgrade, an unlocked achievement and a bought item name a timeline title, so
with ``karni.timeline`` installed they are entries on the person's timeline.

Override / escape hatch: subscribe to the events in your own
``listeners.py``. A project that wants another payload declares its own
event and publishes it from a listener of these.
"""

from __future__ import annotations

from karni.events import declare

__all__ = ["FAMILY_EVENTS"]

_GAME = "the game's slug"
_PLAYER = "the player's id"

declare(
    "game.player.joined",
    version=1,
    fields={"player": _PLAYER, "game": "blank: a player is not of one game", "guest": "a guest"},
    person="person",
    describe="A new player: a guest got its token, or an account played for the first time.",
)
declare(
    "game.player.upgraded",
    version=1,
    fields={
        "player": "the account's player's id",
        "user": "the account's id",
        "adopted": "the guest's player became the account's (it had none)",
    },
    person="person",
    timeline={"title": "Game progress kept on the account"},
    describe="A guest signed in, and their progress joined the account's player.",
)
declare(
    "game.achievement.unlocked",
    version=1,
    fields={"game": _GAME, "player": _PLAYER, "achievement": "its key", "title": "its title"},
    person="person",
    timeline={"title": "Achievement unlocked: {title}"},
    describe="The server unlocked an achievement for a player.",
)
declare(
    "game.mission.completed",
    version=1,
    fields={
        "game": _GAME,
        "player": _PLAYER,
        "mission": "its key",
        "title": "its title",
        "period_start": "the day its period started, or blank for a mission done once",
    },
    person="person",
    describe="A player completed a mission (once, or in its day or week).",
)
declare(
    "game.item.bought",
    version=1,
    fields={
        "game": _GAME,
        "player": _PLAYER,
        "item": "its key",
        "currency": "the currency's key",
        "price": "what it cost, a whole number",
    },
    person="person",
    timeline={"title": "Bought {item} in {game}", "body": "{price} {currency}"},
    describe="A player bought an item of the shop with a soft currency.",
)
declare(
    "game.score.flagged",
    version=1,
    fields={
        "game": _GAME,
        "player": _PLAYER,
        "board": "the board's key",
        "score": "the score's id",
        "value": "the score",
    },
    person="person",
    describe="A score is held for staff to review before it counts.",
)
declare(
    "game.analytics.tracked",
    version=1,
    fields={
        "game": _GAME,
        "player": "the player's id, or blank",
        "event": "the event's name, one the game's analytics settings declare",
        "props": "its props, checked against their declared types",
    },
    describe="A game client sent an analytics event the game declares.",
)
declare(
    "game.match.reported",
    version=1,
    fields={"game": _GAME, "match": "the match's id", "players": "the players' ids"},
    describe="A realtime server reported the results of a match.",
)

#: The family events karni-game publishes, by name.
FAMILY_EVENTS: tuple[str, ...] = (
    "game.player.joined",
    "game.player.upgraded",
    "game.achievement.unlocked",
    "game.mission.completed",
    "game.item.bought",
    "game.score.flagged",
    "game.analytics.tracked",
    "game.match.reported",
)
