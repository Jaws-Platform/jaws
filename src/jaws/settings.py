"""The tool configuration: the `config/` directory, loaded once and passed to every command.

It describes how the tool runs (Terraform version, module family pins, state bucket,
organisation constants, ECR, sync headers), the accounts it knows, and every project
onboarded to it, as opposed to what one project is, which lives in each project
repository's jaws.yaml.

The directory's YAML files are read as one document: each file holds some of its
top-level sections, and a section may be in only one file. Which file holds a section
is organisation only (config/README.md lists them); one file holding every section is
read the same way.
"""

from __future__ import annotations

import ipaddress
import os
import re
import zoneinfo
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .components import check_prefixes
from .errors import ConfigError

ENV_CONFIG_PATH = "JAWS_CONFIG"
IMAGE_CONFIG_PATH = Path("/etc/jaws/config")
LOCAL_CONFIG_PATH = Path("config")

_DURATION = re.compile(r"^(\d+)([smh])$")
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600}


def parse_duration(value: str) -> int:
    """Seconds for a Terraform-style duration such as `120s`, `15m` or `1h`."""
    match = _DURATION.match(value)
    if not match:
        raise ValueError(f"{value!r} is not a duration like 120s, 15m or 1h")
    return int(match.group(1)) * _DURATION_UNITS[match.group(2)]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolSection(_Section):
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_format: Literal["console", "json"] = "console"


class TerraformSection(_Section):
    lock_timeout: str = "120s"
    plan_timeout: str = "15m"

    @field_validator("lock_timeout", "plan_timeout")
    @classmethod
    def _duration(cls, value: str) -> str:
        parse_duration(value)
        return value

    @property
    def plan_timeout_seconds(self) -> int:
        return parse_duration(self.plan_timeout)


class StateSection(_Section):
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    region: str = Field(pattern=r"^[a-z]{2}-[a-z]+-\d$")
    key_template: str

    @field_validator("key_template")
    @classmethod
    def _placeholders(cls, value: str) -> str:
        for placeholder in ("{project}", "{environment}"):
            if placeholder not in value:
                raise ValueError(f"key_template must contain {placeholder}")
        if value.startswith("/") or "*" in value or "?" in value:
            raise ValueError("key_template must be a relative key without IAM wildcards")
        return value


#: What an account in the registry is for. A management account holds AWS
#: Organizations and IAM Identity Center; the others can hold workloads.
ACCOUNT_TYPES = ("management", "development", "staging", "production")
_ACCOUNT_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
#: A GitHub organization or user name, as GitHub spells it.
_GITHUB_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")


class Account(_Section):
    """One account in the registry (`aws.accounts.<name>`)."""

    type: Literal["management", "development", "staging", "production"]
    account_id: str = Field(pattern=r"^\d{12}$")
    #: The owner's Identity Center admin role in the account: the break-glass
    #: principal of the hardened bucket policies, for the primary account.
    admin_role_arn: str | None = Field(
        default=None,
        pattern=r"^arn:aws:iam::\d{12}:role/aws-reserved/sso\.amazonaws\.com/AWSReservedSSO_[A-Za-z0-9_-]+$",
    )
    description: str | None = None

    @model_validator(mode="after")
    def _admin_role_is_in_the_account(self) -> Account:
        if self.admin_role_arn and not self.admin_role_arn.startswith(
            f"arn:aws:iam::{self.account_id}:role/"
        ):
            raise ValueError(
                f"admin_role_arn {self.admin_role_arn} is not a role in account {self.account_id}"
            )
        return self


class AwsSection(_Section):
    """The account registry (config/aws.yaml): every account jaws knows about,
    and `primary`, the one it builds in."""

    primary: str
    accounts: dict[str, Account] = Field(min_length=1)

    @field_validator("accounts")
    @classmethod
    def _accounts_are_named_and_distinct(cls, value: dict[str, Account]) -> dict[str, Account]:
        seen: dict[str, str] = {}
        for name, account in value.items():
            if not _ACCOUNT_NAME.match(name):
                raise ValueError(f"account name {name!r} must be lowercase kebab-case")
            if account.account_id in seen:
                raise ValueError(
                    f"accounts {seen[account.account_id]} and {name} are both "
                    f"{account.account_id}: every account in the registry is distinct"
                )
            seen[account.account_id] = name
        management = [n for n, a in value.items() if a.type == "management"]
        if len(management) > 1:
            raise ValueError(
                f"accounts {', '.join(management)} are all of type management; "
                "an organization has one management account"
            )
        return value

    @model_validator(mode="after")
    def _primary_is_a_workload_account(self) -> AwsSection:
        if self.primary not in self.accounts:
            raise ValueError(
                f"primary {self.primary!r} is not in accounts ({', '.join(self.accounts)})"
            )
        if self.primary_account.type == "management":
            raise ValueError(
                f"primary {self.primary!r} is the management account; jaws builds in a "
                "development, staging or production account"
            )
        return self

    @property
    def primary_account(self) -> Account:
        """The account jaws builds in: its foundation and every project."""
        return self.accounts[self.primary]

    @property
    def account_id(self) -> str:
        """The primary account's ID."""
        return self.primary_account.account_id

    @property
    def admin_role_arn(self) -> str | None:
        """The owner's admin role in the primary account."""
        return self.primary_account.admin_role_arn

    def of_type(self, account_type: str) -> dict[str, Account]:
        """The registry's accounts of one type, by name, in file order."""
        return {n: a for n, a in self.accounts.items() if a.type == account_type}


class ContextSection(_Section):
    #: The root of every name the tool gives (`<name_root>-<project>-...`, the
    #: `<name_root>-infra-ci-*` roles). A name only, never a tag value.
    name_root: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    #: The Organization tag of the tool's own stacks: the GitHub owner of this
    #: repository. A project's resources carry its own owner (`projects`).
    organization: str = Field(pattern=_GITHUB_OWNER.pattern)
    owner: str = Field(pattern=_GITHUB_OWNER.pattern)
    #: The ManagedBy tag the tool stamps on everything it builds.
    managed_by: str = Field(default="JAWS", pattern=r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$")


class DnsSection(_Section):
    zone: str = Field(pattern=r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
    zone_id: str = Field(pattern=r"^Z[A-Z0-9]{5,31}$")


class EcrSection(_Section):
    repository: str = Field(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
    keep_release_images: int = Field(ge=1)
    expire_untagged_after_days: int = Field(ge=1)


class SyncSection(_Section):
    cache_control: str = "public, max-age=3600"  # assets without a content hash
    preview_cache_control: str = "public, max-age=300"
    #: Pages: always fresh after a publish.
    html_cache_control: str = "public, max-age=0, must-revalidate"
    #: `site.immutable_paths`.
    immutable_cache_control: str = "public, max-age=31536000, immutable"


class BotSection(_Section):
    """How bot projects run: the health check and the records layout prefix."""

    #: Bot projects (components: container-image + lichess-bot): the container
    #: must log this within `health_seconds` after a deploy, or it is rolled back.
    health_log_pattern: str = "awaiting challenges"
    health_seconds: int = Field(default=90, ge=10, le=600)
    records_prefix: str = Field(pattern=r"^([a-z0-9][a-z0-9-]*/)+$")
    #: Zones of the bot VPC's public subnets, in order (the bot uses the first).
    #: Spot tasks try each, so list every zone that offers their type; append
    #: only, since subnets are numbered by position.
    availability_zones: tuple[str, ...] = Field(min_length=1, max_length=6)
    #: How long a build waits for a release's assets to be attached: release
    #: workflows publish first and upload their build outputs afterwards.
    asset_wait: str = "30m"
    #: The pinned Amazon Linux 2023 image per architecture, by its Amazon-owned image
    #: name (e.g. al2023-ami-2023.9.20251027.0-kernel-6.1-x86_64). A bot's instance
    #: changes OS only when its pin changes; an architecture without a pin follows
    #: the latest image, which replaces the instance on every Amazon release.
    amis: dict[Literal["x86_64", "arm64"], str] = {}

    @field_validator("asset_wait")
    @classmethod
    def _asset_wait(cls, value: str) -> str:
        parse_duration(value)
        return value

    @property
    def asset_wait_seconds(self) -> int:
        return parse_duration(self.asset_wait)

    @field_validator("amis")
    @classmethod
    def _ami_names(cls, value: dict[str, str]) -> dict[str, str]:
        for architecture, name in value.items():
            if name.startswith("ami-") or not re.fullmatch(r"[A-Za-z0-9._()/-]{3,128}", name):
                raise ValueError(
                    f"{architecture}: {name!r} must be an Amazon image name like "
                    f"al2023-ami-2023.9.20251027.0-kernel-6.1-{architecture}, not an ID"
                )
            if not name.endswith(f"-{architecture}"):
                raise ValueError(f"{architecture}: {name!r} must end in -{architecture}")
        return value


class TaskLimits(_Section):
    """What any project file may ask for. `project.py` checks files against these."""

    #: Longest a task may run. GitHub stops a job at six hours.
    max_hours: int = Field(ge=1)
    max_vcpus: int = Field(ge=1)
    root_volume_gb: int = Field(ge=1)


class DatasetRetention(_Section):
    """The centrally approved retention of one dataset bucket.

    A consumer's dataset component must request exactly these values.
    """

    #: The dataset's `prefix` that `write_once` and `expire_prefixes` are
    #: relative to. Required when any retention is set; the file's own prefix
    #: must then equal it. An empty entry imposes no prefix.
    prefix: str | None = None
    write_once: tuple[str, ...] = ()
    expire_prefixes: dict[str, int] = {}
    expire_noncurrent_days: int | None = None
    versioning: bool = False

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, value: str | None) -> str | None:
        if value is not None:
            check_prefixes((value,))
        return value

    @field_validator("write_once")
    @classmethod
    def _write_once(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return check_prefixes(value)

    @field_validator("expire_prefixes")
    @classmethod
    def _expire_prefixes(cls, value: dict[str, int]) -> dict[str, int]:
        check_prefixes(tuple(value))
        return value

    @model_validator(mode="after")
    def _retention_needs_a_prefix(self) -> DatasetRetention:
        relative = self.write_once or self.expire_prefixes
        if (relative or self.expire_noncurrent_days is not None) and self.prefix is None:
            raise ValueError(
                "prefix is required when write_once, expire_prefixes or "
                "expire_noncurrent_days is set: the dataset prefix they apply to"
            )
        return self


#: The default CIDR of the bot VPC; a Databricks project's `vpc_cidr` may not overlap it.
BOT_VPC_CIDR = "10.0.0.0/16"
#: The longest project name with a `databricks` entry: IAM role names are limited
#: to 64 characters and `<name_root>-<project>-databricks-cross-account` must fit.
DATABRICKS_PROJECT_NAME_MAX = 21
PLACEHOLDER_UUID = "00000000-0000-0000-0000-000000000000"

_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_UUID = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _check_emails(value: tuple[str, ...]) -> tuple[str, ...]:
    for email in value:
        if not _EMAIL.match(email):
            raise ValueError(f"{email!r} is not an email address")
    return value


class DatabricksPolicy(_Section):
    """One cluster policy, centrally reviewed; a project lists the names it gets."""

    description: str
    #: The Databricks policy definition: attribute path to its rule.
    definition: dict[str, Any]


class DatabricksProject(_Section):
    """What one project's Databricks workspace is approved for."""

    compute_policies: tuple[str, ...]
    cost_center: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    #: Allocated centrally so IP capacity is owned here and overlaps are checkable.
    vpc_cidr: str
    #: Workspace admins, by email. Central because admins can change cluster policies,
    #: entitlements and grants; plain users are listed in the project's own file.
    admins: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _users_moved(cls, data: Any) -> Any:
        if isinstance(data, dict) and "users" in data:
            raise ValueError(
                "`users` no longer lives in the tool configuration: "
                "list the workspace users in the "
                "project's own jaws.yaml, under the databricks-workspace "
                "component (users: [name@example.com]); only admins are set here"
            )
        return data

    @field_validator("vpc_cidr")
    @classmethod
    def _vpc_cidr(cls, value: str) -> str:
        try:
            network = ipaddress.IPv4Network(value, strict=True)
        except ValueError as exc:
            raise ValueError(f"vpc_cidr {value!r} is not an IPv4 network: {exc}") from exc
        if not 16 <= network.prefixlen <= 20:
            raise ValueError(f"vpc_cidr {value!r} must be between /16 and /20")
        return value

    @field_validator("admins")
    @classmethod
    def _emails(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _check_emails(value)


class DatabricksSection(_Section):
    """The Databricks account the workspace projects live in (the `databricks:` section)."""

    #: False until the owner has created the service principal and set its secret;
    #: the foundation's Databricks resources and the live checks wait for true.
    enabled: bool
    account_id: str = Field(pattern=_UUID)
    client_id: str = Field(pattern=_UUID)
    secret_parameter: str = "/jaws/databricks/client-secret"
    metastore_name: str = "jaws-us-east-1"
    metastore_admins: tuple[str, ...] = Field(min_length=1)
    #: The pinned Amazon Linux 2023 arm64 image name of the NAT instance.
    nat_ami: str
    #: The deployment-name prefix Databricks configured for this account, if any. With
    #: one, a workspace's URL is `<prefix>-<project>`; without, Databricks picks the URL.
    deployment_name_prefix: str | None = Field(default=None, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    audit_bucket: str = "jaws-databricks-audit-logs"
    events_prefix: str = Field(default="events/", pattern=r"^([a-z0-9][a-z0-9-]*/)+$")
    compute_policies: dict[str, DatabricksPolicy] = {}
    readiness_timeout: str = "20m"
    #: The shared-objects host's URL (foundation/databricks.tf, `databricks_shared_host`):
    #: the workspace the data-access stack binds and grants onboarded datasets through.
    #: Databricks picks it when the workspace is created; the foundation checks it matches.
    shared_host_url: str | None = Field(
        default=None, pattern=r"^https://[a-z0-9.-]+\.cloud\.databricks\.com$"
    )

    @field_validator("metastore_admins")
    @classmethod
    def _emails(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _check_emails(value)

    @field_validator("nat_ami")
    @classmethod
    def _nat_ami(cls, value: str) -> str:
        if value.startswith("ami-") or not re.fullmatch(r"[A-Za-z0-9._()/-]{3,128}", value):
            raise ValueError(f"{value!r} must be an Amazon image name, not an ID")
        if not value.endswith("-arm64"):
            raise ValueError(f"{value!r} must be an arm64 image (end in -arm64)")
        return value

    @field_validator("compute_policies")
    @classmethod
    def _policy_names(cls, value: dict[str, DatabricksPolicy]) -> dict[str, DatabricksPolicy]:
        for name in value:
            if not _KEBAB.match(name):
                raise ValueError(f"compute_policies: name {name!r} must be kebab-case")
            if "autotermination_minutes" not in value[name].definition:
                raise ValueError(
                    f"compute_policies.{name}.definition must set autotermination_minutes "
                    "(the workspace module rejects a policy without it)"
                )
        return value

    @field_validator("readiness_timeout")
    @classmethod
    def _readiness_timeout(cls, value: str) -> str:
        parse_duration(value)
        return value

    @model_validator(mode="after")
    def _filled_in_once_enabled(self) -> DatabricksSection:
        """Once enabled, no placeholder may remain: the foundation would make the
        @example.com addresses metastore admins (its plan refuses the same)."""
        if not self.enabled:
            return self
        ids = {
            "account_id": "the Databricks account ID",
            "client_id": "the service principal's application (client) ID",
        }
        problems = [
            f"databricks.{name} is still the nil UUID placeholder; fill in {what}"
            for name, what in ids.items()
            if getattr(self, name).lower() == PLACEHOLDER_UUID
        ]
        admins = [e for e in self.metastore_admins if e.lower().endswith("@example.com")]
        if admins:
            problems.append(
                f"databricks.metastore_admins still holds the placeholder {', '.join(admins)}; "
                "replace it with the owner's real email (an account user)"
            )
        if problems:
            raise ValueError("; ".join(problems) + " (or set databricks.enabled back to false)")
        return self

    @property
    def readiness_timeout_seconds(self) -> int:
        return parse_duration(self.readiness_timeout)

    @property
    def has_placeholder_ids(self) -> bool:
        """True while `account_id` or `client_id` is still the nil UUID."""
        return PLACEHOLDER_UUID in (self.account_id.lower(), self.client_id.lower())


#: Where the monitoring stack's owner-set secrets live in SSM: the Grafana admin
#: and each Slack channel's webhook (`jaws monitoring secrets`). Never Terraform's.
MONITORING_SECRETS_PREFIX = "/jaws/monitoring/"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
#: The monitoring module's alert thresholds (spec 6.8) by name: True for a
#: warning and critical pair, False for a warning alone. An override replaces
#: the module's whole pair, so it states both.
MONITORING_THRESHOLDS = {
    "cpu_percent": True,
    "cpu_credits_percent": True,
    "memory_percent": True,
    "swap_percent": True,
    "disk_percent": True,
    "disk_full_days": True,
    "inodes_percent": True,
    "prometheus_size_percent": False,
    "prometheus_history_days": False,
    "container_restarts": True,
    "tls_days": True,
    "os_release_update_days": False,
    "normalizer_hours": True,
    "aws_charge_days": True,
    "databricks_delivery_hours": True,
    "cost_sync_hours": True,
    "anomaly_ratio": True,
    "untagged_daily_usd": False,
}
_ON_HOUR = re.compile(r"^([01][0-9]|2[0-3]):00$")
_OFF_HOUR = re.compile(r"^(([01][0-9]|2[0-3]):00|24:00)$")
_MONITORING_AMI = re.compile(r"^al2023-ami-.+-arm64$")
#: A Graviton (arm64) type, which an arm64 image needs: a `g` after the
#: generation (t9g, m8gd, c7gn, g5g), never c7i or g6.
_GRAVITON_TYPE = re.compile(r"^[a-z]+[0-9]+[a-z]*g[a-z]*\.[a-z0-9]+$")
_S3_BUCKET = r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$"
_SLACK_CHANNEL = re.compile(r"^[a-z][a-z0-9-]{0,29}$")
_SSM_NAME = re.compile(r"^/[A-Za-z0-9_.\-/]+$")
_FQDN = r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"

_Usd = Annotated[float, Field(gt=0)]


class MonitoringSchedule(_Section):
    """The node's off-hours (spec 6.10): on from `on` to `off` on `days`, in
    `timezone`, and stopped otherwise. Raw cron is deliberately not accepted."""

    timezone: str
    days: tuple[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"], ...] = Field(min_length=1)
    on: str
    #: Up to 24:00, the midnight that ends the day.
    off: str

    @field_validator("timezone")
    @classmethod
    def _iana_zone(cls, value: str) -> str:
        problem = (
            f"monitoring.schedule.timezone {value!r} is not an IANA time zone, "
            "such as America/Denver"
        )
        try:
            zoneinfo.ZoneInfo(value)
        except zoneinfo.ZoneInfoNotFoundError:
            if not zoneinfo.available_timezones():
                problem += " (this system has no time zone database to check it against: tzdata)"
            raise ValueError(problem) from None
        except ValueError:
            raise ValueError(problem) from None
        return value

    @field_validator("days")
    @classmethod
    def _unique_days(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        twice = sorted({d for d in value if value.count(d) > 1}, key=WEEKDAYS.index)
        if twice:
            raise ValueError(f"monitoring.schedule.days lists {', '.join(twice)} more than once")
        return value

    @field_validator("on", "off", mode="before")
    @classmethod
    def _quoted(cls, value: Any, info: ValidationInfo) -> Any:
        if isinstance(value, int):
            raise ValueError(
                f'monitoring.schedule.{info.field_name} must be quoted, such as "20:00": '
                f"YAML reads a bare 20:00 as a number of minutes ({value})"
            )
        return value

    @field_validator("on")
    @classmethod
    def _on_hour(cls, value: str) -> str:
        if not _ON_HOUR.match(value):
            raise ValueError(
                f"monitoring.schedule.on {value!r} must be a whole hour, HH:00, from 00:00 to 23:00"
            )
        return value

    @field_validator("off")
    @classmethod
    def _off_hour(cls, value: str) -> str:
        if not _OFF_HOUR.match(value):
            raise ValueError(
                f"monitoring.schedule.off {value!r} must be a whole hour, HH:00, or 24:00 "
                "for the midnight that ends the day"
            )
        return value

    @model_validator(mode="after")
    def _one_window_a_day(self) -> MonitoringSchedule:
        on, off = int(self.on[:2]), int(self.off[:2])
        if off <= on:
            raise ValueError(
                f"monitoring.schedule.off {self.off} is not after monitoring.schedule.on "
                f"{self.on}: the node runs from on to off within each day, so there are no "
                "overnight windows (off may be 24:00, the midnight that ends the day)"
            )
        if (on, off) == (0, 24):
            raise ValueError(
                "monitoring.schedule.on 00:00 and monitoring.schedule.off 24:00 would start and "
                "stop the node at the same midnight; leave out monitoring.schedule to run all day"
            )
        if off - on < 4:
            raise ValueError(
                f"monitoring.schedule.off {self.off} is {off - on} hours after "
                f"monitoring.schedule.on {self.on}; the node runs at least 4 hours a day"
            )
        return self


class MonitoringBudgets(_Section):
    """Monthly budgets in USD: the total, by project, and by account (ID or name)."""

    total: _Usd | None = None
    projects: dict[str, _Usd] = {}
    accounts: dict[str, _Usd] = {}


class MonitoringCost(_Section):
    """The cost half of the platform: the billing bucket (the foundation's) and
    the providers whose bills land in it."""

    #: Bucket names are global, so it carries the account ID.
    bucket: str = Field(pattern=_S3_BUCKET)
    #: Deny overwrites and deletes under raw/; on once the first deliveries are checked.
    protect_raw: bool = False
    #: The organization's AWS bill (the owner's billing-export/ root delivers it).
    aws: bool = True
    #: Databricks' billing, exported by a job on the shared workspace.
    databricks: bool = False
    budgets: MonitoringBudgets = MonitoringBudgets()
    #: A day must also be this many USD over its 14-day median to be an anomaly.
    anomaly_floor_usd: float = Field(default=2, ge=0)

    @model_validator(mode="after")
    def _a_provider(self) -> MonitoringCost:
        if not (self.aws or self.databricks):
            raise ValueError(
                "monitoring.cost.aws and monitoring.cost.databricks are both false; turn one on, "
                "or leave out monitoring.cost for a host-only node"
            )
        return self


class MonitoringSlack(_Section):
    """Where alerts go: each channel is the SSM parameter holding its Slack
    incoming-webhook URL, and each route sends an area's alerts to a channel."""

    channels: dict[str, str] = Field(min_length=1)
    routes: dict[Literal["host", "pipeline", "cost"], str]

    @field_validator("channels")
    @classmethod
    def _channels(cls, value: dict[str, str]) -> dict[str, str]:
        for name, parameter in value.items():
            if not _SLACK_CHANNEL.match(name):
                raise ValueError(
                    f"monitoring.slack.channels.{name}: a channel is named with a lowercase "
                    "letter, then lowercase letters, digits or - (at most 30)"
                )
            if not (parameter.startswith(MONITORING_SECRETS_PREFIX) and _SSM_NAME.match(parameter)):
                raise ValueError(
                    f"monitoring.slack.channels.{name} {parameter!r} must be an SSM parameter "
                    f"under {MONITORING_SECRETS_PREFIX}, such as "
                    f"{MONITORING_SECRETS_PREFIX}slack/{name}"
                )
        return value

    @model_validator(mode="after")
    def _routes_name_channels(self) -> MonitoringSlack:
        if "host" not in self.routes:
            raise ValueError(
                "monitoring.slack.routes.host is required: the root notification policy "
                "sends host alerts, and every area without a route, there"
            )
        for area, channel in self.routes.items():
            if channel not in self.channels:
                raise ValueError(
                    f"monitoring.slack.routes.{area} names channel {channel!r}, which is not in "
                    f"monitoring.slack.channels ({', '.join(self.channels)})"
                )
        return self


class MonitoringThreshold(_Section):
    warning: float
    critical: float | None = None


class MonitoringSection(_Section):
    """The monitoring and cost platform (config/monitoring.yaml): the node the
    monitoring/ stack runs, the foundation's billing bucket, and where alerts go.
    Each optional part is off while it is left out."""

    instance_type: str = "t9g.medium"
    #: The pinned Amazon Linux 2023 arm64 image, by name: patching is a PR bumping it.
    ami: str
    #: Public HTTPS at this name in the dns zone; None keeps the node private.
    domain: str | None = Field(default=None, pattern=_FQDN)
    #: Daily snapshots of the data volume.
    snapshots: bool = False
    #: None runs the node all day.
    schedule: MonitoringSchedule | None = None
    #: None is a host-only node: no cost data, dashboards or rules.
    cost: MonitoringCost | None = None
    #: None notifies nobody: alerts show in Grafana only.
    slack: MonitoringSlack | None = None
    #: Overrides of the module's thresholds, by name.
    thresholds: dict[str, MonitoringThreshold] = {}

    @field_validator("instance_type")
    @classmethod
    def _graviton(cls, value: str) -> str:
        if not _GRAVITON_TYPE.match(value):
            raise ValueError(
                f"monitoring.instance_type {value!r} must be a Graviton (arm64) type such as "
                "t9g.medium: monitoring.ami is an arm64 image"
            )
        return value

    @field_validator("ami")
    @classmethod
    def _ami(cls, value: str) -> str:
        if not _MONITORING_AMI.match(value):
            raise ValueError(
                f"monitoring.ami {value!r} must be an Amazon Linux 2023 arm64 image name, "
                "al2023-ami-<release>-kernel-<version>-arm64, not an ID"
            )
        return value

    @field_validator("thresholds")
    @classmethod
    def _thresholds(cls, value: dict[str, MonitoringThreshold]) -> dict[str, MonitoringThreshold]:
        for name, threshold in value.items():
            if name not in MONITORING_THRESHOLDS:
                raise ValueError(
                    f"monitoring.thresholds.{name} is not one of the module's thresholds "
                    f"({', '.join(MONITORING_THRESHOLDS)})"
                )
            paired = MONITORING_THRESHOLDS[name]
            if paired and threshold.critical is None:
                raise ValueError(
                    f"monitoring.thresholds.{name} needs both warning and critical: an "
                    "override replaces the module's pair"
                )
            if not paired and threshold.critical is not None:
                raise ValueError(f"monitoring.thresholds.{name} has a warning only, no critical")
        return value


class ProjectGuardrails(_Section):
    """What one project's task launch role and buckets are approved for.

    Reviewed in this repository; the project's own file cannot widen any of it.
    """

    instance_types: tuple[str, ...] = ()
    task_profiles: tuple[str, ...] = ()
    datasets: dict[str, DatasetRetention] = {}
    #: Per-project override of `tasks.max_run_cost_usd`.
    max_run_cost_usd: float | None = None
    #: Present for a Databricks workspace project (needs the top-level `databricks`).
    databricks: DatabricksProject | None = None


#: What a project is, which decides the stack and roles the foundation gives it:
#: a static site, a released Lichess bot, a research project (remote tasks and
#: datasets, never released; the bot stack without a release role), or a
#: Databricks workspace.
PROJECT_TYPES = ("site", "bot", "research", "databricks")
_PROJECT_KEY = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class OnboardedProject(ProjectGuardrails):
    """One project in config/projects.yaml: who it is, and what it is approved for
    (the guardrails it inherits)."""

    description: str = Field(min_length=1)
    type: Literal["site", "bot", "research", "databricks"]
    #: The repository's name under its owner (`projects.<owner>`).
    repository: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    #: Its numeric GitHub ID, which the CI roles' OIDC trust names.
    repository_id: str = Field(pattern=r"^\d+$")
    #: A site's domain.
    domain: str | None = Field(
        default=None, pattern=r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
    )

    @model_validator(mode="after")
    def _fields_fit_the_type(self) -> OnboardedProject:
        if self.type == "site":
            if self.domain is None:
                raise ValueError("a site needs its domain")
            approved = [
                name
                for name in ("instance_types", "task_profiles", "datasets", "max_run_cost_usd")
                if getattr(self, name)
            ]
            if approved:
                raise ValueError(
                    f"a site runs no tasks and has no datasets: drop {', '.join(approved)}"
                )
        elif self.domain is not None:
            raise ValueError(f"only a site has a domain, and this is a {self.type} project")
        if (self.databricks is None) == (self.type == "databricks"):
            raise ValueError(
                "a databricks project needs its databricks entry"
                if self.type == "databricks"
                else "only a databricks project has a databricks entry, and this is a "
                f"{self.type} project"
            )
        return self


class GithubOwner(_Section):
    """A GitHub organization or user (`projects.<owner>`) and the projects whose
    repositories it owns."""

    #: The owner's numeric GitHub ID (`gh api users/<owner> --jq .id`).
    owner_id: str = Field(pattern=r"^\d+$")
    projects: dict[str, OnboardedProject] = Field(min_length=1)

    @field_validator("projects")
    @classmethod
    def _keys_are_kebab_case(
        cls, value: dict[str, OnboardedProject]
    ) -> dict[str, OnboardedProject]:
        for key in value:
            if not _PROJECT_KEY.match(key):
                raise ValueError(f"project key {key!r} must be lowercase kebab-case")
        return value


class TasksSection(_Section):
    """How `task run` sets up and follows task instances (component `task-runner`)."""

    #: The Rust toolchain every task instance installs with rustup. Pin a
    #: version: changing it is a new launch template version, not a rebuild.
    rust_toolchain: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]*$")
    #: Seconds between polls of a task's output and status.
    poll_seconds: int = Field(default=5, ge=1, le=60)
    #: Pinned images for task profiles, by key (a profile's `image`): the
    #: Amazon-owned image *name*, resolved to its ID by the bot stack. A
    #: profile's image changes only when its pin changes.
    images: dict[str, str] = {}
    #: What any project file may ask for.
    limits: TaskLimits
    #: Worst-case cost of one task; above it, the launch is refused.
    max_run_cost_usd: float = Field(gt=0)

    @field_validator("images")
    @classmethod
    def _image_names(cls, value: dict[str, str]) -> dict[str, str]:
        for key, name in value.items():
            if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", key):
                raise ValueError(f"images: key {key!r} must be kebab-case")
            if name.startswith("ami-") or not re.fullmatch(r"[A-Za-z0-9._()/ -]{3,128}", name):
                raise ValueError(f"images.{key}: {name!r} must be an Amazon image name, not an ID")
        return value


class Settings(_Section):
    """The whole tool configuration (every file of config/)."""

    tool: ToolSection = ToolSection()
    terraform: TerraformSection = TerraformSection()
    state: StateSection
    aws: AwsSection
    context: ContextSection
    dns: DnsSection
    ecr: EcrSection
    sync: SyncSection = SyncSection()
    bot: BotSection
    tasks: TasksSection
    #: Every onboarded project, grouped by the GitHub owner of its repository: the
    #: `projects` section. `projects` (the property) indexes them by key.
    owners: dict[str, GithubOwner] = Field(default_factory=dict, alias="projects")
    databricks: DatabricksSection | None = None
    #: The monitoring and cost platform (config/monitoring.yaml); None builds none of it.
    monitoring: MonitoringSection | None = None

    _projects: dict[str, OnboardedProject] = PrivateAttr(default_factory=dict)
    _project_owners: dict[str, str] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _index_projects(self) -> Settings:
        projects: dict[str, OnboardedProject] = {}
        owners: dict[str, str] = {}
        for owner, group in self.owners.items():
            if not _GITHUB_OWNER.match(owner):
                raise ValueError(f"projects: {owner!r} is not a GitHub organization or user name")
            for key, project in group.projects.items():
                if key in projects:
                    raise ValueError(
                        f"project {key!r} is onboarded under both {owners[key]} and {owner}: "
                        "a project key is unique across owners"
                    )
                projects[key] = project
                owners[key] = owner
        self._projects = projects
        self._project_owners = owners
        return self

    @property
    def projects(self) -> dict[str, OnboardedProject]:
        """Every onboarded project by its key, whichever owner it is under."""
        return self._projects

    def repository(self, project: str) -> str:
        """An onboarded project's repository, as `<owner>/<name>`."""
        return f"{self.owner(project)}/{self._projects[project].repository}"

    def owner(self, project: str) -> str:
        """The GitHub organization or user an onboarded project is registered under."""
        return self._project_owners[project]

    @model_validator(mode="after")
    def _databricks_consistency(self) -> Settings:
        projects = {n: g.databricks for n, g in self.projects.items() if g.databricks}
        if self.databricks is None:
            if projects:
                raise ValueError(
                    f"projects {', '.join(sorted(projects))} have a databricks entry "
                    "but no databricks section is configured (config/databricks.yaml)"
                )
            return self
        central = self.databricks.compute_policies
        taken: list[tuple[str, ipaddress.IPv4Network]] = [
            ("the bot VPC", ipaddress.IPv4Network(BOT_VPC_CIDR))
        ]
        for name, project in sorted(projects.items()):
            if len(name) > DATABRICKS_PROJECT_NAME_MAX:
                raise ValueError(
                    f"project {name!r} has a databricks entry, so its name may be at most "
                    f"{DATABRICKS_PROJECT_NAME_MAX} characters (IAM role name limit)"
                )
            for policy in project.compute_policies:
                if policy not in central:
                    raise ValueError(
                        f"projects.{name}.databricks: compute policy {policy!r} is not "
                        "defined under databricks.compute_policies"
                    )
            network = ipaddress.IPv4Network(project.vpc_cidr)
            for other, other_network in taken:
                if network.overlaps(other_network):
                    raise ValueError(
                        f"projects.{name}.databricks.vpc_cidr {project.vpc_cidr} overlaps "
                        f"{other} ({other_network})"
                    )
            taken.append((f"project {name!r}", network))
        return self

    @model_validator(mode="after")
    def _monitoring_domain_in_the_zone(self) -> Settings:
        domain = self.monitoring.domain if self.monitoring is not None else None
        if domain is not None and not domain.endswith(f".{self.dns.zone}"):
            raise ValueError(
                f"monitoring.domain {domain} is not a name in the dns zone {self.dns.zone} "
                "(config/sites.yaml), where the stack creates its record"
            )
        return self

    def run_cost_ceiling(self, project: str) -> float:
        """The project's `max_run_cost_usd` override, else `tasks.max_run_cost_usd`."""
        guardrails = self.projects.get(project)
        if guardrails is not None and guardrails.max_run_cost_usd is not None:
            return guardrails.max_run_cost_usd
        return self.tasks.max_run_cost_usd

    def state_key(self, project: str, environment: str, stack: str | None = None) -> str:
        """The state key of a project's environment, or of one of its stacks.

        A Databricks project has several stacks (`account`, `workspace`); each gets
        `<project>-<environment>-<stack>` as its file name. Without `stack` the key
        is unchanged.
        """
        key = self.state.key_template.format(project=project, environment=environment)
        if stack is None:
            return key
        if not key.endswith(".tfstate"):
            raise ValueError("key_template must end in .tfstate to add a stack suffix")
        return f"{key.removesuffix('.tfstate')}-{stack}.tfstate"


class _ConfigLoader(yaml.SafeLoader):
    """YAML 1.2's booleans, true and false only. PyYAML follows YAML 1.1, where
    on, off, yes and no are booleans too, so the schedule's `on:` would be the key
    True; the workflows' yq reads config/ as YAML 1.2, and the CLI reads it as yq
    does. Terraform's yamldecode reads a bare `on:` key as "true", so monitoring/
    accepts either."""


_ConfigLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_ConfigLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def default_config_path() -> Path:
    """JAWS_CONFIG, else the directory baked into the image, else ./config."""
    if ENV_CONFIG_PATH in os.environ:
        return Path(os.environ[ENV_CONFIG_PATH])
    if IMAGE_CONFIG_PATH.is_dir():
        return IMAGE_CONFIG_PATH
    return LOCAL_CONFIG_PATH


def load_document(path: Path) -> dict[str, Any]:
    """The tool configuration as one mapping of its top-level sections.

    `path` is the config directory, whose `*.yaml` files are merged (each section
    in one file only), or a single file holding every section.
    """
    return _load_document_with_origin(path)[0]


def _load_document_with_origin(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """`load_document`, and the name of the file each section came from."""
    if path.is_dir():
        files = sorted(path.glob("*.yaml"))
        strays = sorted(p.name for p in path.glob("*.yml"))
        if strays:
            raise ConfigError(f"{path}: {', '.join(strays)}: config files end in .yaml")
        if not files:
            raise ConfigError(f"{path}: no .yaml files in the tool configuration directory")
    elif path.is_file():
        files = [path]
    else:
        raise ConfigError(f"tool configuration not found at {path}")
    document: dict[str, Any] = {}
    origin: dict[str, str] = {}
    for file in files:
        try:
            raw = yaml.load(file.read_text(), Loader=_ConfigLoader)
        except yaml.YAMLError as exc:
            raise ConfigError(f"{file}: not valid YAML: {exc}") from exc
        if raw is None:
            continue
        if not isinstance(raw, dict):
            raise ConfigError(f"{file}: expected a mapping at the top level")
        for section, value in raw.items():
            if section in document:
                raise ConfigError(
                    f"{file}: section {section!r} is already in {origin[section]}; "
                    "each section lives in one file"
                )
            document[section] = value
            origin[section] = file.name
    return document, origin


def load_settings(path: Path | None = None, environ: dict[str, str] | None = None) -> Settings:
    """Load the tool configuration (`load_document`) and apply the JAWS_* overrides.

    Only `JAWS_LOG_LEVEL` and `JAWS_LOG_FORMAT` may be overridden: they are the
    knobs a person debugging locally needs, and nothing else about how the
    tool runs should vary between runs of the same image.
    """
    env = os.environ if environ is None else environ
    path = path or default_config_path()
    raw, origin = _load_document_with_origin(path)

    tool = dict(raw.get("tool") or {})
    if "JAWS_LOG_LEVEL" in env:
        tool["log_level"] = env["JAWS_LOG_LEVEL"]
    if "JAWS_LOG_FORMAT" in env:
        tool["log_format"] = env["JAWS_LOG_FORMAT"]
    raw["tool"] = tool

    terraform_section = raw.get("terraform")
    owned: list[str] = []
    for key, section, present, home in (
        ("library", "library", "library" in raw, "src/jaws/product.yaml"),
        (
            "terraform.version",
            "terraform",
            isinstance(terraform_section, dict) and "version" in terraform_section,
            "src/jaws/product.yaml",
        ),
        (
            "plan",
            "plan",
            "plan" in raw,
            "src/jaws/product.py (PLAN_COMMENT_MAX_BYTES)",
        ),
    ):
        if present:
            where = f" in {origin[section]}" if path.is_dir() else ""
            owned.append(f"{key}{where}: belongs in {home}")
    if owned:
        raise ConfigError(
            f"{path}: {'; '.join(owned)}; the Jaws release owns these, "
            "not the platform configuration"
        )
    for legacy in ("production", "management", "development"):
        if legacy in raw:
            raise ConfigError(
                f"{path}: {legacy}: the accounts are the registry in aws.accounts "
                "(config/aws.yaml), each with its type; aws.primary names the one jaws builds in"
            )
    aws = raw.get("aws")
    if isinstance(aws, dict) and "account_id" in aws:
        raise ConfigError(
            f"{path}: aws.account_id: the accounts are the registry in aws.accounts "
            "(config/aws.yaml); aws.primary names the one jaws builds in"
        )
    try:
        return Settings.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {_format_validation_error(exc)}") from exc


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(f"{location}: {error['msg']}")
    return "; ".join(lines)
