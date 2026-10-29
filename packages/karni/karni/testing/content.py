"""``load_content``: a test loads the project's real content, as ``karni load`` does.

The page test of a site renders every page with the rows the design's pages
hold (``content/site.json``, written by ``karni design extract``)::

    from karni.testing import load_content

    @pytest.fixture(autouse=True)
    def site_content(db: None) -> None:
        load_content("content/site.json")

A relative path is read from the project root (``settings.BASE_DIR``, else
the folder above the settings package), never from the working directory,
so the test passes wherever pytest runs from. A file that does not exist, or
rows the models refuse, fail the test with ``E804`` or ``E805`` and the
path, as ``karni load`` reports them.

Override / escape hatch: pass an absolute path, or call
:func:`karni.transfer.loading.load_content` yourself (it takes the importer
class).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from karni.testing._source import project_root

__all__ = ["content_path", "load_content"]

#: Where ``karni design extract -o`` writes a site's content in the procedure.
SITE_CONTENT = "content/site.json"


def content_path(path: str | Path = SITE_CONTENT) -> Path:
    """``path`` as an absolute path: a relative one is read from the project root."""
    file = Path(path)
    return file if file.is_absolute() else project_root() / file


def load_content(
    path: str | Path = SITE_CONTENT, *, missing_ok: bool = False, **options: Any
) -> Any:
    """Load the content file at ``path`` into the test database and return the report.

    :param path: the file, relative to the project root (default ``content/site.json``).
    :param missing_ok: return ``None`` when the file does not exist yet, instead of
        failing. A site's generated page test passes it: until ``karni design
        extract`` writes the file there is nothing to load.
    :param options: passed to :func:`karni.transfer.loading.load_content`
        (``actor``, ``refresh_files``, ``prune``, ``importer_class``).
    :raises karni.transfer.loading.LoadError: ``E804`` (the file, missing or
        unreadable) or ``E805`` (rows refused, each listed).
    """
    from karni.transfer.loading import load_content as load

    file = content_path(path)
    if missing_ok and not file.is_file():
        return None
    return load(file, **options)
