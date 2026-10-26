"""Database and media backups with retention, and the restore: ``python -m karni.deploy.backup``.

The ``backup`` service of ``docker-compose.prod.yml`` runs this file next to
``pg_dump`` (the scaffold's Dockerfile, target ``backup``, copies it into a
``postgres`` image of the database's major version). It is standard library
only, so it runs without Django or the project. boto3 is imported only when
an S3 bucket is configured. docs/deploy.md has the procedures.

    karni-backup run                       # one backup now, then retention
    karni-backup loop                      # every KARNI_BACKUP_INTERVAL_HOURS (the service)
    karni-backup list                      # the backups, newest first
    karni-backup restore latest --database-url postgres://.../restored --create
    karni-backup restore latest --clean --media-root /data/media   # over the live site
    karni-backup counts --database-url postgres://.../live --against postgres://.../restored
    karni-backup check                     # health: the last run did not fail

A backup is a directory named by its UTC time, ``20261026T030000Z``, holding
``database.dump`` (``pg_dump --format=custom``), ``media.tar.gz`` (the media
root, when it has files) and ``manifest.json``. It is written under a hidden
``.<name>.partial`` name and renamed when complete, so a backup that failed
half way is never listed or restored.

Settings, all environment variables:

``DATABASE_URL``
    The database to dump (``postgres://``, ``postgresql://``, ``pgsql://`` or
    ``postgis://``). The password is passed to ``pg_dump`` in ``PGPASSWORD``,
    never on its command line.
``KARNI_BACKUP_DIR``
    Where backups are written (default ``/backups``, a named volume).
``KARNI_BACKUP_KEEP``
    How many backups are kept, locally and in the bucket (default 7).
``KARNI_BACKUP_INTERVAL_HOURS``
    Hours between backups in ``loop`` (default 24). A backup runs at start
    when the newest one is older than that.
``KARNI_BACKUP_MEDIA_ROOT``
    The media directory to archive (default ``MEDIA_ROOT``, else
    ``/data/media``). Empty turns the media archive off.
``KARNI_BACKUP_S3_BUCKET`` and ``KARNI_BACKUP_S3_PREFIX``
    Also upload each backup to this bucket under the prefix (default
    ``backups/``). Credentials and endpoint come from ``AWS_ACCESS_KEY_ID``,
    ``AWS_SECRET_ACCESS_KEY``, ``AWS_S3_ENDPOINT_URL`` and ``AWS_S3_REGION_NAME``.
``KARNI_BACKUP_PG_BIN``
    The directory holding ``pg_dump``, ``pg_restore``, ``psql`` and
    ``createdb`` (default: found on ``PATH``). Its major version must be at
    least the server's.

Override / escape hatch: every function takes its configuration as a
:class:`Config`, and :func:`run_backup` takes a ``client`` for S3, so another
scheduler (cron, a Celery task) can call it. A failure exits with status 1 and
an ``E521`` line.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType
from typing import Any, Protocol
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

__all__ = [
    "BackupError",
    "Config",
    "list_backups",
    "main",
    "prune",
    "restore",
    "row_counts",
    "run_backup",
]

#: The error code every failure carries: ``karni explain E521``.
CODE = "E521"
NAME_FORMAT = "%Y%m%dT%H%M%SZ"
NAME_PATTERN = re.compile(r"^\d{8}T\d{6}Z$")
DUMP_FILE = "database.dump"
MEDIA_FILE = "media.tar.gz"
MANIFEST_FILE = "manifest.json"
STATUS_FILE = ".status.json"
FORMAT_VERSION = 1

#: URL schemes django-environ accepts for PostgreSQL, all spoken by libpq as postgresql://.
POSTGRES_SCHEMES = frozenset({"postgres", "postgresql", "pgsql", "postgis", "psql"})
#: libpq connection parameters a DATABASE_URL query may carry. Others (django-environ's
#: own, such as conn_max_age) are dropped before the URL reaches pg_dump.
LIBPQ_PARAMETERS = frozenset(
    {
        "application_name",
        "channel_binding",
        "connect_timeout",
        "gssencmode",
        "keepalives",
        "keepalives_count",
        "keepalives_idle",
        "keepalives_interval",
        "options",
        "passfile",
        "service",
        "sslcert",
        "sslcrl",
        "sslkey",
        "sslmode",
        "sslnegotiation",
        "sslpassword",
        "sslrootcert",
        "target_session_attrs",
    }
)


class BackupError(Exception):
    """A backup, restore or count failed; the message says what and how to fix it."""


class S3Client(Protocol):
    """The four boto3 S3 client methods this module calls."""

    def upload_file(self, Filename: str, Bucket: str, Key: str) -> None: ...  # noqa: N803

    def download_file(self, Bucket: str, Key: str, Filename: str) -> None: ...  # noqa: N803

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]: ...

    def delete_objects(self, **kwargs: Any) -> dict[str, Any]: ...


def _env_int(environ: Mapping[str, str], name: str, default: int, minimum: int) -> int:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise BackupError(f"{name}={raw!r} is not a whole number.") from None
    if value < minimum:
        raise BackupError(f"{name}={value} is below {minimum}.")
    return value


def _env_float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise BackupError(f"{name}={raw!r} is not a number.") from None
    if value <= 0:
        raise BackupError(f"{name}={value} must be above 0.")
    return value


@dataclass(frozen=True)
class Config:
    """Everything a backup needs, read from the environment by :meth:`from_env`."""

    database_url: str = ""
    directory: Path = Path("/backups")
    keep: int = 7
    interval_hours: float = 24.0
    media_root: Path | None = Path("/data/media")
    s3_bucket: str = ""
    s3_prefix: str = "backups/"
    s3_endpoint: str = ""
    s3_region: str = ""
    pg_bin: Path | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Config:
        env = os.environ if environ is None else environ
        media = env.get("KARNI_BACKUP_MEDIA_ROOT")
        if media is None:
            media = env.get("MEDIA_ROOT", "/data/media")
        prefix = env.get("KARNI_BACKUP_S3_PREFIX", "backups/").strip().lstrip("/")
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        pg_bin = env.get("KARNI_BACKUP_PG_BIN", "").strip()
        return cls(
            database_url=env.get("DATABASE_URL", "").strip(),
            directory=Path(env.get("KARNI_BACKUP_DIR", "").strip() or "/backups"),
            keep=_env_int(env, "KARNI_BACKUP_KEEP", 7, 1),
            interval_hours=_env_float(env, "KARNI_BACKUP_INTERVAL_HOURS", 24.0),
            media_root=Path(media.strip()) if media.strip() else None,
            s3_bucket=env.get("KARNI_BACKUP_S3_BUCKET", "").strip(),
            s3_prefix=prefix,
            s3_endpoint=env.get("AWS_S3_ENDPOINT_URL", "").strip(),
            s3_region=env.get("AWS_S3_REGION_NAME", "").strip(),
            pg_bin=Path(pg_bin) if pg_bin else None,
        )


# PostgreSQL connections and tools


@dataclass(frozen=True)
class Connection:
    """A libpq URL without the password, the password apart, and the database name."""

    url: str
    password: str
    database: str
    env: dict[str, str] = field(default_factory=dict)


def connection(database_url: str) -> Connection:
    """Split ``database_url`` for libpq: the password goes to ``PGPASSWORD``, not argv."""
    if not database_url:
        raise BackupError("DATABASE_URL is not set: there is no database to back up or restore.")
    parts = urlsplit(database_url)
    if parts.scheme not in POSTGRES_SCHEMES:
        raise BackupError(
            f"DATABASE_URL uses {parts.scheme or 'no'} scheme: backups need PostgreSQL "
            "(postgres://user:password@host:5432/name)."
        )
    database = unquote(parts.path.lstrip("/"))
    if not database:
        raise BackupError("DATABASE_URL names no database (postgres://user:password@host/name).")
    user = unquote(parts.username or "")
    password = unquote(parts.password or "")
    host = parts.hostname or ""
    if host and ":" in host:
        host = f"[{host}]"
    netloc = host + (f":{parts.port}" if parts.port else "")
    if user:
        netloc = f"{user.replace('@', '%40')}@{netloc}"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k in LIBPQ_PARAMETERS])
    url = urlunsplit(("postgresql", netloc, parts.path, query, ""))
    env = {"PGPASSWORD": password} if password else {}
    return Connection(url, password, database, env)


def with_database(database_url: str, name: str) -> str:
    """``database_url`` pointing at another database on the same server."""
    parts = urlsplit(database_url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


def _tool(config: Config, name: str) -> str:
    if config.pg_bin is not None:
        candidate = config.pg_bin / name
        if not candidate.exists():
            raise BackupError(f"{candidate} does not exist (KARNI_BACKUP_PG_BIN).")
        return str(candidate)
    found = shutil.which(name)
    if found is None:
        raise BackupError(
            f"{name} is not on PATH. Run backups in the backup service (it has the PostgreSQL "
            "client tools), or set KARNI_BACKUP_PG_BIN to the directory that holds them."
        )
    return found


def _postgres(config: Config, conn: Connection, argv: Sequence[str], what: str) -> str:
    env = {**os.environ, **conn.env}
    result = subprocess.run(list(argv), env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit status {result.returncode}"
        if "unrecognized configuration parameter" in detail:
            detail += (
                " The PostgreSQL client tools are newer than the server. Use the server's "
                "major version: the backup image's POSTGRES_VERSION, or KARNI_BACKUP_PG_BIN."
            )
        raise BackupError(f"{what} failed: {detail}")
    return result.stdout


# Backups on disk


def _now() -> datetime:
    return datetime.now(UTC)


def backup_name(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(NAME_FORMAT)


def backup_time(name: str) -> datetime:
    return datetime.strptime(name, NAME_FORMAT).replace(tzinfo=UTC)


def list_backups(directory: Path) -> list[Path]:
    """Complete backups in ``directory``, newest first."""
    if not directory.is_dir():
        return []
    found = [
        path
        for path in directory.iterdir()
        if path.is_dir() and NAME_PATTERN.match(path.name) and (path / MANIFEST_FILE).is_file()
    ]
    return sorted(found, key=lambda path: path.name, reverse=True)


def _media_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def archive_media(root: Path, target: Path) -> dict[str, int]:
    """``root``'s files into a gzip tar under ``media/``: ``{"files": n, "bytes": size}``."""
    files = 0
    with tarfile.open(target, "w:gz") as archive:
        for path in _media_files(root):
            archive.add(path, arcname=f"media/{path.relative_to(root).as_posix()}")
            files += 1
    return {"files": files, "bytes": target.stat().st_size}


def run_backup(
    config: Config, *, client: S3Client | None = None, now: datetime | None = None
) -> Path:
    """Dump the database and archive the media into a new backup, then apply retention."""
    conn = connection(config.database_url)
    moment = now or _now()
    name = backup_name(moment)
    config.directory.mkdir(parents=True, exist_ok=True)
    final = config.directory / name
    if final.exists():
        raise BackupError(f"{final} already exists: one backup per second at most.")
    for stale in config.directory.glob(".*.partial"):
        shutil.rmtree(stale, ignore_errors=True)
    partial = config.directory / f".{name}.partial"
    partial.mkdir()
    try:
        dump = partial / DUMP_FILE
        _postgres(
            config,
            conn,
            [_tool(config, "pg_dump"), "--format=custom", f"--file={dump}", f"--dbname={conn.url}"],
            "pg_dump",
        )
        manifest: dict[str, Any] = {
            "format": FORMAT_VERSION,
            "name": name,
            "created": moment.astimezone(UTC).isoformat(),
            "database": {"name": conn.database, "bytes": dump.stat().st_size},
            "media": None,
        }
        media = config.media_root
        if media is not None and media.is_dir() and any(_media_files(media)):
            manifest["media"] = {"root": str(media), **archive_media(media, partial / MEDIA_FILE)}
        (partial / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2) + "\n")
        partial.rename(final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    if config.s3_bucket:
        upload(config, final, client or s3_client(config))
    prune(config, client=client if config.s3_bucket else None)
    return final


def prune(config: Config, *, client: S3Client | None = None) -> list[str]:
    """Delete all but the newest ``config.keep`` backups, locally and in the bucket."""
    removed = []
    for path in list_backups(config.directory)[config.keep :]:
        shutil.rmtree(path)
        removed.append(path.name)
    if config.s3_bucket:
        s3 = client or s3_client(config)
        for name in s3_backups(config, s3)[config.keep :]:
            keys = [{"Key": key} for key in _s3_keys(config, s3, f"{config.s3_prefix}{name}/")]
            for start in range(0, len(keys), 1000):
                s3.delete_objects(
                    Bucket=config.s3_bucket, Delete={"Objects": keys[start : start + 1000]}
                )
            if name not in removed:
                removed.append(name)
    return removed


# S3


def s3_client(config: Config) -> S3Client:
    try:
        import boto3  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        raise BackupError(
            "KARNI_BACKUP_S3_BUCKET is set but boto3 is not installed. The scaffold's backup "
            "image installs it. Elsewhere: pip install boto3."
        ) from None
    client: S3Client = boto3.client(
        "s3", endpoint_url=config.s3_endpoint or None, region_name=config.s3_region or None
    )
    return client


def upload(config: Config, backup: Path, client: S3Client) -> None:
    for path in sorted(backup.iterdir()):
        client.upload_file(
            str(path), config.s3_bucket, f"{config.s3_prefix}{backup.name}/{path.name}"
        )


def _s3_keys(config: Config, client: S3Client, prefix: str) -> list[str]:
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": config.s3_bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        keys.extend(str(item["Key"]) for item in page.get("Contents", []))
        token = page.get("NextContinuationToken")
        if not page.get("IsTruncated") or not token:
            return keys


def s3_backups(config: Config, client: S3Client) -> list[str]:
    """Complete backups in the bucket (those with a manifest), newest first."""
    names = set()
    for key in _s3_keys(config, client, config.s3_prefix):
        rest = key[len(config.s3_prefix) :]
        name, _, file = rest.partition("/")
        if NAME_PATTERN.match(name) and file == MANIFEST_FILE:
            names.add(name)
    return sorted(names, reverse=True)


def fetch(config: Config, name: str, client: S3Client, target: Path) -> Path:
    """Download one backup from the bucket into ``target/<name>``."""
    folder = target / name
    folder.mkdir(parents=True, exist_ok=True)
    keys = _s3_keys(config, client, f"{config.s3_prefix}{name}/")
    if not keys:
        raise BackupError(f"No backup {name} in s3://{config.s3_bucket}/{config.s3_prefix}.")
    for key in keys:
        client.download_file(config.s3_bucket, key, str(folder / key.rsplit("/", 1)[-1]))
    return folder


# Restore and row counts


def find_backup(config: Config, name: str, *, client: S3Client | None = None) -> Path:
    """A local backup by name (``latest`` for the newest), fetched from S3 when only there."""
    local = list_backups(config.directory)
    if name == "latest":
        if local:
            return local[0]
        if config.s3_bucket:
            remote = s3_backups(config, client or s3_client(config))
            if remote:
                name = remote[0]
        if name == "latest":
            raise BackupError(f"No backup in {config.directory} yet. Run `karni-backup run`.")
    path = config.directory / name
    if (path / MANIFEST_FILE).is_file():
        return path
    if config.s3_bucket:
        return fetch(config, name, client or s3_client(config), Path(tempfile.mkdtemp()))
    raise BackupError(f"No backup named {name} in {config.directory} (karni-backup list).")


def create_database(config: Config, database_url: str) -> None:
    conn = connection(database_url)
    maintenance = connection(with_database(database_url, "postgres"))
    _postgres(
        config,
        conn,
        [_tool(config, "createdb"), f"--maintenance-db={maintenance.url}", conn.database],
        f"createdb {conn.database}",
    )


def restore(
    config: Config,
    backup: Path,
    database_url: str,
    *,
    create: bool = False,
    clean: bool = False,
    media_root: Path | None = None,
) -> None:
    """Restore ``backup`` into ``database_url`` in one transaction, its media into ``media_root``.

    ``create`` creates the database first. ``clean`` drops what the backup restores (and
    empties ``media_root``) first, for a restore over an existing database.
    """
    conn = connection(database_url)
    dump = backup / DUMP_FILE
    if not dump.is_file():
        raise BackupError(f"{dump} is missing: {backup} is not a complete backup.")
    if create:
        create_database(config, database_url)
    argv = [_tool(config, "pg_restore"), "--no-owner", "--no-privileges", "--single-transaction"]
    if clean:
        argv += ["--clean", "--if-exists"]
    _postgres(config, conn, [*argv, f"--dbname={conn.url}", str(dump)], "pg_restore")
    archive = backup / MEDIA_FILE
    if media_root is not None and archive.is_file():
        if clean and media_root.is_dir():
            for child in media_root.iterdir():
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        media_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as tar:
            members = [m for m in tar.getmembers() if m.name.startswith("media/")]
            for member in members:
                member.name = member.name.removeprefix("media/")
            tar.extractall(media_root, members=members, filter="data")
        hand_over(media_root, [media_root / member.name for member in members])


def hand_over(root: Path, paths: Sequence[Path]) -> None:
    """Give restored files (and their folders) to ``root``'s owner, when running as root.

    The backup container runs as root, and the application writes uploads as its
    own user, which must keep owning every restored file and folder.
    """
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    owner = root.stat()
    done: set[Path] = set()
    for path in paths:
        for item in [path, *path.parents]:
            if item == root or root not in item.parents or item in done:
                continue
            os.chown(item, owner.st_uid, owner.st_gid, follow_symlinks=False)
            done.add(item)


COUNT_SQL = """
select table_schema || '.' || table_name,
       (xpath('/row/c/text()', query_to_xml(
           format('select count(*) as c from %I.%I', table_schema, table_name),
           false, true, '')))[1]::text
from information_schema.tables
where table_type = 'BASE TABLE'
  and table_schema not in ('pg_catalog', 'information_schema')
order by 1
"""


def row_counts(config: Config, database_url: str) -> dict[str, int]:
    """Exact row counts per table (``schema.table``) of every user table."""
    conn = connection(database_url)
    out = _postgres(
        config,
        conn,
        [_tool(config, "psql"), "--no-psqlrc", "-At", "-F", "\t", "-c", COUNT_SQL, conn.url],
        "psql (row counts)",
    )
    counts: dict[str, int] = {}
    for line in out.splitlines():
        table, _, count = line.partition("\t")
        if table:
            counts[table] = int(count or 0)
    return counts


# Health and the schedule


def write_status(config: Config, ok: bool, detail: str) -> None:
    config.directory.mkdir(parents=True, exist_ok=True)
    status = {"ok": ok, "at": _now().isoformat(), "detail": detail}
    (config.directory / STATUS_FILE).write_text(json.dumps(status) + "\n")


def health(config: Config, *, now: datetime | None = None) -> tuple[bool, str]:
    """Unhealthy when the last run failed, or no backup succeeded for two intervals."""
    path = config.directory / STATUS_FILE
    if not path.is_file():
        return True, "no backup has run yet"
    try:
        status = json.loads(path.read_text())
        at = datetime.fromisoformat(str(status["at"]))
    except (OSError, ValueError, KeyError) as exc:
        return False, f"{path} is unreadable: {exc}"
    if not status.get("ok"):
        return False, f"the last backup failed at {at.isoformat()}: {status.get('detail')}"
    late = timedelta(hours=config.interval_hours * 2 + 1)
    if (now or _now()) - at > late:
        return False, f"no backup since {at.isoformat()}"
    return True, f"last backup {status.get('detail')} at {at.isoformat()}"


def seconds_until_due(config: Config, *, now: datetime | None = None) -> float:
    """0 when the newest backup is older than the interval (or there is none)."""
    backups = list_backups(config.directory)
    if not backups:
        return 0.0
    due = backup_time(backups[0].name) + timedelta(hours=config.interval_hours)
    return max(0.0, (due - (now or _now())).total_seconds())


def _attempt(config: Config, client: S3Client | None = None) -> bool:
    try:
        path = run_backup(config, client=client)
    except BackupError as exc:
        write_status(config, False, str(exc))
        _say(f"{CODE} backup failed: {exc}", error=True)
        return False
    write_status(config, True, path.name)
    _say(f"backup {path.name} written to {path} (keeping {config.keep})")
    return True


def loop(
    config: Config,
    *,
    sleep: Callable[[float], None] = time.sleep,
    runs: int | None = None,
) -> None:
    """Back up whenever one is due, for ever (or ``runs`` times, for tests)."""

    def stop(signum: int, frame: FrameType | None) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    _say(f"backing up every {config.interval_hours:g} h into {config.directory}")
    done = 0
    while runs is None or done < runs:
        wait = seconds_until_due(config)
        if wait > 0:
            sleep(min(wait, 3600.0))
            continue
        if not _attempt(config):
            sleep(min(3600.0, config.interval_hours * 3600))
        done += 1


def _say(message: str, *, error: bool = False) -> None:
    print(f"karni-backup: {message}", file=sys.stderr if error else sys.stdout, flush=True)


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="karni-backup", description="Database and media backups for a Karni project."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="one backup now, then retention")
    commands.add_parser("loop", help="back up every KARNI_BACKUP_INTERVAL_HOURS")
    commands.add_parser("list", help="the backups, newest first")
    commands.add_parser("check", help="exit 1 when the last backup failed or is overdue")
    restore_cmd = commands.add_parser("restore", help="restore a backup into a database")
    restore_cmd.add_argument("name", help="a backup name from `list`, or latest")
    restore_cmd.add_argument(
        "--database-url",
        help="the database to restore into. Without it, --clean restores over DATABASE_URL",
    )
    restore_cmd.add_argument("--create", action="store_true", help="create that database first")
    restore_cmd.add_argument(
        "--clean", action="store_true", help="drop what the backup restores first (and the media)"
    )
    restore_cmd.add_argument("--media-root", type=Path, help="also restore the media here")
    counts_cmd = commands.add_parser("counts", help="row counts per table")
    counts_cmd.add_argument("--database-url", required=True)
    counts_cmd.add_argument("--against", help="another database: exit 1 on any difference")
    args = parser.parse_args(argv)
    try:
        config = Config.from_env(environ)
        if args.command == "run":
            return 0 if _attempt(config) else 1
        if args.command == "loop":
            loop(config)
            return 0
        if args.command == "list":
            for path in list_backups(config.directory):
                manifest = json.loads((path / MANIFEST_FILE).read_text())
                media = manifest.get("media") or {}
                print(
                    f"{path.name}  database {manifest['database']['bytes']} bytes  "
                    f"media {media.get('files', 0)} files"
                )
            if config.s3_bucket:
                for name in s3_backups(config, s3_client(config)):
                    print(f"{name}  in s3://{config.s3_bucket}/{config.s3_prefix}")
            return 0
        if args.command == "check":
            healthy, detail = health(config)
            print(("healthy: " if healthy else "unhealthy: ") + detail)
            return 0 if healthy else 1
        if args.command == "restore":
            target = args.database_url
            if not target:
                if not args.clean:
                    raise BackupError(
                        "Name the database to restore into with --database-url, or pass --clean "
                        "to restore over DATABASE_URL (stop the services that write to it first)."
                    )
                target = config.database_url
            backup = find_backup(config, args.name)
            restore(
                config,
                backup,
                target,
                create=args.create,
                clean=args.clean,
                media_root=args.media_root,
            )
            _say(f"restored {backup.name} into {connection(target).database}")
            return 0
        counts = row_counts(config, args.database_url)
        if not args.against:
            for table, count in counts.items():
                print(f"{table}\t{count}")
            return 0
        other = row_counts(config, args.against)
        differ = 0
        for table in sorted(set(counts) | set(other)):
            mark = "" if counts.get(table) == other.get(table) else "  DIFFERS"
            differ += bool(mark)
            print(f"{table}\t{counts.get(table, '-')}\t{other.get(table, '-')}{mark}")
        print(f"{len(counts)} tables, {differ} differ", file=sys.stderr)
        return 1 if differ else 0
    except BackupError as exc:
        _say(f"{CODE} {exc}", error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
