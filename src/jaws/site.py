"""The site file, jaws.yaml, and everything derived from it.

The file holds only what differs between sites. Bucket, roles, state key and
URLs are derived here, which is what guarantees they follow the convention.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .components import (
    Component,
    ContainerImage,
    DatabricksWorkspace,
    Dataset,
    LichessBot,
    TaskRunner,
)
from .errors import ConfigError
from .settings import Settings

SITE_FILE = Path("jaws.yaml")

#: The tags the project file must state.
REQUIRED_TAGS = ("Project", "Environment", "Repository", "Owner")

#: The tags the tool decides for every resource (docs/tagging.md): Organization is
#: the GitHub organization or user the project is registered under
#: (config/projects.yaml), and ManagedBy is `context.managed_by`. A project file
#: may not state either.
TOOL_TAGS = ("Organization", "ManagedBy")

ENVIRONMENT = "prod"
PROD_PREFIX = "prod/"
DEV_PREFIX = "dev/"
PREVIEWS_PREFIX = "previews/"

_FQDN = re.compile(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SiteSection(_Model):
    output_dir: str
    immutable_paths: tuple[str, ...] = ()

    @field_validator("output_dir")
    @classmethod
    def _relative(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value in ("", "."):
            raise ValueError("must be a relative directory inside the repository")
        return value

    @field_validator("immutable_paths")
    @classmethod
    def _globs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in value:
            if pattern.startswith("/") or ".." in pattern.split("/"):
                raise ValueError(f"{pattern!r} must be a glob relative to output_dir")
        return value


class PreviewSection(_Model):
    enabled: bool = True


class DevSection(_Model):
    domain: str = Field(pattern=_FQDN.pattern)


class SiteConfig(_Model):
    """jaws.yaml, validated on its own.

    A file describes a site (`domain` and `site`), a bot project (`components`:
    one container image and one Lichess bot, and optionally datasets and a task
    runner) or a research project (`components`: only datasets and a task
    runner). Rules that need the tool configuration (the DNS zone, the organisation) live
    in `Site.from_config` and `Project.from_config`, so that this model can be
    checked without it.
    """

    version: Literal[1]
    project: str = Field(pattern=_KEBAB.pattern, max_length=30)
    repository: str = Field(pattern=_REPOSITORY.pattern)
    domain: str | None = Field(default=None, pattern=_FQDN.pattern)
    tags: dict[str, str]
    site: SiteSection | None = None
    preview: PreviewSection = PreviewSection()
    dev: DevSection | None = None
    components: tuple[Component, ...] = ()

    @model_validator(mode="after")
    def _one_kind(self) -> SiteConfig:
        is_site = self.domain is not None and self.site is not None and not self.components
        has_components = (
            bool(self.components)
            and self.domain is None
            and self.site is None
            and self.dev is None
            and "preview" not in self.model_fields_set
        )
        if not (is_site or has_components):
            raise ValueError(
                "a file describes either a site (domain and site, no components), a bot "
                "project (components: a container-image and a lichess-bot) or a research "
                "project (components: a dataset and a task-runner) or a Databricks project "
                "(components: a databricks-workspace), without domain, site, "
                "dev or preview"
            )
        if has_components:
            counts = {
                kind: sum(1 for c in self.components if c.kind == kind)
                for kind in ("container-image", "lichess-bot")
            }
            if any(counts.values()):  # both zero is a research project
                for kind, count in counts.items():
                    if count != 1:
                        raise ValueError(f"components must hold exactly one {kind}, got {count}")
                pinned = self.bot.track == "pinned"
                if pinned and self.image.artifact.version is None:
                    raise ValueError(
                        "lichess-bot.track: pinned needs container-image.artifact.version, "
                        "the release tag to ship"
                    )
                if not pinned and self.image.artifact.version is not None:
                    raise ValueError(
                        "container-image.artifact.version pins a release; set "
                        "lichess-bot.track: pinned, or remove the version to follow every release"
                    )
            runners = sum(1 for c in self.components if c.kind == "task-runner")
            if runners > 1:
                raise ValueError(f"components may hold at most one task-runner, got {runners}")
            workspaces = sum(1 for c in self.components if c.kind == "databricks-workspace")
            if workspaces > 1:
                raise ValueError(
                    f"components may hold at most one databricks-workspace, got {workspaces}"
                )
            names = [c.name for c in self.datasets]
            if len(names) != len(set(names)):
                raise ValueError(f"dataset names must be unique, got {names}")
            if runners == 0 and any("task-runner" in c.writers for c in self.datasets):
                raise ValueError(
                    "a dataset with writers: [task-runner] needs a task-runner component"
                )
            runner = self.task_runner
            known = {d.name for d in self.datasets}
            for name, profile in (runner.profiles if runner else {}).items():
                unknown = sorted(set(profile.datasets) - known)
                if unknown:
                    raise ValueError(
                        f"task-runner profile {name}: datasets {', '.join(unknown)} are not "
                        "dataset components of this file"
                    )
        return self

    @property
    def kind(self) -> Literal["site", "bot", "research", "databricks"]:
        if not self.components:
            return "site"
        if any(isinstance(c, DatabricksWorkspace) for c in self.components):
            return "databricks"  # combining it with other components is refused by guardrails
        return "bot" if any(isinstance(c, LichessBot) for c in self.components) else "research"

    @property
    def image(self) -> ContainerImage:
        return next(c for c in self.components if isinstance(c, ContainerImage))

    @property
    def bot(self) -> LichessBot:
        return next(c for c in self.components if isinstance(c, LichessBot))

    @property
    def databricks(self) -> DatabricksWorkspace:
        return next(c for c in self.components if isinstance(c, DatabricksWorkspace))

    @property
    def task_runner(self) -> TaskRunner | None:
        return next((c for c in self.components if isinstance(c, TaskRunner)), None)

    @property
    def datasets(self) -> tuple[Dataset, ...]:
        return tuple(c for c in self.components if isinstance(c, Dataset))

    @field_validator("tags")
    @classmethod
    def _no_tool_tags(cls, value: dict[str, str]) -> dict[str, str]:
        source = {
            "Organization": "the project's GitHub owner in config/projects.yaml",
            "ManagedBy": "context.managed_by in config/tool.yaml",
        }
        stated = [key for key in TOOL_TAGS if key in value]
        if stated:
            raise ValueError(
                "; ".join(f"tags.{key} is set by jaws ({source[key]}); remove it" for key in stated)
            )
        return value

    @model_validator(mode="after")
    def _required_tags(self) -> SiteConfig:
        missing = [tag for tag in REQUIRED_TAGS if tag not in self.tags]
        if missing:
            raise ValueError(
                f"tags is missing the required keys {', '.join(missing)}; every site must "
                f"state all of {', '.join(REQUIRED_TAGS)} explicitly"
            )
        expected = {
            "Project": self.project,
            "Environment": ENVIRONMENT,
            "Repository": self.repository,
        }
        mismatched = [
            f"{key} must be {value!r}, got {self.tags[key]!r}"
            for key, value in expected.items()
            if self.tags[key] != value
        ]
        if mismatched:
            raise ValueError("tags: " + "; ".join(mismatched))
        empty = [key for key, value in self.tags.items() if not value.strip()]
        if empty:
            raise ValueError(f"tags: empty values for {', '.join(empty)}")
        return self

    @model_validator(mode="after")
    def _dev_differs(self) -> SiteConfig:
        if self.dev is not None and self.dev.domain == self.domain:
            raise ValueError("dev.domain must differ from domain")
        return self


def load_site_config(path: Path = SITE_FILE) -> SiteConfig:
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        raise ConfigError(f"site file not found at {path}") from exc
    return site_config_from_text(text, str(path))


def site_config_from_text(text: str, where: str) -> SiteConfig:
    """A site file's contents, validated; `where` names it in every error."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{where}: not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: expected a mapping at the top level")
    try:
        return SiteConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"{where}: {_format_validation_error(exc)}") from exc


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        message = error["msg"].removeprefix("Value error, ")
        lines.append(f"{location}: {message}")
    return "; ".join(lines)


def stamped_tags(
    tags: Mapping[str, str],
    organization: str,
    managed_by: str,
    platform_tags: Mapping[str, str],
) -> dict[str, str]:
    """The file's `tags`, the platform's own (`context.tags`) and the tool's own
    (TOOL_TAGS), none of which the file may state."""
    return {**tags, **platform_tags, "Organization": organization, "ManagedBy": managed_by}


def platform_tag_problems(tags: Mapping[str, str], settings: Settings) -> list[str]:
    """One problem per platform tag that a project file states."""
    platform = {key.casefold() for key in settings.context.tags}
    return [
        f"tags.{key} is set by jaws (context.tags in config/tool.yaml); remove it"
        for key in tags
        if key.casefold() in platform
    ]


def project_organization(config: SiteConfig, settings: Settings) -> str:
    """The Organization tag of a project's resources: the GitHub organization or user
    it is registered under in config/projects.yaml, or, for a project not onboarded
    (which only the stop commands accept), the owner of its repository."""
    if config.project in settings.projects:
        return settings.owner(config.project)
    return config.repository.split("/", 1)[0]


class Site(_Model):
    """A validated site plus everything derived from it and the tool configuration."""

    config: SiteConfig
    #: The root of every name (config/tool.yaml `context.name_root`).
    name_root: str
    #: The Organization tag: the project's GitHub owner (project_organization).
    organization: str
    managed_by: str
    #: The platform's own tags (config/tool.yaml `context.tags`).
    platform_tags: dict[str, str]
    zone_id: str
    state_bucket: str
    state_key: str
    region: str

    @classmethod
    def from_config(cls, config: SiteConfig, settings: Settings) -> Site:
        if config.kind != "site":
            raise ConfigError(
                f"{config.project} is a {config.kind} project, not a site; "
                "this command works on sites only"
            )
        problems: list[str] = platform_tag_problems(config.tags, settings)
        zone_suffix = "." + settings.dns.zone
        for label, domain in (
            ("domain", config.domain),
            ("dev.domain", config.dev and config.dev.domain),
        ):
            if domain and domain != settings.dns.zone and not domain.endswith(zone_suffix):
                problems.append(f"{label} {domain!r} is not under the zone {settings.dns.zone!r}")
        if problems:
            raise ConfigError("; ".join(problems))
        return cls(
            config=config,
            name_root=settings.context.name_root,
            organization=project_organization(config, settings),
            managed_by=settings.context.managed_by,
            platform_tags=dict(settings.context.tags),
            zone_id=settings.dns.zone_id,
            state_bucket=settings.state.bucket,
            state_key=settings.state_key(config.project, ENVIRONMENT),
            region=settings.state.region,
        )

    @property
    def project(self) -> str:
        return self.config.project

    @property
    def tags(self) -> dict[str, str]:
        """The tags every resource of the site carries (docs/tagging.md)."""
        return stamped_tags(
            self.config.tags, self.organization, self.managed_by, self.platform_tags
        )

    @property
    def bucket(self) -> str:
        return f"{self.name_root}-{self.project}"

    def role_name(self, role: Literal["plan", "preview", "apply"]) -> str:
        return f"{self.name_root}-{self.project}-ci-{role}"

    @property
    def domain(self) -> str:
        assert self.config.domain is not None  # from_config admits sites only
        return self.config.domain

    @property
    def site_section(self) -> SiteSection:
        assert self.config.site is not None  # from_config admits sites only
        return self.config.site

    @property
    def prod_url(self) -> str:
        return f"https://{self.domain}/"

    @property
    def dev_url(self) -> str | None:
        return f"https://{self.config.dev.domain}/" if self.config.dev else None

    @staticmethod
    def preview_prefix(pr: int) -> str:
        return f"{PREVIEWS_PREFIX}pr-{pr}/"

    def preview_url(self, pr: int) -> str:
        return f"https://pr-{pr}.preview.{self.domain}/"
