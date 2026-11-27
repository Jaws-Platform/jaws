"""GitHub Actions outputs and the step summary. No-ops outside Actions."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .report import Provenance

ENV_PLATFORM_COMMIT = "JAWS_PLATFORM_COMMIT"
ENV_PLATFORM_SOURCE = "JAWS_PLATFORM_SOURCE"
_PLATFORM_COMMIT = re.compile(r"[0-9a-f]{40}")
_PLATFORM_SOURCE = re.compile(r"https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9._-]+")


def write_output(name: str, value: str) -> None:
    """Append `name=value` to GITHUB_OUTPUT when it is set."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    if "\n" in value:
        raise ValueError(f"output {name} must be a single line")
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def append_summary(markdown: str) -> None:
    """Append Markdown to GITHUB_STEP_SUMMARY when it is set."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(markdown.rstrip("\n") + "\n\n")


def run_url() -> str | None:
    server = os.environ.get("GITHUB_SERVER_URL")
    repository = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if server and repository and run_id:
        return f"{server}/{repository}/actions/runs/{run_id}"
    return None


def head_sha() -> str | None:
    return os.environ.get("JAWS_HEAD_SHA") or os.environ.get("GITHUB_SHA")


def commit_url(sha: str | None) -> str | None:
    server = os.environ.get("GITHUB_SERVER_URL")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if sha and server and repository:
        return f"{server}/{repository}/commit/{sha}"
    return None


def platform_commit() -> tuple[str | None, str | None]:
    """The hub commit that built this image and its URL; each is None unless valid."""
    sha = os.environ.get(ENV_PLATFORM_COMMIT, "")
    if not _PLATFORM_COMMIT.fullmatch(sha):
        return None, None
    source = os.environ.get(ENV_PLATFORM_SOURCE, "")
    return sha, f"{source}/commit/{sha}" if _PLATFORM_SOURCE.fullmatch(source) else None


def provenance(version: str) -> Provenance:
    """What the comments' footer says about this run."""
    sha = head_sha()
    platform_sha, platform_url = platform_commit()
    return Provenance(
        version=version,
        sha=sha,
        commit_url=commit_url(sha),
        run_url=run_url(),
        platform_sha=platform_sha,
        platform_url=platform_url,
    )
