"""karni-cli — the ``karni`` command."""

from importlib import metadata as _metadata

try:
    __version__ = _metadata.version("karni-cli")  # [project] version in pyproject.toml
except _metadata.PackageNotFoundError:  # a source tree on sys.path, never installed
    __version__ = "0+unknown"
