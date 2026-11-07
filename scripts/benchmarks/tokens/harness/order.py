"""The order of the runs: conditions alternate, so the time of day touches both alike."""

from __future__ import annotations

from collections.abc import Sequence

Run = tuple[str, str, int]  # (task, condition, index from 1)


def plan(tasks: Sequence[str], conditions: Sequence[str], n: int) -> list[Run]:
    """Round by round: run 1 of every task with each condition in turn, then run 2, and so on.

    With the conditions ``plain, karni`` the order is plain, karni, plain, karni... and a
    stop at any point leaves every task and condition with the same number of runs, give or
    take one round.
    """
    return [
        (task, condition, index)
        for index in range(1, n + 1)
        for task in tasks
        for condition in conditions
    ]
