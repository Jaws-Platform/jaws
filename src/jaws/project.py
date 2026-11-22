"""A project file of any kind, with everything derived from it.

Sites keep using `Site` (site.py) for their commands. `Project` is the view
the kind-aware commands (validate, plan, apply, destroy) and the bot
commands work with: it derives the bot's names, parameters and roles the
same way the foundation stack and the container-instance module do.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from . import guardrails
from .components import (
    CPU_PROFILE,
    ContainerImage,
    DatabricksWorkspace,
    Dataset,
    LichessBot,
    TaskRunner,
    project_reader,
)
from .errors import ConfigError
from .settings import DatabricksProject, Settings
from .site import ENVIRONMENT, Site, SiteConfig, account_tags, organization_problems

Role = Literal["plan", "preview", "apply", "release", "task"]

#: Tag keys Databricks sets itself on clusters and workspaces; a project file may not state them.
DATABRICKS_RESERVED_TAGS = ("Vendor", "Creator", "ClusterName", "ClusterId", "Name")


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    config: SiteConfig
    organization: str
    managed_by: str
    state_bucket: str
    state_key: str
    region: str
    zone_id: str | None
    #: The project's approved Databricks settings (cost center, network, members), if any.
    databricks_approved: DatabricksProject | None = None

    @classmethod
    def from_config(
        cls, config: SiteConfig, settings: Settings, check_guardrails: bool = True
    ) -> Project:
        """`check_guardrails=False` is for the commands that only find and stop
        instances: an instance must stay stoppable after a guardrail change."""
        if config.kind == "site":
            site = Site.from_config(config, settings)
            return cls(
                config=config,
                organization=site.organization,
                managed_by=site.managed_by,
                state_bucket=site.state_bucket,
                state_key=site.state_key,
                region=site.region,
                zone_id=site.zone_id,
            )
        organization = settings.context.organization
        problems = organization_problems(config.tags, settings)
        own = f"/{organization}/{config.project}/"
        if config.kind == "databricks":
            reserved = sorted(set(config.tags) & set(DATABRICKS_RESERVED_TAGS))
            if reserved:
                problems.append(
                    f"tags may not use {', '.join(reserved)}: Databricks reserves those keys"
                )
        if config.kind == "bot":  # a research project has no lichess-bot to hold secrets
            for name, parameter in config.bot.secrets.items():
                if not parameter.startswith("/"):
                    continue  # relative: under own by construction; `bot` is refused at parse
                if not parameter.startswith(own):
                    problems.append(f"secrets.{name} must start with {own}, got {parameter!r}")
                elif parameter.startswith(f"{own}bot/"):
                    problems.append(
                        f"secrets.{name} must not live under {own}bot/, "
                        "which the release role can write"
                    )
        for dataset in config.datasets:
            name = f"{organization}-{config.project}-{dataset.name}"
            if dataset.bucket != name:
                problems.append(
                    f"dataset {dataset.name}: bucket must be {name!r} "
                    f"(<Organization>-<project>-<name>), got {dataset.bucket!r}"
                )
            if True:
                if len(name) > 63:
                    problems.append(
                        f"dataset {dataset.name}: bucket {name!r} exceeds 63 characters"
                    )
            for reader in dataset.readers:
                named = project_reader(reader)
                reader_project = settings.projects.get(named[0]) if named is not None else None
                if named is not None and (reader_project is None or reader_project.type == "site"):
                    problems.append(
                        f"dataset {dataset.name}: reader {reader!r} names project "
                        f"{named[0]!r}, which is not a bot, research or databricks project "
                        "in config/projects.yaml"
                    )
        runner = config.task_runner
        for name, profile in (runner.profiles if runner else {}).items():
            if profile.image is not None and profile.image not in settings.tasks.images:
                problems.append(
                    f"task-runner profile {name}: image {profile.image!r} is not pinned in "
                    "config/bots.yaml tasks.images"
                )
        if check_guardrails:
            problems += guardrails.check(config, settings)
        if problems:
            raise ConfigError("; ".join(problems))
        return cls(
            config=config,
            organization=organization,
            managed_by=settings.context.managed_by,
            state_bucket=settings.state.bucket,
            state_key=settings.state_key(config.project, ENVIRONMENT),
            region=settings.state.region,
            zone_id=None,
            databricks_approved=(
                settings.projects[config.project].databricks
                if config.kind == "databricks" and config.project in settings.projects
                else None
            ),
        )

    @property
    def project(self) -> str:
        return self.config.project

    @property
    def kind(self) -> Literal["site", "bot", "research", "databricks"]:
        return self.config.kind

    @property
    def tags(self) -> dict[str, str]:
        """The tags every resource of the project carries, as this account stamps them."""
        return account_tags(self.config.tags, self.organization, self.managed_by)

    @property
    def has_components(self) -> bool:
        """Bot and research projects are made of components; a site is not."""
        return self.config.kind != "site"

    @property
    def stack_kind(self) -> Literal["site", "bot", "databricks"]:
        """The Terraform stack that provisions it: research projects use the bot stack."""
        if self.config.kind == "databricks":
            return "databricks"
        return "site" if self.config.kind == "site" else "bot"

    @property
    def image(self) -> ContainerImage:
        self._require("bot")
        return self.config.image

    @property
    def bot(self) -> LichessBot:
        self._require("bot")
        return self.config.bot

    @property
    def secret_parameters(self) -> dict[str, str]:
        """Each secret's SSM parameter in this account: a name relative to the project
        is `/<organization>/<project>/<name>`; an absolute path is itself."""
        own = f"/{self.organization}/{self.config.project}/"
        return {
            name: value if value.startswith("/") else f"{own}{value}"
            for name, value in self.bot.secrets.items()
        }

    @property
    def databricks(self) -> DatabricksWorkspace:
        self._require("databricks")
        return self.config.databricks

    @property
    def databricks_tags(self) -> dict[str, str]:
        """The tags of the workspace and its clusters: the project's own, its cost center
        (from config/projects.yaml) and the workspace's name."""
        self._require("databricks")
        return {
            **self.tags,
            "CostCenter": self._databricks_guardrails().cost_center,
            "Workspace": f"{self.project}-{ENVIRONMENT}",
        }

    def _databricks_guardrails(self) -> DatabricksProject:
        if self.databricks_approved is None:
            raise ConfigError(f"{self.project} has no projects.{self.project}.databricks entry")
        return self.databricks_approved

    @property
    def site_bucket(self) -> str:
        self._require("site")
        return f"{self.organization}-{self.project}"

    @property
    def release_repository(self) -> str:
        """Where the engine's releases are published: the artifact's own
        repository when the file names one, else the project's."""
        return self.image.artifact.repository or self.config.repository

    @property
    def pinned_version(self) -> str | None:
        """The release a `track: pinned` bot ships; None when it follows every release."""
        return self.image.artifact.version if self.bot.track == "pinned" else None

    @property
    def image_repository(self) -> str:
        return f"{self.organization}-{self.project}"

    @property
    def bot_name(self) -> str:
        return f"{self.organization}-{self.project}-bot"

    @property
    def records_bucket(self) -> str:
        return f"{self.organization}-{self.project}-records"

    @property
    def vpc_name(self) -> str:
        return f"{self.organization}-{self.project}"

    @property
    def parameter_prefix(self) -> str:
        return f"/{self.organization}/{self.project}/bot"

    @property
    def log_group(self) -> str:
        return self.parameter_prefix

    @property
    def task_runner(self) -> TaskRunner | None:
        self._require_components()
        return self.config.task_runner

    @property
    def task_name(self) -> str:
        """The task launch template, instance role, profile and security group."""
        return f"{self.organization}-{self.project}-task"

    @property
    def task_template(self) -> str:
        return self.task_name

    def profile_task_name(self, profile: str) -> str:
        """A profile's launch template, instance role and profile: `cpu` is
        `task_name`, every other `<task_name>-<profile>`."""
        return self.task_name if profile == CPU_PROFILE else f"{self.task_name}-{profile}"

    @property
    def task_log_group(self) -> str:
        return f"/{self.organization}/{self.project}/tasks"

    @property
    def task_bucket(self) -> str:
        return f"{self.organization}-{self.project}-tasks"

    @property
    def task_prefix(self) -> str:
        return "tasks/"

    @property
    def datasets(self) -> tuple[Dataset, ...]:
        self._require_components()
        return self.config.datasets

    def dataset_bucket(self, name: str) -> str:
        return f"{self.organization}-{self.project}-{name}"

    def parameter(self, name: str) -> str:
        return f"{self.parameter_prefix}/{name}"

    def role_name(self, role: Role) -> str:
        return f"{self.organization}-{self.project}-ci-{role}"

    @property
    def profile_url(self) -> str | None:
        user = self.bot.lichess_user
        return f"https://lichess.org/@/{user}" if user else None

    def _require(self, kind: Literal["site", "bot", "databricks"]) -> None:
        if self.kind != kind:
            raise ConfigError(f"{self.project} is not a {kind} project")

    def _require_components(self) -> None:
        if not self.has_components:
            raise ConfigError(f"{self.project} has no components (it is a site project)")
