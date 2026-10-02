"""Hatch build hook: bundle templates/project into the wheel (contract E7).

From the monorepo, ../../templates/project is copied to karni_cli/_templates/
project so sdists are self-contained. Building a wheel FROM an sdist finds the
copy already in-tree and no-ops — never a missing-source error.
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
            shutil.copytree(repo_source, bundled)
        elif not bundled.is_dir():
            raise RuntimeError(
                "No project template available: neither the monorepo templates/ "
                "nor a bundled karni_cli/_templates copy exists."
            )
        build_data.setdefault("artifacts", []).append("karni_cli/_templates/")
