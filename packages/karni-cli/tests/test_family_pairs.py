"""Every pair of family parts, built together: the nightly pairs job (docs/family.md).

``karni new --recipe a --recipe b`` for each pair of the parts below runs the migrations, the seed,
the project's tests (both parts' own among them) and ``karni check`` (the architecture rules K315
and K315 too), and then ``karni check`` is run once more on the built project. A connection that
leans on a third part by accident, a role or a route two parts share, or one part naming the
other, fails here and not in a customer's project.

Run it with ``pytest -m recipes tests/test_family_pairs.py``. CI runs it nightly and on demand
(the ``pairs`` job), not on every push: each pair is a full build.

``PARTS`` grows with the family: the shop joins it after its branch is merged. The first test fails
when a recipe that has connections is missing from it, so a new part cannot be forgotten.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from karni_cli.commands import check as check_mod

from . import test_family_build
from .test_family_build import _new, _spec
from .test_family_matrix import _recipe_dirs, declared_connections

#: The recipes that are parts of the family (they declare connections). The shop joins after the merge.
PARTS = ("booking", "crm", "visits")
PAIRS = list(itertools.combinations(PARTS, 2))

family = test_family_build.family


def test_every_part_with_connections_is_in_the_pairs() -> None:
    with_connections = {
        name for name, folder in _recipe_dirs().items() if declared_connections(folder)
    }
    assert with_connections == set(PARTS), (
        "PARTS in tests/test_family_pairs.py lists the recipes that declare connections: "
        f"{sorted(with_connections)}"
    )
    assert len(PAIRS) == len(PARTS) * (len(PARTS) - 1) // 2


@pytest.mark.recipes
@pytest.mark.parametrize(("first", "second"), PAIRS, ids=[f"{a}+{b}" for a, b in PAIRS])
def test_a_pair_builds_and_checks_green(
    family: Path, monkeypatch: pytest.MonkeyPatch, first: str, second: str
) -> None:
    root = _new(family, monkeypatch, f"pair_{first}_{second}", first, second)
    spec = _spec(root)
    assert spec["app"]["recipes"] == [first, second]
    assert len(spec["apps"]) == 2
    monkeypatch.chdir(root)
    passed, output = check_mod.run_checks(root)
    assert passed, output


def test_the_workflow_runs_exactly_these_pairs_nightly_and_on_demand() -> None:
    import yaml

    path = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "family-pairs.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = workflow[True]  # YAML reads the key `on` as True
    assert set(triggers) == {"schedule", "workflow_dispatch"}  # never on a push
    assert triggers["schedule"][0]["cron"]
    assert workflow["jobs"]["pairs"]["strategy"]["matrix"]["pair"] == [f"{a}+{b}" for a, b in PAIRS]
    ci = yaml.safe_load((path.parent / "ci.yml").read_text(encoding="utf-8"))
    assert "pairs" not in ci["jobs"]  # the push workflow does not build every pair
