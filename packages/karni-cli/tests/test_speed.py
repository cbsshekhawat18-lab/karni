"""scripts/benchmark/speed.py (experimental): the speed budgets and their comparison.

The CI job runs the script for every recipe. Here the default suite checks the
budget arithmetic and the stored baseline: the run itself takes minutes.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from .conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "benchmark" / "speed.py"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("karni_benchmark_speed", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(times: dict[str, float], calibration: float = 1.0) -> dict[str, Any]:
    return {"calibration": calibration, "times": times}


def test_median_is_of_the_runs_not_the_worst() -> None:
    bench = _script()
    assert bench.median([3.0, 100.0, 4.0]) == 4.0
    assert bench.median([1.0, 2.0]) == 1.5


def test_a_time_fails_above_baseline_times_scale_times_threshold_plus_slack() -> None:
    bench = _script()
    baseline = _run({"check_cold": 4.0, "plan": 1.0, "new_shop": 20.0, "new_app": 15.0})
    ok = _run({"check_cold": 6.9, "plan": 2.4, "new_shop": 39.9, "new_app": 24.9})
    assert bench.compare(ok, baseline, 1.5, 1.0, 10.0) == []
    slow = _run({"check_cold": 7.1, "new_shop": 40.1})
    failures = bench.compare(slow, baseline, 1.5, 1.0, 10.0)
    assert [line.split(":")[0] for line in failures] == ["check_cold", "new_shop"]
    assert "above 7.00s" in failures[0] and "above 40.00s" in failures[1]
    # a machine twice as slow (its calibration says so) gets twice the time
    assert (
        bench.compare(_run({"check_cold": 12.9}, calibration=2.0), baseline, 1.5, 1.0, 10.0) == []
    )
    # a step the baseline never had is not compared
    assert bench.compare(_run({"brand_new": 999.0}), baseline, 1.5, 1.0, 10.0) == []


def test_a_rebuild_with_no_change_has_an_absolute_ceiling_whatever_the_machine() -> None:
    bench = _script()
    baseline = _run({"build_nochange": 1.0})
    assert bench.compare(_run({"build_nochange": 4.9}), baseline, 1.5, 1.0, 10.0) == []
    failures = bench.compare(_run({"build_nochange": 5.1}), baseline, 1.5, 1.0, 10.0)
    assert len(failures) == 1 and "ceiling" in failures[0]
    # the machine's speed does not move the ceiling: only --rebuild-ceiling does
    slower = _run({"build_nochange": 5.1}, calibration=3.0)
    assert len(bench.compare(slower, baseline, 1.5, 1.0, 10.0)) == 1
    assert bench.compare(slower, baseline, 1.5, 1.0, 10.0, rebuild_ceiling=8.0) == []


def test_the_stored_baseline_covers_every_step_and_says_where_it_was_recorded() -> None:
    bench = _script()
    baseline = json.loads(bench.BASELINE.read_text())
    assert baseline["version"] == bench.VERSION and baseline["calibration"] > 0
    assert baseline["runs"] >= 3, "a baseline is the median of at least three runs"
    for step in (*bench.QUICK, "new_app", *(f"new_{name}" for name in baseline["recipes"])):
        assert step in baseline["times"], step
    assert baseline["times"]["build_nochange"] < bench.REBUILD_CEILING
    assert "Mac" in baseline["note"] and "load_before" in baseline


def test_every_built_in_recipe_is_in_the_baseline() -> None:
    from karni_cli import recipes as recipes_mod

    bench = _script()
    baseline = json.loads(Path(bench.BASELINE).read_text())
    assert sorted(recipes_mod.load(installed=False).recipes) == sorted(baseline["recipes"])
