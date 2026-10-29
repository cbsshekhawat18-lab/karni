"""Experimental. ``karni build --json``: its output, and the JSON Schema published for it.

The output is ``{version, file, valid, issues, status, code, message, plan,
files, hand_edits, adopted, steps, next}``. ``plan`` is exactly what
``karni plan --json`` prints. The schema is published as
``docs/assets/karni-build.schema.json`` (regenerate it with
``python -m karni_cli.builder.output > docs/assets/karni-build.schema.json``),
and ``version`` moves only for a breaking change of the output.
"""

from __future__ import annotations

import json
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from karni_cli.spec import plan as plan_mod

__all__ = ["BUILD_SCHEMA_URL", "BUILD_VERSION", "STATUSES", "STEPS", "checked", "json_schema"]

#: Experimental. The version of the ``--json`` output. It moves only for a breaking change.
BUILD_VERSION: Final = 1
#: Experimental. Where the JSON Schema of ``karni build --json`` is published.
BUILD_SCHEMA_URL: Final = (
    "https://cbsshekhawat18-lab.github.io/karni/assets/karni-build.schema.json"
)
Status = Literal["built", "nothing to build", "dry run", "refused", "failed", "invalid"]
#: Experimental. What a build ends as.
STATUSES: Final = (
    "built",
    "nothing to build",
    "dry run",
    "refused",
    "failed",
    "invalid",
)
StepName = Literal["modules", "files", "migrations", "migrate", "seed", "types", "test", "check"]
#: Experimental. The steps of a build, in the order they run.
STEPS: Final = ("modules", "files", "migrations", "migrate", "seed", "types", "test", "check")


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _FileOut(_Out):
    """One file a build writes (or, with --dry-run, would write)."""

    path: str = Field(description="The file, relative to the project root.")
    action: Literal["create", "modify", "delete"] = Field(description="What happens to it.")
    owner: Literal["karni", "project"] = Field(
        description="karni: a Karni-owned file or block, rewritten on every build. project: a "
        "file of the project's, created once or given a missing class."
    )


class _HandEditOut(_Out):
    """A Karni-owned file or block edited by hand: the build stops before it writes anything."""

    path: str = Field(description="The file, or the block (config/settings.py, routes.tsx ...).")
    lines: list[int] = Field(description="The lines of the file on disk that differ (1-based).")
    diff: list[str] = Field(description="A short diff: - what karni build writes, + the file.")
    unrecorded: bool = Field(
        description="true: the file exists but karni build never wrote it (not in the record)."
    )


class _StepOut(_Out):
    """One step of the build."""

    name: StepName = Field(description="The step: " + ", ".join(STEPS) + ".")
    status: Literal["done", "skipped", "failed", "pending"] = Field(
        description="done, skipped (nothing to do), failed (the build stopped here) or pending "
        "(not reached: the next karni build runs it)."
    )
    summary: str = Field(description="One line: what the step did, or why it failed.")


class _BuildOut(_Out):
    """Experimental. The output of karni build --json."""

    version: Literal[1] = Field(description="The version of this output: 1.")
    file: str = Field(description="The spec file, as given.")
    valid: bool = Field(description="false when the spec has problems: then issues lists them.")
    issues: list[dict[str, Any]] = Field(
        description="The spec's problems, as karni spec validate --json reports them."
    )
    status: Status = Field(description="How the build ended: " + ", ".join(STATUSES) + ".")
    code: str | None = Field(
        description="The error code when refused or failed (karni explain <code>). null otherwise."
    )
    message: str | None = Field(description="What stopped the build. null when nothing did.")
    plan: dict[str, Any] | None = Field(
        description="The plan, exactly as karni plan --json prints it (docs/assets/"
        "karni-plan.schema.json). null when the spec has problems."
    )
    files: list[_FileOut] = Field(description="The files written (with --dry-run: to write).")
    hand_edits: list[_HandEditOut] = Field(
        description="Karni-owned files and blocks edited by hand. The build stops on them (C273) "
        "unless --force (a .orig backup is kept) or --adopt."
    )
    adopted: list[str] = Field(
        description="Karni-owned files and blocks the project adopted: karni build leaves them."
    )
    steps: list[_StepOut] = Field(description="Every step, in order, with how it went.")
    next: str | None = Field(description="What to do next, when something is left to do.")


def json_schema() -> dict[str, Any]:
    """Experimental. The JSON Schema of ``karni build --json``, as published at :data:`BUILD_SCHEMA_URL`."""
    from karni_cli.spec.schema import _tidy

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BUILD_SCHEMA_URL,
        "title": "karni build --json",
        "description": (
            "Experimental. What karni build did. Generated by python -m karni_cli.builder.output. "
            "Never edit it by hand."
        ),
        **_tidy(_BuildOut.model_json_schema()),
    }


def checked(data: dict[str, Any]) -> dict[str, Any]:
    """Experimental. ``data`` checked against the published schema's models (raises on a mismatch)."""
    if data.get("plan") is not None:
        plan_mod.checked_output(data["plan"])
    return _BuildOut.model_validate(data).model_dump(mode="json")


if __name__ == "__main__":  # pragma: no cover - python -m karni_cli.builder.output
    print(json.dumps(json_schema(), indent=2, sort_keys=False))
