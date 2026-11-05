"""scripts/benchmark/large_project.py (experimental): a small project, timed, and the comparison.

The CI job runs it on 100 models. Here it runs on 5, so the default suite
proves the whole path (karni new, the spec, karni build, every timed step)
and the comparison with a baseline.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from karni_cli.spec.validate import validate_text

from .conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "benchmark" / "large_project.py"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("karni_benchmark_large_project", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_generated_spec_is_valid_and_spreads_the_entities() -> None:
    bench = _script()
    names = bench.entity_names(100, 10)
    assert len(names) == 10 and sum(len(found) for found in names.values()) == 100
    assert len({name for found in names.values() for name in found}) == 100  # unique names
    report = validate_text(bench.spec_text(100, 10))
    assert report.ok, [issue.render("karni.yaml") for issue in report.issues]
    assert report.spec is not None
    entities = [e for application in report.spec.apps.values() for e in application.entities]
    assert len(entities) == 100
    small = validate_text(bench.spec_text(5, 1))
    assert small.ok and small.spec is not None and list(small.spec.apps) == ["area01"]


def _run(times: dict[str, float], calibration: float = 1.0, models: int = 100) -> dict[str, Any]:
    return {"models": models, "calibration": calibration, "times": times}


def test_compare_scales_by_the_calibration_and_allows_the_slack() -> None:
    bench = _script()
    baseline = _run({"check_cold": 4.0, "check_cached": 2.0, "tests": 50.0})
    assert bench.compare(_run({"check_cold": 6.9, "tests": 75.0}), baseline, 1.5, 1.0) == []
    failures = bench.compare(_run({"check_cached": 4.5, "tests": 40.0}), baseline, 1.5, 1.0)
    assert len(failures) == 1 and failures[0].startswith("check_cached: 4.50s, above 4.00s")
    # a machine twice as slow (its calibration says so) gets twice the time
    slower = _run({"check_cached": 6.5}, calibration=2.0)
    assert bench.compare(slower, baseline, 1.5, 1.0) == []
    other_size = bench.compare(_run({}, models=5), baseline, 1.5, 1.0)
    assert "the baseline has 100 models and this run 5" in other_size[0]


def test_the_stored_baseline_is_a_100_model_run() -> None:
    bench = _script()
    baseline = json.loads(bench.BASELINE.read_text())
    assert baseline["version"] == bench.VERSION and baseline["models"] == 100
    assert set(bench.STEPS) <= set(baseline["times"]) and baseline["calibration"] > 0


def test_a_five_model_project_is_made_and_timed(tmp_path: Path) -> None:
    out = tmp_path / "bench.json"
    baseline = tmp_path / "baseline.json"
    env = {
        k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "DJANGO_SETTINGS_MODULE")
    }
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--models", "5", "--apps", "2", "--out", str(out),
         "--baseline", str(baseline), "--record", "--keep", str(tmp_path / "work")],
        capture_output=True, text=True, env=env, timeout=900, check=False,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    result = json.loads(out.read_text())
    assert result["models"] == 5 and result["apps"] == 2
    assert set(result["times"]) == set(_script().STEPS)
    assert all(seconds > 0 for seconds in result["times"].values())
    assert result["tests"].startswith("8 passed")  # 5 entity tests and the scaffold's 3
    assert json.loads(baseline.read_text()) == result  # --record wrote it
    project = tmp_path / "work" / "bench"
    assert (project / ".karni" / "local" / "check-cache.json").is_file()
    assert not (project / "frontend").exists()
    # the same run compared with itself passes, with a tighter baseline it fails
    tight = {**result, "times": {name: 0.001 for name in result["times"]}}
    baseline.write_text(json.dumps(tight))
    bench = _script()
    assert bench.compare(result, tight, 1.5, 0.0)
    assert bench.compare(result, result, 1.5, 0.0) == []
