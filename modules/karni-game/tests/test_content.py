"""A game is declared on the server in a content file, loaded with karni load (natural keys)."""

from __future__ import annotations

from pathlib import Path

from karni.transfer.loading import load_content

from karni_game.models import Achievement, Board, ConfigValue, Game, Item, Mission, Reward

CONTENT = Path(__file__).with_name("content") / "game.yaml"


def test_a_content_file_declares_a_game_and_loads_twice_the_same(db: None) -> None:
    load_content(CONTENT)
    game = Game.objects.get(slug="block-hopper")
    assert game.options().analytics["level_done"] == {"level": "int", "ms": "int"}
    assert set(Board.objects.filter(game=game).values_list("key", flat=True)) == {"high", "daily"}
    reward = Reward.objects.get(key="collector")
    assert (reward.game_id, reward.currency.key) == (game.pk, "coins")
    assert Achievement.objects.get(key="collector").reward_id == reward.pk
    assert Achievement.objects.get(key="first-jump").game_id == game.pk
    assert Mission.objects.get(key="three-levels").game_id == game.pk
    assert Item.objects.get(key="red-cap").game_id == game.pk
    assert ConfigValue.objects.get(key="night_mode").flag is True
    rows = (Board.objects.count(), Reward.objects.count(), Achievement.objects.count())
    load_content(CONTENT)
    assert (Board.objects.count(), Reward.objects.count(), Achievement.objects.count()) == rows
