"""Statistics over runs: the median and the spread, no more."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Spread:
    n: int
    median: float
    minimum: float
    maximum: float
    q1: float
    q3: float

    @property
    def iqr(self) -> float:
        return self.q3 - self.q1


def spread(values: Sequence[float]) -> Spread | None:
    """The median, minimum, maximum and quartiles of ``values`` (None when there are none).

    Quartiles use the inclusive method, so a few runs give quartiles inside the data.
    """
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        q1 = q3 = ordered[0]
    else:
        q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    return Spread(
        n=len(ordered),
        median=statistics.median(ordered),
        minimum=ordered[0],
        maximum=ordered[-1],
        q1=q1,
        q3=q3,
    )
