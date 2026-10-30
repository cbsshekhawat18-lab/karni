"""karni check's cache (experimental): a hit, a miss after an edit, --changed, invalidation."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

import karni
from karni.testing import architecture, checkcache, duplication
from karni.testing.checkcache import CheckCache


def _counter() -> tuple[list[int], object]:
    calls: list[int] = []

    def compute() -> list[str]:
        calls.append(1)
        return [f"found {len(calls)}"]

    return calls, compute


def test_an_unchanged_file_is_a_hit_and_an_edit_a_miss(tmp_path: Path) -> None:
    source = tmp_path / "shop" / "models.py"
    source.parent.mkdir()
    source.write_text("x = 1\n")
    calls, compute = _counter()
    first = CheckCache.load(tmp_path, key="k")
    assert first.per_file("raw-sql", source, compute) == ["found 1"]
    assert first.save() and (tmp_path / ".karni" / "local" / ".gitignore").is_file()

    again = CheckCache.load(tmp_path, key="k")
    assert again.per_file("raw-sql", source, compute) == ["found 1"]
    assert (again.hits, again.misses, len(calls)) == (1, 0, 1)

    source.write_text("x = 2\n")
    edited = CheckCache.load(tmp_path, key="k")
    assert edited.per_file("raw-sql", source, compute) == ["found 2"]
    assert (edited.hits, edited.misses) == (0, 1)
    assert edited.summary() == "check cache: 0 of 1 file results reused"


def test_another_fingerprint_or_format_ignores_the_cache(tmp_path: Path) -> None:
    source = tmp_path / "a.py"
    source.write_text("pass\n")
    calls, compute = _counter()
    cache = CheckCache.load(tmp_path, key="karni 0.4")
    cache.per_file("duplicate", source, compute)
    cache.save()
    assert CheckCache.load(tmp_path, key="karni 0.5").per_file("duplicate", source, compute)
    assert len(calls) == 2
    (tmp_path / checkcache.CACHE_FILE).write_text("not json")
    assert CheckCache.load(tmp_path, key="karni 0.4").per_file("duplicate", source, compute)
    assert len(calls) == 3


def test_the_fingerprint_follows_the_version_and_the_settings(monkeypatch, settings) -> None:
    before = checkcache.fingerprint()
    assert checkcache.fingerprint() == before
    monkeypatch.setattr(karni, "__version__", "99.0.0")
    assert checkcache.fingerprint() != before
    monkeypatch.undo()
    settings.KARNI_ARCHITECTURE = {"sql_allowed": ["*/reports/*"]}
    assert checkcache.fingerprint() != before


def test_a_changed_extra_input_drops_that_check(tmp_path: Path) -> None:
    source = tmp_path / "a.py"
    source.write_text("pass\n")
    calls, compute = _counter()
    cache = CheckCache.load(tmp_path, key="k")
    cache.extra("audited", "Price")
    cache.per_file("audited", source, compute)
    cache.save()
    again = CheckCache.load(tmp_path, key="k")
    again.extra("audited", "Price,Order")
    again.per_file("audited", source, compute)
    assert len(calls) == 2


def test_changed_narrows_what_is_read_and_reported(tmp_path: Path) -> None:
    cache = CheckCache.load(tmp_path, key="k", changed=["shop/models.py"])
    assert cache.wanted(tmp_path / "shop" / "models.py")
    assert not cache.wanted(tmp_path / "shop" / "views.py")
    assert cache.reports("shop/models.py:12") and not cache.reports("shop/views.py:3")
    assert not cache.reports("shop.Product")  # a finding with no file is left out
    assert CheckCache.load(tmp_path, key="k").reports("shop.Product")


def test_off_computes_everything_and_writes_nothing(tmp_path: Path) -> None:
    source = tmp_path / "a.py"
    source.write_text("pass\n")
    calls, compute = _counter()
    cache = CheckCache.load(tmp_path, enabled=False)
    cache.per_file("raw-sql", source, compute)
    cache.per_file("raw-sql", source, compute)
    assert len(calls) == 2 and cache.save() and not cache.path.exists()
    assert cache.summary() == "check cache: off"


def test_the_rules_reuse_the_cache_and_find_the_same(tmp_path: Path) -> None:
    plain = sorted(architecture.run_checks()) + sorted(duplication.run_check())
    cache = CheckCache.load(tmp_path, key="k", file=tmp_path / "cache.json")
    with checkcache.using(cache):
        cold = sorted(architecture.run_checks()) + sorted(duplication.run_check())
    assert cold == plain and cache.misses > 0 and cache.hits == 0
    cache.save()
    warm = CheckCache.load(tmp_path, key="k", file=tmp_path / "cache.json")
    with checkcache.using(warm):
        again = sorted(architecture.run_checks()) + sorted(duplication.run_check())
    assert again == plain and warm.misses == 0 and warm.hits == cache.misses


@pytest.mark.django_db
def test_karni_check_keeps_its_cache_where_the_setting_says(settings, tmp_path: Path) -> None:
    settings.KARNI_CHECK_CACHE = str(tmp_path / "check-cache.json")
    out = StringIO()
    call_command("karni_check", stdout=out, stderr=StringIO())
    assert "check cache: 0 of " in out.getvalue() and "backend checks: ok" in out.getvalue()
    stored = json.loads((tmp_path / "check-cache.json").read_text())
    assert stored["format"] == checkcache.FORMAT and stored["checks"]
    out = StringIO()
    call_command("karni_check", stdout=out, stderr=StringIO())
    reused = out.getvalue().split("check cache: ", 1)[1].split(" file results")[0]
    hits, total = reused.split(" of ")
    assert hits == total and int(total) > 0
    out = StringIO()
    call_command("karni_check", "--no-cache", stdout=out, stderr=StringIO())
    assert "check cache" not in out.getvalue() and "backend checks: ok" in out.getvalue()
    out = StringIO()
    call_command("karni_check", "--changed", "tests/testapp/models.py", stdout=out)
    assert "1 changed file(s)" in out.getvalue()
