"""Hatch build hook: bundle templates/project into the wheel (contract E7).

From the monorepo, ../../templates/project is copied to karni_cli/_templates/
project so sdists are self-contained. Building a wheel FROM an sdist finds the
copy already in-tree and no-ops — never a missing-source error.

The same applies to Karni's stdlib-only agent rules (packages/karni/karni/
agent -> karni_cli/_agent): the fallback `karni rules` / `karni new` use when
karni itself is not importable and no project interpreter is reachable.
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

        agent_bundle = pkg_root / "karni_cli" / "_agent"
        agent_source = pkg_root.parent / "karni" / "karni" / "agent"
        if agent_source.is_dir():
            if agent_bundle.exists():
                shutil.rmtree(agent_bundle)
            shutil.copytree(
                agent_source, agent_bundle, ignore=shutil.ignore_patterns("__pycache__")
            )
        elif not agent_bundle.is_dir():
            raise RuntimeError(
                "No agent rules available: neither the monorepo packages/karni/karni/agent "
                "nor a bundled karni_cli/_agent copy exists."
            )
        build_data["artifacts"].append("karni_cli/_agent/")
