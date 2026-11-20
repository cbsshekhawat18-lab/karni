"""Experimental. Achievements and missions, unlocked by the server from the counters a game reports.

A game reports progress as counters (``coins_collected``, ``levels_done``)
with amounts. :func:`report` refuses a counter no active achievement or
mission of the game counts, and an amount outside 1 to the game's
``max_progress_step`` (``GAME024``), so a client cannot invent a counter or
jump to a goal. It adds the amounts to the counter over all time and in the
day and week when a mission counts per day or week, then unlocks each
achievement whose counter reached its goal, and completes each mission
reached in its period, granting their rewards. Each unlock publishes
``game.achievement.unlocked`` and lands in the account's inbox (with
``karni.notify``), each completion ``game.mission.completed``.

Override / escape hatch: an achievement and a mission are rows staff edit; a
project's own rule (a combination of counters) is a listener of
``game.achievement.unlocked`` or its own :func:`report` caller.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.apps import apps
from django.db import IntegrityError, router, transaction
from django.db.models import F

from karni_game import clock, rewards
from karni_game.errors import game_error
from karni_game.models import (
    Achievement,
    Completion,
    Game,
    Mission,
    Player,
    Progress,
    Unlock,
)

__all__ = ["achievements", "counters", "missions", "report"]

#: The most events one report may hold.
MAX_EVENTS = 20


def counters(game: Game) -> dict[str, set[str]]:
    """The counters the game's active achievements and missions count, with the periods each
    is counted in (``all`` always, ``daily`` or ``weekly`` for a mission of that period)."""
    found: dict[str, set[str]] = defaultdict(lambda: {"all"})
    for counter in Achievement.objects.filter(game=game, is_active=True).values_list(
        "counter", flat=True
    ):
        found[counter].add("all")
    for counter, period in Mission.objects.filter(game=game, is_active=True).values_list(
        "counter", "period"
    ):
        found[counter].add(period if period in ("daily", "weekly") else "all")
    return dict(found)


def _start(game: Game, period: str) -> Any:
    return clock.period_start(game, period)


def _add(player: Player, game: Game, counter: str, period: str, amount: int) -> None:
    start = _start(game, period)
    rows = Progress.objects.filter(
        player=player, game=game, counter=counter, period=period, period_start=start
    )
    if rows.update(value=F("value") + amount):
        return
    try:
        with transaction.atomic(using=router.db_for_write(Progress)):
            Progress.objects.create(
                player=player,
                game=game,
                counter=counter,
                period=period,
                period_start=start,
                value=amount,
            )
    except IntegrityError:  # another report made the row first
        rows.update(value=F("value") + amount)


def _value(player: Player, game: Game, counter: str, period: str) -> int:
    found = (
        Progress.objects.filter(
            player=player,
            game=game,
            counter=counter,
            period=period,
            period_start=_start(game, period),
        )
        .values_list("value", flat=True)
        .first()
    )
    return int(found or 0)


def _granted(player: Player, reward: Any, reference: str) -> dict[str, Any] | None:
    if reward is None or not reward.is_active:
        return None
    return rewards.grant(player, reward, source="server", reference=reference).change.as_dict()


def _notify_unlock(player: Player, achievement: Achievement) -> None:
    if not apps.is_installed("karni.notify") or player.person.user_id is None:
        return
    person_id = player.person_id
    context = {
        "game": {"title": achievement.game.title},
        "achievement": {"title": achievement.title, "description": achievement.description},
    }

    def send() -> None:
        from karni import notify
        from karni.people.models import Person

        person = Person.objects.filter(pk=person_id).first()
        if person is not None:
            notify.send("game.achievement_unlocked", to=[person], context=context)

    transaction.on_commit(send)


def _unlock(player: Player, game: Game, touched: set[str]) -> list[dict[str, Any]]:
    from karni.events import publish

    done: list[dict[str, Any]] = []
    rows = Achievement.objects.filter(game=game, is_active=True, counter__in=touched)
    rows = rows.exclude(unlocks__player=player).select_related("reward__currency")
    for achievement in rows:
        achievement.game = game
        if _value(player, game, achievement.counter, "all") < achievement.goal:
            continue
        try:
            with transaction.atomic(using=router.db_for_write(Unlock)):
                Unlock.objects.create(player=player, achievement=achievement)
        except IntegrityError:  # another report unlocked it
            continue
        granted = _granted(player, achievement.reward, achievement.key)
        publish(
            "game.achievement.unlocked",
            subject=achievement,
            person=player.person_id,
            game=game.slug,
            player=str(player.pk),
            achievement=achievement.key,
            title=achievement.title,
        )
        _notify_unlock(player, achievement)
        found: dict[str, Any] = {"key": achievement.key, "title": achievement.title}
        if granted is not None:
            found["granted"] = granted
        done.append(found)
    return done


def _complete(player: Player, game: Game, touched: set[str]) -> list[dict[str, Any]]:
    from karni.events import publish

    done: list[dict[str, Any]] = []
    rows = Mission.objects.filter(game=game, is_active=True, counter__in=touched)
    for mission in rows.select_related("reward__currency"):
        period = mission.period if mission.period in ("daily", "weekly") else "all"
        start = _start(game, period)
        if _value(player, game, mission.counter, period) < mission.goal:
            continue
        try:
            with transaction.atomic(using=router.db_for_write(Completion)):
                Completion.objects.create(player=player, mission=mission, period_start=start)
        except IntegrityError:  # completed already in this period
            continue
        granted = _granted(player, mission.reward, mission.key)
        publish(
            "game.mission.completed",
            subject=mission,
            person=player.person_id,
            game=game.slug,
            player=str(player.pk),
            mission=mission.key,
            title=mission.title,
            period_start="" if period == "all" else start.isoformat(),
        )
        found: dict[str, Any] = {"key": mission.key, "title": mission.title}
        if granted is not None:
            found["granted"] = granted
        done.append(found)
    return done


def report(player: Player, game: Game, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Add the events' amounts; unlock and complete what they reached."""
    counted = counters(game)
    step = game.options().max_progress_step
    if len(events) > MAX_EVENTS:
        raise game_error("GAME024", f"A report holds at most {MAX_EVENTS} events.")
    for index, event in enumerate(events):
        counter, amount = str(event.get("counter", "")), event.get("amount")
        if counter not in counted:
            raise game_error(
                "GAME024",
                f"No achievement or mission of {game.slug} counts {counter!r}.",
                index=index,
            )
        if not isinstance(amount, int) or isinstance(amount, bool) or not 1 <= amount <= step:
            raise game_error(
                "GAME024",
                f"A progress amount is a whole number from 1 to {step}, not {amount!r}.",
                index=index,
            )
    touched: set[str] = set()
    with transaction.atomic(using=router.db_for_write(Progress)):
        for event in events:
            counter, amount = str(event["counter"]), int(event["amount"])
            for period in counted[counter]:
                _add(player, game, counter, period, amount)
            touched.add(counter)
        unlocked = _unlock(player, game, touched)
        completed = _complete(player, game, touched)
    return {
        "counters": {name: _value(player, game, name, "all") for name in sorted(touched)},
        "unlocked": unlocked,
        "completed": completed,
    }


def achievements(player: Player | None, game: Game) -> list[dict[str, Any]]:
    """The game's achievements with the player's progress and unlocks."""
    unlocked: dict[Any, Any] = {}
    if player is not None:
        unlocked = dict(
            Unlock.objects.filter(player=player, achievement__game=game).values_list(
                "achievement_id", "created_at"
            )
        )
    rows = []
    for row in Achievement.objects.filter(game=game, is_active=True):
        at = unlocked.get(row.pk)
        secret = row.hidden and at is None
        rows.append(
            {
                "key": row.key,
                "title": "" if secret else row.title,
                "description": "" if secret else row.description,
                "hidden": row.hidden,
                "counter": row.counter,
                "goal": row.goal,
                "progress": _value(player, game, row.counter, "all") if player else 0,
                "unlocked_at": at,
            }
        )
    return rows


def missions(player: Player | None, game: Game) -> list[dict[str, Any]]:
    """The game's missions with the player's progress in each one's period now."""
    rows = []
    for row in Mission.objects.filter(game=game, is_active=True).select_related("reward__currency"):
        period = row.period if row.period in ("daily", "weekly") else "all"
        start = _start(game, period)
        done = None
        if player is not None:
            done = (
                Completion.objects.filter(player=player, mission=row, period_start=start)
                .values_list("created_at", flat=True)
                .first()
            )
        reward = row.reward
        rows.append(
            {
                "key": row.key,
                "title": row.title,
                "description": row.description,
                "period": row.period,
                "period_start": None if period == "all" else start.isoformat(),
                "counter": row.counter,
                "goal": row.goal,
                "progress": _value(player, game, row.counter, period) if player else 0,
                "completed_at": done,
                "reward": (
                    {"currency": reward.currency.key, "amount": reward.amount} if reward else None
                ),
            }
        )
    return rows
