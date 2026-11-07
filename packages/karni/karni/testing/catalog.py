"""Experimental. ``assert_module_manifest``: a module's catalog entry matches the module.

::

    from karni.testing import assert_module_manifest


    def test_manifest() -> None:
        assert_module_manifest("karni_payments")

**assert_module_manifest(package)** reads ``<package>/karni.module.toml``
(package data, as ``karni add`` reads it) and checks, in one call:

* **format**: it parses (:func:`karni.catalog.parse_text`) as a module
  manifest whose first app is ``package``;
* **entry point**: once the distribution is installed, its ``karni.modules``
  entry point with the manifest's name names ``package``, so the catalog
  finds it;
* **settings**: every setting in ``provides.settings`` is a key of the
  fragment ``wiring.settings`` names (``conf:DEFAULTS``), and every
  ``KARNI_<NAME>_*`` key of that fragment is listed, so the spec's module
  options cannot drift from the module;
* **models**: when Django is set up with the app installed, ``provides.models``
  are exactly the app's concrete models.

It raises :class:`~karni.exceptions.KarniAssertionError` (``E310``) listing
every mismatch. Override / escape hatch:
the checks are plain functions of :mod:`karni.catalog`, so a module with a
setting outside its prefix lists it in ``provides.settings`` like any other.
"""

from __future__ import annotations

from importlib import import_module, resources
from importlib.metadata import PackageNotFoundError, distribution
from typing import TYPE_CHECKING

from karni.catalog import ENTRY_POINT_GROUP, MANIFEST_FILE, ManifestError, parse_text
from karni.exceptions import KarniAssertionError

if TYPE_CHECKING:
    from karni.catalog import Manifest

__all__ = ["assert_module_manifest"]


def _models(app: str) -> set[str] | None:
    """The concrete models of ``app``, or ``None`` when Django is not set up with it."""
    try:
        from django.apps import apps
        from django.core.exceptions import AppRegistryNotReady
    except ImportError:  # pragma: no cover - karni depends on Django
        return None
    try:
        config = apps.get_app_config(app)
    except (LookupError, AppRegistryNotReady):
        return None
    return {model.__name__ for model in config.get_models()}


def assert_module_manifest(package: str) -> Manifest:
    """Experimental. Check ``<package>/karni.module.toml`` against the module; return it."""
    source = f"{package}/{MANIFEST_FILE}"
    try:
        text = resources.files(package).joinpath(MANIFEST_FILE).read_text(encoding="utf-8")
    except (ImportError, OSError) as exc:
        raise KarniAssertionError(f"{source} cannot be read: {exc}", code="E310") from None
    try:
        manifest = parse_text(text, source)
    except ManifestError as exc:
        raise KarniAssertionError(
            "\n".join([f"{source} is not valid:", *exc.problems]), code="E310"
        ) from None
    problems: list[str] = []
    if manifest.kind != "module" or manifest.app != package:
        problems.append(f"wiring.apps must start with {package!r}, got {manifest.app!r}")
    try:
        installed = distribution(manifest.distribution)
    except PackageNotFoundError:  # a module's suite may run from its checkout, uninstalled
        installed = None
    points = {
        p.name: p.value
        for p in (installed.entry_points if installed else ())
        if p.group == ENTRY_POINT_GROUP
    }
    if installed is not None and points.get(manifest.name, "").split(":", 1)[0] != package:
        problems.append(
            f'no [project.entry-points."{ENTRY_POINT_GROUP}"] {manifest.name} = "{package}" '
            "installed (reinstall the module after adding it)"
        )
    if manifest.wiring.settings:
        module, _, attribute = manifest.wiring.settings.partition(":")
        defaults = getattr(import_module(module), attribute, None)
        if not isinstance(defaults, dict):
            problems.append(f"wiring.settings {manifest.wiring.settings} is not a dict")
        else:
            listed = set(manifest.provides.settings)
            missing = sorted(listed - set(defaults))
            prefix = f"KARNI_{manifest.name.upper()}_"
            unlisted = sorted(k for k in defaults if k.startswith(prefix) and k not in listed)
            if missing:
                problems.append(f"provides.settings not in {attribute}: {', '.join(missing)}")
            if unlisted:
                problems.append(f"{attribute} keys not in provides.settings: {', '.join(unlisted)}")
    found = _models(package)
    if found is not None and found != set(manifest.provides.models):
        problems.append(
            f"provides.models {sorted(manifest.provides.models)} differ from the app's "
            f"models {sorted(found)}"
        )
    if problems:
        raise KarniAssertionError(
            "\n".join([f"{source} does not match {package}:", *problems]), code="E310"
        )
    return manifest
