"""Hatch build hook: bundle templates/project into the wheel (contract E7).

From the monorepo, ../../templates/project is copied to karni_cli/_templates/
project so sdists are self-contained. Building a wheel FROM an sdist finds the
copy already in-tree and no-ops — never a missing-source error.

The same applies to Karni's stdlib-only agent rules (packages/karni/karni/
agent -> karni_cli/_agent): the fallback `karni rules` / `karni new` use when
karni itself is not importable and no project interpreter is reachable. And
to Karni's machine-readable changelog (packages/karni/karni/changelog ->
karni_cli/_changelog), which `karni upgrade` reads: the CLI must know every
change up to its own release, whatever karni the project has installed.
Likewise Karni's error code registry (packages/karni/karni/errorcodes ->
karni_cli/_errorcodes), which `karni explain` and error messages read, the
settings reference (packages/karni/karni/conf/reference.py and the base.py it
reads -> karni_cli/_settings), which `karni explain <SETTING>` reads, and
@karni/ui's token stylesheet (packages/karni-ui/src/styles.css ->
karni_cli/_ui/styles.css), whose defaults `karni ui detect` lists when a
project has neither @karni/ui installed nor a monorepo checkout. And the
module catalog (packages/karni/karni/catalog -> karni_cli/_catalog, with a
copy of each module's karni.module.toml under _catalog/modules/), so
`karni modules list` shows the modules a project has not installed.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class TemplateBundleHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        pkg_root = Path(self.root)
        bundled = pkg_root / "karni_cli" / "_templates" / "project"
        repo_source = pkg_root.parent.parent / "templates" / "project"

        if repo_source.is_dir():
            if bundled.exists():
                shutil.rmtree(bundled)
            shutil.copytree(
                repo_source,
                bundled,
                ignore=shutil.ignore_patterns("__pycache__", "node_modules", ".DS_Store"),
            )
        elif not bundled.is_dir():
            raise RuntimeError(
                "No project template available: neither the monorepo templates/ "
                "nor a bundled karni_cli/_templates copy exists."
            )
        build_data.setdefault("artifacts", []).append("karni_cli/_templates/")

        self._bundle_karni(pkg_root, "agent", "_agent", "agent rules", build_data)
        self._bundle_karni(pkg_root, "changelog", "_changelog", "changelog", build_data)
        self._bundle_karni(pkg_root, "errorcodes", "_errorcodes", "error codes", build_data)
        self._bundle_karni(pkg_root, "catalog", "_catalog", "module catalog", build_data)
        manifests = sorted(pkg_root.parent.parent.glob("modules/*/karni_*/karni.module.toml"))
        bundled_modules = pkg_root / "karni_cli" / "_catalog" / "modules"
        if manifests:
            bundled_modules.mkdir(parents=True, exist_ok=True)
            for manifest in manifests:
                shutil.copy2(manifest, bundled_modules / f"{manifest.parent.parent.name}.toml")
        elif not bundled_modules.is_dir():
            raise RuntimeError("No module manifests to bundle into karni_cli/_catalog/modules.")
        # karni.links (every published URL, stdlib only) rides inside the
        # errorcodes bundle: the registry loads it by path when karni is absent.
        links = pkg_root.parent / "karni" / "karni" / "links.py"
        bundled_links = pkg_root / "karni_cli" / "_errorcodes" / "links.py"
        if links.is_file():
            shutil.copy2(links, bundled_links)
        elif not bundled_links.is_file():
            raise RuntimeError("No karni/links.py to bundle into karni_cli/_errorcodes.")

        # The settings reference (stdlib only) and the file it reads: `karni explain <SETTING>`.
        settings_bundle = pkg_root / "karni_cli" / "_settings"
        conf = pkg_root.parent / "karni" / "karni" / "conf"
        if (conf / "reference.py").is_file():
            settings_bundle.mkdir(parents=True, exist_ok=True)
            for name in ("reference.py", "base.py"):
                shutil.copy2(conf / name, settings_bundle / name)
        elif not (settings_bundle / "reference.py").is_file():
            raise RuntimeError("No karni/conf/reference.py to bundle into karni_cli/_settings.")
        build_data["artifacts"].append("karni_cli/_settings/")

        styles = pkg_root.parent / "karni-ui" / "src" / "styles.css"
        bundled_styles = pkg_root / "karni_cli" / "_ui" / "styles.css"
        if styles.is_file():
            bundled_styles.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(styles, bundled_styles)
        elif not bundled_styles.is_file():
            raise RuntimeError("No @karni/ui styles.css to bundle into karni_cli/_ui.")
        build_data["artifacts"].append("karni_cli/_ui/")

    @staticmethod
    def _bundle_karni(
        pkg_root: Path, package: str, bundle: str, what: str, build_data: dict[str, Any]
    ) -> None:
        """Copy the stdlib-only ``karni/<package>`` into ``karni_cli/<bundle>``."""
        bundled = pkg_root / "karni_cli" / bundle
        source = pkg_root.parent / "karni" / "karni" / package
        if source.is_dir():
            if bundled.exists():
                shutil.rmtree(bundled)
            shutil.copytree(source, bundled, ignore=shutil.ignore_patterns("__pycache__"))
        elif not bundled.is_dir():
            raise RuntimeError(
                f"No {what} available: neither the monorepo packages/karni/karni/{package} "
                f"nor a bundled karni_cli/{bundle} copy exists."
            )
        build_data["artifacts"].append(f"karni_cli/{bundle}/")
