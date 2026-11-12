"""Backups: configuration, retention, S3, the schedule, and a real dump and restore.

The PostgreSQL round trip runs when DATABASE_URL names a PostgreSQL server and
its client tools are on PATH (or in KARNI_BACKUP_PG_BIN). CI's PostgreSQL step
has both. It creates and drops its own databases.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import socket
import subprocess
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from karni.deploy import backup
from karni.deploy.backup import BackupError, Config


def _fake_backup(directory: Path, name: str) -> Path:
    path = directory / name
    path.mkdir(parents=True)
    (path / backup.DUMP_FILE).write_bytes(b"dump")
    manifest = {"name": name, "database": {"name": "shop", "bytes": 4}, "media": None}
    (path / backup.MANIFEST_FILE).write_text(json.dumps(manifest))
    return path


def test_the_module_needs_only_the_standard_library() -> None:
    """The backup container runs this file next to pg_dump, without Django or karni."""
    tree = ast.parse(Path(backup.__file__).read_text())
    top_level: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            top_level.add(node.module.split(".")[0])
    assert top_level <= {"__future__", *__import__("sys").stdlib_module_names}


def test_config_from_the_environment() -> None:
    config = Config.from_env(
        {
            "DATABASE_URL": "postgres://u:p@db/shop",
            "KARNI_BACKUP_DIR": "/srv/backups",
            "KARNI_BACKUP_KEEP": "3",
            "KARNI_BACKUP_INTERVAL_HOURS": "6",
            "MEDIA_ROOT": "/data/media",
            "KARNI_BACKUP_S3_BUCKET": "bucket",
            "KARNI_BACKUP_S3_PREFIX": "/site",
        }
    )
    assert config.directory == Path("/srv/backups")
    assert (config.keep, config.interval_hours) == (3, 6.0)
    assert config.media_root == Path("/data/media")
    assert config.s3_prefix == "site/"
    assert Config.from_env({"KARNI_BACKUP_MEDIA_ROOT": ""}).media_root is None
    with pytest.raises(BackupError, match="KARNI_BACKUP_KEEP=0 is below 1"):
        Config.from_env({"KARNI_BACKUP_KEEP": "0"})
    with pytest.raises(BackupError, match="not a number"):
        Config.from_env({"KARNI_BACKUP_INTERVAL_HOURS": "daily"})


def test_the_password_never_reaches_the_command_line() -> None:
    conn = backup.connection(
        "postgis://karni:s%40cret@db:5432/shop?sslmode=require&conn_max_age=60"
    )
    assert conn.url == "postgresql://karni@db:5432/shop?sslmode=require"
    assert conn.env == {"PGPASSWORD": "s@cret"}
    assert conn.database == "shop"
    for bad in ("", "sqlite:///db.sqlite3", "postgres://db:5432/"):
        with pytest.raises(BackupError):
            backup.connection(bad)


def test_retention_keeps_the_newest(tmp_path: Path) -> None:
    for day in range(1, 6):
        _fake_backup(tmp_path, f"202610{day:02d}T030000Z")
    (tmp_path / "not-a-backup").mkdir()
    removed = backup.prune(Config(directory=tmp_path, keep=2))
    assert removed == ["20261003T030000Z", "20261002T030000Z", "20261001T030000Z"]
    assert [p.name for p in backup.list_backups(tmp_path)] == [
        "20261005T030000Z",
        "20261004T030000Z",
    ]
    assert (tmp_path / "not-a-backup").is_dir()


def test_the_schedule_and_the_health_check(tmp_path: Path) -> None:
    config = Config(directory=tmp_path, interval_hours=24)
    now = datetime(2026, 10, 26, 12, tzinfo=UTC)
    assert backup.seconds_until_due(config, now=now) == 0
    assert backup.health(config, now=now)[0]  # nothing ran yet
    _fake_backup(tmp_path, backup.backup_name(now - timedelta(hours=20)))
    assert backup.seconds_until_due(config, now=now) == pytest.approx(4 * 3600)
    backup.write_status(config, False, "pg_dump failed: no route to host")
    healthy, detail = backup.health(config)
    assert not healthy and "no route to host" in detail
    backup.write_status(config, True, "20261026T030000Z")
    assert backup.health(config)[0]
    assert not backup.health(config, now=datetime.now(UTC) + timedelta(days=3))[0]


def test_loop_backs_up_when_due_and_sleeps_otherwise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config(directory=tmp_path, interval_hours=1)
    made: list[str] = []

    def fake_run(config: Config, **kwargs: Any) -> Path:
        name = backup.backup_name(datetime.now(UTC) - timedelta(minutes=len(made)))
        made.append(name)
        return _fake_backup(tmp_path, name)

    slept: list[float] = []
    monkeypatch.setattr(backup, "run_backup", fake_run)
    monkeypatch.setattr(backup.signal, "signal", lambda *args: None)
    backup.loop(config, sleep=slept.append, runs=1)
    assert len(made) == 1 and slept == []

    def sleep_until_due(seconds: float) -> None:
        slept.append(seconds)
        _due_now(tmp_path)

    backup.loop(config, sleep=sleep_until_due, runs=1)
    assert len(made) == 2 and 0 < slept[0] <= 3600


def _due_now(directory: Path) -> None:
    for path in backup.list_backups(directory):
        shutil.rmtree(path)


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def upload_file(self, Filename: str, Bucket: str, Key: str) -> None:  # noqa: N803
        self.objects[Key] = Path(Filename).read_bytes()

    def download_file(self, Bucket: str, Key: str, Filename: str) -> None:  # noqa: N803
        Path(Filename).write_bytes(self.objects[Key])

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        keys = sorted(k for k in self.objects if k.startswith(kwargs["Prefix"]))
        start = int(kwargs.get("ContinuationToken") or 0)
        page = keys[start : start + 2]  # tiny pages exercise the continuation
        more = start + 2 < len(keys)
        return {
            "Contents": [{"Key": k} for k in page],
            "IsTruncated": more,
            "NextContinuationToken": str(start + 2) if more else None,
        }

    def delete_objects(self, **kwargs: Any) -> dict[str, Any]:
        for item in kwargs["Delete"]["Objects"]:
            self.objects.pop(item["Key"], None)
        return {}


def test_s3_upload_retention_and_fetch(tmp_path: Path) -> None:
    s3 = FakeS3()
    config = Config(directory=tmp_path / "local", keep=2, s3_bucket="b", s3_prefix="site/")
    for day in range(1, 4):
        backup.upload(config, _fake_backup(config.directory, f"202610{day:02d}T030000Z"), s3)
    assert backup.s3_backups(config, s3) == [
        "20261003T030000Z",
        "20261002T030000Z",
        "20261001T030000Z",
    ]
    backup.prune(config, client=s3)
    assert backup.s3_backups(config, s3) == ["20261003T030000Z", "20261002T030000Z"]
    assert not any("20261001" in key for key in s3.objects)
    shutil.rmtree(config.directory)
    fetched = backup.find_backup(config, "latest", client=s3)
    assert fetched.name == "20261003T030000Z"
    assert (fetched / backup.DUMP_FILE).read_bytes() == b"dump"


# PostgreSQL round trip


def _postgres_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "")
    return url if urlsplit(url).scheme in backup.POSTGRES_SCHEMES else None


def _pg_bin() -> Path | None:
    configured = os.environ.get("KARNI_BACKUP_PG_BIN")
    return Path(configured) if configured else None


def _tools_present() -> bool:
    folder = _pg_bin()
    names = ("pg_dump", "pg_restore", "psql", "createdb")
    if folder is not None:
        return all((folder / name).exists() for name in names)
    return all(shutil.which(name) for name in names)


def _reachable(url: str) -> bool:
    """Whether a server accepts TCP connections at the URL (a unix socket: assume so)."""
    parts = urlsplit(url)
    if not parts.hostname or parts.hostname.startswith("/"):
        return True
    try:
        with socket.create_connection((parts.hostname, parts.port or 5432), timeout=3):
            return True
    except OSError:
        return False


@pytest.fixture
def server() -> Iterator[tuple[str, list[str]]]:
    url = _postgres_url()
    if url is None or not _tools_present():
        pytest.skip(
            "needs DATABASE_URL=postgres://... and the PostgreSQL client tools "
            "(pg_dump, pg_restore, psql, createdb) on PATH or in KARNI_BACKUP_PG_BIN"
        )
    if not _reachable(url):
        pytest.skip("needs a PostgreSQL server listening at DATABASE_URL's host and port")
    config = Config(pg_bin=_pg_bin())
    # The maintenance database: DATABASE_URL's own database need not exist.
    maintenance = backup.connection(backup.with_database(url, "postgres"))
    client = backup._postgres(
        config, maintenance, [backup._tool(config, "pg_dump"), "--version"], "version"
    )
    server_version = backup._postgres(
        config,
        maintenance,
        [
            backup._tool(config, "psql"),
            "--no-psqlrc",
            "-Atc",
            "show server_version_num",
            maintenance.url,
        ],
        "server version",
    )
    client_major = int(re.findall(r"\d+", client)[0])
    if client_major > int(server_version.strip()) // 10000:
        pytest.skip(
            f"{client.strip()} is newer than the server: set KARNI_BACKUP_PG_BIN to the "
            "server's major version"
        )
    created: list[str] = []
    yield url, created
    maintenance = backup.connection(backup.with_database(url, "postgres"))
    for name in created:
        subprocess.run(
            [
                backup._tool(config, "psql"),
                "--no-psqlrc",
                "-q",
                "-c",
                f'drop database if exists "{name}"',
                maintenance.url,
            ],
            env={**os.environ, **maintenance.env},
            check=False,
            capture_output=True,
        )


def _psql(config: Config, url: str, sql: str) -> None:
    conn = backup.connection(url)
    backup._postgres(
        config, conn, [backup._tool(config, "psql"), "--no-psqlrc", "-q", "-c", sql, conn.url], sql
    )


def test_dump_restore_and_compare_row_counts(server: tuple[str, list[str]], tmp_path: Path) -> None:
    url, created = server
    tag = uuid.uuid4().hex[:8]
    source = backup.with_database(url, f"karni_backup_{tag}")
    target = backup.with_database(url, f"karni_restored_{tag}")
    created += [f"karni_backup_{tag}", f"karni_restored_{tag}"]
    config = Config(
        database_url=source,
        directory=tmp_path / "backups",
        keep=2,
        media_root=tmp_path / "media",
        pg_bin=_pg_bin(),
    )
    backup.create_database(config, source)
    _psql(
        config,
        source,
        "create table shop_item (id serial primary key, name text not null);"
        "insert into shop_item (name) select 'item ' || n from generate_series(1, 120) n;"
        "create table shop_order (id serial primary key, item_id int references shop_item);"
        "insert into shop_order (item_id) select n from generate_series(1, 40) n;",
    )
    (tmp_path / "media" / "items").mkdir(parents=True)
    (tmp_path / "media" / "items" / "photo.jpg").write_bytes(b"\xff\xd8 not really a jpeg")

    names = []
    for minute in range(3):
        moment = datetime(2026, 10, 26, 3, minute, tzinfo=UTC)
        names.append(backup.run_backup(config, now=moment).name)
    kept = [path.name for path in backup.list_backups(config.directory)]
    assert kept == names[:0:-1]  # the newest two
    newest = config.directory / kept[0]
    assert (newest / backup.DUMP_FILE).stat().st_size > 0
    manifest = json.loads((newest / backup.MANIFEST_FILE).read_text())
    assert manifest["media"]["files"] == 1

    restored_media = tmp_path / "restored-media"
    backup.restore(config, newest, target, create=True, media_root=restored_media)
    counts = backup.row_counts(config, source)
    assert counts == {"public.shop_item": 120, "public.shop_order": 40}
    assert backup.row_counts(config, target) == counts
    assert (restored_media / "items" / "photo.jpg").read_bytes().startswith(b"\xff\xd8")

    # A second restore over the same database needs --clean, and gives the same rows.
    backup.restore(config, newest, target, clean=True)
    assert backup.row_counts(config, target) == counts
    assert backup.main(["counts", "--database-url", source, "--against", target]) == 0


def test_restoring_over_the_live_database_must_say_so(tmp_path: Path) -> None:
    env = {"DATABASE_URL": "postgres://u@db/shop", "KARNI_BACKUP_DIR": str(tmp_path)}
    assert backup.main(["restore", "latest"], environ=env) == 1  # no target, no --clean
    # With --clean the target is DATABASE_URL; here the backup is what is missing.
    assert backup.main(["restore", "latest", "--clean"], environ=env) == 1


def test_hand_over_is_a_no_op_without_root(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.txt").write_text("x")
    backup.hand_over(tmp_path, [tmp_path / "a" / "b.txt"])
    assert (tmp_path / "a" / "b.txt").read_text() == "x"
