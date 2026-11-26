"""One version line for karni, karni-cli and the first-party modules.

Karni's packages are released in lockstep: ``karni``, ``karni-cli`` and every
module of this repository carry one version, and a module's range on karni is
its own minor (``karni>=0.7,<0.8``). A project that installs them unpinned
can end up with ``karni`` on 0.7 and ``karni-site`` on 0.6 after one
``pip install -U``. ``karni.W521`` names each package that is not on the
line karni itself is on.

A package that is not a release is left out: a checkout installed in editable
mode, and a version with a ``.dev`` or ``+local`` part. Third-party modules
(``karni-*`` packages this repository does not release) have their own
versions and are never compared.

``python -m karni.versions`` prints the installed first-party versions as JSON
(``karni doctor`` reads it).

Override / escape hatch: add ``"karni.W521"`` to ``SILENCED_SYSTEM_CHECKS``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from importlib import metadata

from django.core import checks
from packaging.version import InvalidVersion, Version

from karni.exceptions import check_warning

__all__ = ["LOCKSTEP", "installed_versions", "line", "off_the_line", "range_for"]

#: The distributions released in lockstep with karni (docs/releasing.md lists them). A test keeps
#: this equal to the folders of ``modules/``.
LOCKSTEP: tuple[str, ...] = (
    "karni",
    "karni-cli",
    "karni-ai",
    "karni-approvals",
    "karni-charts",
    "karni-commerce",
    "karni-game",
    "karni-impersonation",
    "karni-payments",
    "karni-reports",
    "karni-site",
    "karni-storage",
)


def line(version: str) -> tuple[int, int] | None:
    """The (major, minor) a version belongs to, ``None`` for text that is not a version."""
    try:
        parsed = Version(version)
    except InvalidVersion:
        return None
    release = parsed.release
    return release[0], release[1] if len(release) > 1 else 0


def range_for(version: str) -> str | None:
    """The range that keeps a project on the line of ``version``: ``>=0.7,<0.8``, ``>=1.2,<2``."""
    found = line(version)
    if found is None:
        return None
    major, minor = found
    return (
        f">={major}.{minor},<{major}.{minor + 1}"
        if major == 0
        else f">={major}.{minor},<{major + 1}"
    )


def _editable(distribution: metadata.Distribution) -> bool:
    try:
        text = distribution.read_text("direct_url.json")
        data = json.loads(text) if text else {}
    except (OSError, ValueError):
        return False
    return bool(isinstance(data, dict) and (data.get("dir_info") or {}).get("editable"))


def installed_versions() -> dict[str, str]:
    """The release versions of the lockstep distributions installed here (not a checkout)."""
    found: dict[str, str] = {}
    for name in LOCKSTEP:
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        try:
            parsed = Version(distribution.version)
        except InvalidVersion:
            continue
        if parsed.is_devrelease or parsed.local or _editable(distribution):
            continue
        found[name] = distribution.version
    return found


def off_the_line(versions: Mapping[str, str], reference: str) -> dict[str, str]:
    """The packages of ``versions`` whose line is not the line of ``reference``."""
    wanted = line(reference)
    if wanted is None:
        return {}
    return {name: version for name, version in versions.items() if line(version) != wanted}


@checks.register()
def check_version_line(app_configs: object = None, **kwargs: object) -> list[checks.CheckMessage]:
    """karni.W521: karni, karni-cli or a first-party module on another version line than karni."""
    import karni

    versions = installed_versions()
    reference = versions.get("karni") or karni.__version__
    found = off_the_line(versions, reference)
    wanted = line(reference)
    spec = range_for(reference)
    if not found or wanted is None or spec is None:
        return []
    names = ", ".join(f"{name} {version}" for name, version in sorted(found.items()))
    return [
        check_warning(
            "W521",
            f"karni {reference} is installed with {names}. They are released together and "
            f"must be on the {wanted[0]}.{wanted[1]} line.",
            hint=(
                f"Install every one of them at the range {spec} (pip install 'karni{spec}' "
                "and each module the same way). Pin them in pyproject.toml so an install "
                "cannot drift: karni new writes the range, and karni upgrade writes it for "
                "a project that lists them bare. Moving to a newer line is karni upgrade."
            ),
        )
    ]


if __name__ == "__main__":  # python -m karni.versions
    sys.stdout.write(json.dumps(installed_versions()))
