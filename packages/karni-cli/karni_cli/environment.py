"""Facts about where the CLI is running."""

from __future__ import annotations

import os
from collections.abc import Mapping

#: ``CI`` is the de-facto convention; the rest are set by CI systems that do
#: not always export it (GitHub Actions, GitLab, Buildkite, CircleCI, Jenkins,
#: Azure Pipelines, TeamCity, Bitbucket Pipelines, AWS CodeBuild).
CI_ENV_VARS: tuple[str, ...] = (
    "CI",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "BUILDKITE",
    "CIRCLECI",
    "JENKINS_URL",
    "TF_BUILD",
    "TEAMCITY_VERSION",
    "BITBUCKET_BUILD_NUMBER",
    "CODEBUILD_BUILD_ID",
)
_FALSY = frozenset({"", "0", "false", "no", "off"})


def is_ci(environ: Mapping[str, str] | None = None) -> bool:
    """True when any CI variable is set to something other than an explicit false."""
    env = os.environ if environ is None else environ
    return any(env.get(name, "").strip().lower() not in _FALSY for name in CI_ENV_VARS)
