"""The names the tool had before it was called Jaws, still honoured.

Until every consumer has moved, a run accepts the old project file name
(`jwall-engineering-sites.yaml`) and the old environment variables (`JES_*`),
and says so on stderr each time. The old command name is a second entry point
in pyproject.toml. Everything about the old names lives here so that it can be
removed in one change.
"""

from __future__ import annotations

import os
import sys
from collections.abc import MutableMapping
from pathlib import Path

from .errors import ConfigError
from .log import in_github_actions
from .site import SITE_FILE

LEGACY_SITE_FILE = Path("jwall-engineering-sites.yaml")
ENV_PREFIX = "JAWS_"
LEGACY_ENV_PREFIX = "JES_"


def adopt_legacy_environment(environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Copy each `JES_<NAME>` to `JAWS_<NAME>` unless that is already set.

    Returns the old names that were adopted, sorted. A variable set under both
    names keeps its `JAWS_` value.
    """
    env = os.environ if environ is None else environ
    adopted = []
    for name in sorted(env):
        if not name.startswith(LEGACY_ENV_PREFIX):
            continue
        new = ENV_PREFIX + name.removeprefix(LEGACY_ENV_PREFIX)
        if new not in env:
            env[new] = env[name]
            adopted.append(name)
    return adopted


def resolve_project_file(path: Path) -> Path:
    """The project file to read for `--file path`.

    `jaws.yaml` when it exists; else the old name beside it when that exists;
    else `path`, so the error names the file to create. Both existing is an
    error: nothing should have to guess which one is current. A path with any
    other name is returned as given.
    """
    if path.name != SITE_FILE.name:
        return path
    legacy = path.with_name(LEGACY_SITE_FILE.name)
    if path.is_file() and legacy.is_file():
        raise ConfigError(
            f"both {path} and {legacy} exist; {legacy.name} is the old name of the "
            f"project file, so delete it and keep {path.name}"
        )
    if not path.is_file() and legacy.is_file():
        return legacy
    return path


def notices(project_file: Path, adopted: list[str]) -> list[str]:
    """What to tell a caller that still uses an old name."""
    found = []
    if project_file.name == LEGACY_SITE_FILE.name:
        found.append(
            f"{project_file} is the project file's old name; rename it to {SITE_FILE.name}"
        )
    if adopted:
        renamed = ", ".join(
            f"{name} to {ENV_PREFIX}{name.removeprefix(LEGACY_ENV_PREFIX)}" for name in adopted
        )
        found.append(
            f"environment variables under the old {LEGACY_ENV_PREFIX} prefix: rename {renamed}"
        )
    return found


def announce(messages: list[str]) -> None:
    """Print each notice on stderr, as a warning annotation in GitHub Actions.

    Never on stdout: some commands' output is parsed by the caller.
    """
    for message in messages:
        if in_github_actions():
            print(f"::warning title=Jaws::{message}", file=sys.stderr, flush=True)
        else:
            print(f"warning: {message}", file=sys.stderr, flush=True)
