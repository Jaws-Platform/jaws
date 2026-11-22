from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from jaws.errors import ConfigError
from jaws.settings import (
    ProjectGuardrails,
    Settings,
    load_document,
    load_settings,
    parse_duration,
)
from jaws.site import load_site_config
from tests.conftest import (
    CONFIG_DIR,
    FIXTURES,
    TEST_OWNER,
    fixture_config,
    project_entry,
    repo_config,
    with_guardrails,
)

#: Which file of config/ holds each section. Workflows and scripts read some
#: sections from their file with yq, so a section moves only with its readers.
SECTION_FILES = {
    "aws": "aws.yaml",
    "projects": "projects.yaml",
    "terraform": "terraform.yaml",
    "library": "terraform.yaml",
    "state": "terraform.yaml",
    "tool": "tool.yaml",
    "context": "tool.yaml",
    "plan": "tool.yaml",
    "ecr": "tool.yaml",
    "dns": "sites.yaml",
    "sync": "sites.yaml",
    "bot": "bots.yaml",
    "tasks": "bots.yaml",
    "databricks": "databricks.yaml",
    "monitoring": "monitoring.yaml",
}


def test_repository_config_loads() -> None:
    settings = load_settings(CONFIG_DIR, environ={})
    assert settings.ecr.repository == "jaws-cli"
    assert settings.state.bucket == "jaws-terraform-state-570327089884"
    assert settings.dns.zone == "jwall.engineering"


def test_every_section_is_in_its_file() -> None:
    found = {
        section: path.name
        for path in sorted(CONFIG_DIR.glob("*.yaml"))
        for section in yaml.safe_load(path.read_text())
    }
    assert found == SECTION_FILES


def test_one_file_reads_like_the_directory(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(repo_config()))
    assert load_settings(path, environ={}) == load_settings(CONFIG_DIR, environ={})


def test_a_section_in_two_files_is_refused(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(yaml.safe_dump({"plan": {"comment_max_bytes": 60000}}))
    (tmp_path / "b.yaml").write_text(yaml.safe_dump({"plan": {"comment_max_bytes": 1024}}))
    with pytest.raises(ConfigError, match=r"b\.yaml: section 'plan' is already in a\.yaml"):
        load_document(tmp_path)


def test_a_yml_file_is_refused_rather_than_skipped(tmp_path: Path) -> None:
    (tmp_path / "plan.yml").write_text(yaml.safe_dump({"plan": {"comment_max_bytes": 1024}}))
    with pytest.raises(ConfigError, match=r"plan\.yml: config files end in \.yaml"):
        load_document(tmp_path)


def test_an_empty_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"no \.yaml files"):
        load_document(tmp_path)


def test_the_config_is_read_as_terraform_and_yq_read_it(tmp_path: Path) -> None:
    """YAML 1.2's booleans, true and false only: PyYAML's YAML 1.1 would read the
    schedule's `on:` and `off:` keys (and yes, no) as booleans, while the
    workflows' yq reads them as strings. (Terraform's yamldecode reads a bare
    `on:` key as "true"; monitoring/ accepts either.)"""
    (tmp_path / "a.yaml").write_text(
        'a:\n  on: "08:00"\n  off: "24:00"\n  yes: no\n  flag: true\n  other: False\n'
    )
    assert load_document(tmp_path) == {
        "a": {"on": "08:00", "off": "24:00", "yes": "no", "flag": True, "other": False}
    }
    assert load_document(CONFIG_DIR)["monitoring"]["schedule"]["on"] == "08:00"


def test_state_key_template(settings: Settings) -> None:
    assert settings.state_key("guitar", "prod") == "project=guitar/env=prod/guitar-prod.tfstate"


@pytest.mark.parametrize(("value", "seconds"), [("120s", 120), ("15m", 900), ("1h", 3600)])
def test_parse_duration(value: str, seconds: int) -> None:
    assert parse_duration(value) == seconds


def test_parse_duration_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="duration"):
        parse_duration("soon")


def _write(tmp_path: Path, mutate: dict[str, object]) -> Path:
    raw = fixture_config()
    for dotted, value in mutate.items():
        section, key = dotted.split(".")
        raw.setdefault(section, {})[key] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, {"state.bukcet": "typo"})
    with pytest.raises(ConfigError, match=r"state\.bukcet"):
        load_settings(path, environ={})


def test_key_template_needs_placeholders(tmp_path: Path) -> None:
    path = _write(tmp_path, {"state.key_template": "project={project}/state.tfstate"})
    with pytest.raises(ConfigError, match="environment"):
        load_settings(path, environ={})


def test_bad_duration_is_a_config_error(tmp_path: Path) -> None:
    path = _write(tmp_path, {"terraform.lock_timeout": "soon"})
    with pytest.raises(ConfigError, match="lock_timeout"):
        load_settings(path, environ={})


def test_env_overrides_only_logging(tmp_path: Path) -> None:
    settings = load_settings(
        CONFIG_DIR,
        environ={"JAWS_LOG_LEVEL": "debug", "JAWS_LOG_FORMAT": "json", "JAWS_STATE_BUCKET": "evil"},
    )
    assert settings.tool.log_level == "debug"
    assert settings.tool.log_format == "json"
    assert settings.state.bucket == "jaws-terraform-state-570327089884"


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "nope.yaml", environ={})


def test_bot_section_defaults(settings: Settings) -> None:
    assert settings.bot.health_log_pattern == "awaiting challenges"
    assert settings.bot.health_seconds == 90
    assert settings.bot.records_prefix == "records/"
    assert settings.bot.availability_zones == (
        "us-east-1a", "us-east-1b", "us-east-1c", "us-east-1d", "us-east-1f",
    )  # fmt: skip


def test_bot_health_seconds_bounds(tmp_path: Path) -> None:
    raw = repo_config()
    raw["bot"]["health_seconds"] = 5
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="health_seconds"):
        load_settings(path, environ={})


def test_aws_account_is_configured(settings: Settings) -> None:
    """The one place the account ID lives: workflows build role ARNs from it."""
    assert settings.aws.primary == "production"
    assert settings.aws.account_id == "570327089884"
    assert settings.aws.admin_role_arn is not None
    assert settings.aws.admin_role_arn.startswith("arn:aws:iam::570327089884:role/aws-reserved/")


def test_the_registry_records_every_account_by_type(settings: Settings) -> None:
    """jaws builds in the primary account and only records the others."""
    by_type = {t: {n: a.account_id for n, a in settings.aws.of_type(t).items()} for t in
               ("management", "development", "staging", "production")}  # fmt: skip
    assert by_type == {
        "management": {"management": "650503560686"},
        "development": {"development": "859674017655"},
        "staging": {},
        "production": {"production": "570327089884"},
    }
    assert all(a.description for a in settings.aws.accounts.values())


def _load_aws(tmp_path: Path, aws: dict[str, Any]) -> Settings:
    raw = repo_config()
    raw["aws"] = aws
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    return load_settings(path, environ={})


def _registry() -> dict[str, Any]:
    aws: dict[str, Any] = repo_config()["aws"]
    return aws


def test_an_account_id_must_be_twelve_digits(tmp_path: Path) -> None:
    aws = _registry()
    aws["accounts"]["development"]["account_id"] = "85967401765"
    with pytest.raises(ConfigError, match=r"accounts\.development\.account_id"):
        _load_aws(tmp_path, aws)


def test_two_accounts_cannot_share_an_id(tmp_path: Path) -> None:
    aws = _registry()
    aws["accounts"]["development"]["account_id"] = "570327089884"
    with pytest.raises(
        ConfigError,
        match=r"accounts (development and production|production and development) are both "
        r"570327089884",
    ):
        _load_aws(tmp_path, aws)


def test_the_primary_account_must_be_in_the_registry(tmp_path: Path) -> None:
    aws = _registry()
    aws["primary"] = "prod"
    with pytest.raises(ConfigError, match="primary 'prod' is not in accounts"):
        _load_aws(tmp_path, aws)


def test_jaws_never_builds_in_the_management_account(tmp_path: Path) -> None:
    aws = _registry()
    aws["primary"] = "management"
    with pytest.raises(ConfigError, match="primary 'management' is the management account"):
        _load_aws(tmp_path, aws)


def test_an_organization_has_one_management_account(tmp_path: Path) -> None:
    aws = _registry()
    aws["accounts"]["development"]["type"] = "management"
    with pytest.raises(ConfigError, match="all of type management"):
        _load_aws(tmp_path, aws)


def test_an_account_type_is_one_of_the_known_types(tmp_path: Path) -> None:
    aws = _registry()
    aws["accounts"]["development"]["type"] = "sandbox"
    with pytest.raises(ConfigError, match=r"accounts\.development\.type"):
        _load_aws(tmp_path, aws)


def test_the_admin_role_must_be_in_its_account(tmp_path: Path) -> None:
    aws = _registry()
    role = aws["accounts"]["production"]["admin_role_arn"]
    aws["accounts"]["production"]["admin_role_arn"] = role.replace("570327089884", "650503560686")
    with pytest.raises(ConfigError, match="is not a role in account 570327089884"):
        _load_aws(tmp_path, aws)


def test_accounts_may_have_any_names(tmp_path: Path) -> None:
    """Someone else's registry: their own names, a staging account, no management."""
    settings = _load_aws(
        tmp_path,
        {
            "primary": "prod",
            "accounts": {
                "dev": {"type": "development", "account_id": "111111111111"},
                "stg": {"type": "staging", "account_id": "222222222222"},
                "prod": {"type": "production", "account_id": "333333333333"},
            },
        },
    )
    assert settings.aws.account_id == "333333333333"
    assert settings.aws.admin_role_arn is None
    assert list(settings.aws.of_type("staging")) == ["stg"]
    assert settings.aws.of_type("management") == {}


@pytest.mark.parametrize("legacy", ["management", "development", "production"])
def test_the_old_account_sections_point_at_the_registry(tmp_path: Path, legacy: str) -> None:
    raw = repo_config()
    raw[legacy] = {"account_id": "650503560686"}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(
        ConfigError, match=rf"{legacy}: the accounts are the registry in aws\.accounts"
    ):
        load_settings(path, environ={})


def test_the_old_aws_account_id_points_at_the_registry(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"aws\.account_id: the accounts are the registry"):
        _load_aws(tmp_path, {"account_id": "570327089884"})


def test_bot_amis_are_validated(tmp_path: Path) -> None:
    raw = repo_config()
    raw["bot"]["amis"] = {"x86_64": "ami-04b938437b69a2c9c"}  # an ID, not a name
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="amis"):
        load_settings(path, environ={})


def test_bot_amis_only_name_known_architectures(tmp_path: Path) -> None:
    raw = repo_config()
    raw["bot"]["amis"] = {"riscv64": "ami-0123456789abcdef0"}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="amis"):
        load_settings(path, environ={})


def test_bot_ami_name_must_match_its_architecture(tmp_path: Path) -> None:
    raw = repo_config()
    raw["bot"]["amis"] = {"x86_64": "al2023-ami-2023.9.20251027.0-kernel-6.1-arm64"}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="must end in -x86_64"):
        load_settings(path, environ={})


def test_bot_asset_wait(settings: Settings) -> None:
    """How long a build waits for a release's assets to be attached."""
    assert settings.bot.asset_wait_seconds == 1800


def test_tasks_section(settings: Settings) -> None:
    assert settings.tasks.rust_toolchain == "1.99.1"
    assert settings.tasks.poll_seconds == 5


@pytest.mark.parametrize("bad", ["", "1.99.1; rm -rf /", "Stable", "1.99.1 "])
def test_tasks_toolchain_is_a_rustup_name(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ConfigError, match="rust_toolchain"):
        load_settings(_write(tmp_path, {"tasks.rust_toolchain": bad}), environ={})


@pytest.mark.parametrize("bad", [0, 61])
def test_tasks_poll_bounds(tmp_path: Path, bad: int) -> None:
    with pytest.raises(ConfigError, match="poll_seconds"):
        load_settings(_write(tmp_path, {"tasks.poll_seconds": bad}), environ={})


def test_task_limits_and_default_ceiling(settings: Settings) -> None:
    assert settings.tasks.limits.model_dump() == {
        "max_hours": 6,
        "max_vcpus": 256,
        "root_volume_gb": 200,
    }
    assert settings.tasks.max_run_cost_usd == 50


def test_braveheart_guardrails_match_the_previous_lists(settings: Settings) -> None:
    guardrails = settings.projects["braveheart"]
    assert guardrails.instance_types == (
        "c8a.xlarge",
        "c8a.8xlarge",
        "c8a.16xlarge",
        "g6.xlarge",
        "g6.2xlarge",
        "g6e.xlarge",
    )
    assert guardrails.task_profiles == ("cpu", "gpu", "sprt", "match", "datagen", "relabel")
    assert list(guardrails.datasets) == ["jaws-braveheart-nnue"]
    retention = guardrails.datasets["jaws-braveheart-nnue"]
    assert retention.write_once == ()
    assert retention.expire_prefixes == {}
    assert retention.expire_noncurrent_days is None
    assert retention.versioning is False
    assert guardrails.max_run_cost_usd is None


def test_run_cost_ceiling_defaults_and_overrides(settings: Settings) -> None:
    assert settings.run_cost_ceiling("braveheart") == 50
    assert settings.run_cost_ceiling("not-registered") == 50
    raised = with_guardrails(settings, "big", ProjectGuardrails(max_run_cost_usd=80))
    assert raised.run_cost_ceiling("big") == 80
    assert raised.run_cost_ceiling("braveheart") == 50


def _entry(guardrails: object, **onboarding: object) -> dict[str, object]:
    """A raw research project entry with `guardrails` (a mapping)."""
    entry: dict[str, object] = {
        "description": "A sample",
        "type": "research",
        "repository": "sample",
        "repository_id": "1",
    }
    entry.update(guardrails)  # type: ignore[call-overload]
    entry.update(onboarding)
    return entry


def _with_projects(tmp_path: Path, projects: dict[str, object]) -> Path:
    """The repository's config with only `projects` (key -> raw entry, or the guardrails
    of a research project) onboarded, under the suite's owner."""
    raw = repo_config()
    raw["projects"] = {
        TEST_OWNER: {
            "owner_id": "100000",
            "projects": {
                k: v if isinstance(v, dict) and "type" in v else _entry(v)
                for k, v in projects.items()
            },
        }
    }
    del raw["databricks"]  # its projects are replaced here, and it needs one
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


def test_the_registry_onboards_every_project_once(settings: Settings) -> None:
    real = load_settings(CONFIG_DIR, environ={})
    by_type = {t: sorted(k for k, p in real.projects.items() if p.type == t)
               for t in ("site", "bot", "research", "databricks")}  # fmt: skip
    assert by_type == {
        "site": ["cs-survival-guide", "guitar-knowledge-base", "main-site"],
        "bot": ["braveheart-bot"],
        "research": [
            "braveheart",
            "braveheart-selfplay",
            "braveheart-trainer",
            "pi-benchmarks",
            "pi-prover",
            "prog-strength-archive",
        ],
        "databricks": ["braveheart-databricks"],
    }
    assert all(p.description for p in real.projects.values())
    assert real.repository("pi-prover") == "Pi-Mathematical-Reasoning/pi"
    assert real.repository("main-site") == "jwallace145/site"
    assert real.owners["Braveheart-Chess"].owner_id == "356866252"


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (_entry({}, type="site"), "a site needs its domain"),
        (
            _entry({"task_profiles": ["cpu"]}, type="site", domain="x.example.com"),
            "drop task_profiles",
        ),
        (_entry({}, domain="x.example.com"), "only a site has a domain"),
        (_entry({}, type="databricks"), "needs its databricks entry"),
        (_entry({}, type="pipeline"), r"\.type"),
        (_entry({}, repository_id="R_123"), "repository_id"),
        (_entry({}, description=""), "description"),
    ],
    ids=[
        "site-domain",
        "site-tasks",
        "domain-not-site",
        "databricks-entry",
        "type",
        "id",
        "description",
    ],
)
def test_an_entry_fits_its_type(tmp_path: Path, entry: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_settings(_with_projects(tmp_path, {"p": entry}), environ={})


def test_a_project_key_is_unique_across_owners(tmp_path: Path) -> None:
    raw = repo_config()
    raw["projects"]["Another-Org"] = {
        "owner_id": "200000",
        "projects": {"pi-prover": project_entry(raw, "pi-prover")},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(
        ConfigError,
        match=r"'pi-prover' is onboarded under both (Another-Org|Pi-Mathematical-Reasoning) and",
    ):
        load_settings(path, environ={})


@pytest.mark.parametrize(
    ("owner", "group", "message"),
    [
        (
            "Bad Owner",
            {"owner_id": "1", "projects": {"p": _entry({})}},
            "not a GitHub organization",
        ),
        ("Good-Owner", {"owner_id": "one", "projects": {"p": _entry({})}}, "owner_id"),
        ("Good-Owner", {"owner_id": "1", "projects": {}}, "projects"),
        ("Good-Owner", {"owner_id": "1", "projects": {"Bad_Key": _entry({})}}, "kebab-case"),
    ],
    ids=["owner-name", "owner-id", "no-projects", "project-key"],
)
def test_an_owner_is_a_github_account_with_projects(
    tmp_path: Path, owner: str, group: dict[str, object], message: str
) -> None:
    raw = repo_config()
    raw["projects"][owner] = group
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match=message):
        load_settings(path, environ={})


@pytest.mark.parametrize(
    "projects",
    [
        {"p": {"instance_typez": ["c8a.xlarge"]}},
        {"p": {"datasets": {"b": {"write_onse": ["runs/"]}}}},
    ],
)
def test_unknown_guardrail_key_is_refused(tmp_path: Path, projects: dict[str, object]) -> None:
    with pytest.raises(ConfigError, match="Extra inputs are not permitted"):
        load_settings(_with_projects(tmp_path, projects), environ={})


def test_unknown_limit_key_is_refused(tmp_path: Path) -> None:
    raw = repo_config()
    raw["tasks"]["limits"]["max_gpus"] = 1
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match=r"tasks\.limits\.max_gpus"):
        load_settings(path, environ={})


def test_dataset_retention_is_typed(tmp_path: Path) -> None:
    path = _with_projects(
        tmp_path,
        {
            "math-prover": {
                "datasets": {
                    "b": {
                        "prefix": "data/",
                        "write_once": ["runs/", "models/"],
                        "expire_prefixes": {"tmp/": 30},
                        "expire_noncurrent_days": 90,
                        "versioning": True,
                    }
                },
                "max_run_cost_usd": 80,
            }
        },
    )
    retention = load_settings(path, environ={}).projects["math-prover"].datasets["b"]
    assert retention.write_once == ("runs/", "models/")
    assert retention.expire_prefixes == {"tmp/": 30}
    assert retention.expire_noncurrent_days == 90
    assert retention.versioning is True
    assert retention.prefix == "data/"


@pytest.mark.parametrize(
    "retention",
    [
        {"write_once": ["runs/"]},
        {"expire_prefixes": {"tmp/": 1}},
        {"expire_noncurrent_days": 30, "versioning": True},
    ],
)
def test_central_retention_must_name_the_dataset_prefix(
    tmp_path: Path, retention: dict[str, object]
) -> None:
    path = _with_projects(tmp_path, {"p": {"datasets": {"b": retention}}})
    with pytest.raises(ConfigError, match=r"prefix"):
        load_settings(path, environ={})
    path = _with_projects(tmp_path, {"p": {"datasets": {"b": {**retention, "prefix": "data/"}}}})
    assert load_settings(path, environ={}).projects["p"].datasets["b"].prefix == "data/"


def test_an_empty_central_entry_needs_no_prefix(settings: Settings) -> None:
    entry = settings.projects["braveheart"].datasets["jaws-braveheart-nnue"]
    assert entry.prefix is None


@pytest.mark.parametrize(
    "retention",
    [
        {"prefix": "/data/"},
        {"prefix": "data"},
        {"prefix": "data/", "write_once": ["/runs/"]},
        {"prefix": "data/", "write_once": ["runs"]},
        {"prefix": "data/", "expire_prefixes": {"/tmp/": 1}},
        {"prefix": "data/", "expire_prefixes": {"tmp": 1}},
    ],
)
def test_central_prefixes_have_the_component_format(
    tmp_path: Path, retention: dict[str, object]
) -> None:
    path = _with_projects(tmp_path, {"p": {"datasets": {"b": retention}}})
    with pytest.raises(ConfigError, match=r"prefix|sub-prefix"):
        load_settings(path, environ={})


def _databricks_raw() -> dict[str, Any]:
    """The suite's baseline: Databricks in the management account, with the
    databricks-poc sample (tests/conftest.py)."""
    return fixture_config()


def _load_raw(tmp_path: Path, raw: dict[str, Any]) -> Settings:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    return load_settings(path, environ={})


def _second_project(raw: dict[str, Any], name: str, cidr: str) -> None:
    entry = yaml.safe_load(yaml.safe_dump(project_entry(raw, "databricks-poc")))
    entry["databricks"]["vpc_cidr"] = cidr
    raw["projects"][TEST_OWNER]["projects"][name] = entry


def test_databricks_section_parses(settings: Settings) -> None:
    section = settings.databricks
    assert section is not None
    assert section.enabled is True
    assert section.has_placeholder_ids is False  # the real IDs are filled in
    assert section.secret_parameter == "/jaws/databricks/client-secret"
    assert section.metastore_name == "jaws-us-east-1"
    assert section.audit_bucket == "jaws-databricks-audit-logs"
    assert section.events_prefix == "events/"
    assert section.readiness_timeout_seconds == 1200
    assert set(section.compute_policies) == {"small-interactive", "jobs"}
    small = section.compute_policies["small-interactive"].definition
    assert small["num_workers"] == {"type": "range", "maxValue": 2}
    assert small["autotermination_minutes"] == {"type": "fixed", "value": 30, "hidden": False}
    assert small["node_type_id"] == {"type": "allowlist", "values": ["m7g.large", "m7g.xlarge"]}
    assert small["aws_attributes.availability"]["value"] == "SPOT_WITH_FALLBACK"
    assert section.compute_policies["jobs"].definition["cluster_type"] == {
        "type": "fixed",
        "value": "job",
    }
    poc = settings.projects["databricks-poc"].databricks
    assert poc is not None
    assert poc.compute_policies == ("small-interactive", "jobs")
    assert poc.cost_center == "cc-0000"
    assert poc.vpc_cidr == "10.40.0.0/16"
    assert poc.admins == ("jimmy.wallace145@gmail.com",)


def test_users_in_config_yaml_are_refused_with_the_migration_message(tmp_path: Path) -> None:
    raw = _databricks_raw()
    project_entry(raw, "databricks-poc")["databricks"]["users"] = ["a@corp.test"]
    with pytest.raises(ConfigError, match=r"own jaws\.yaml.*databricks-workspace"):
        _load_raw(tmp_path, raw)


def test_real_ids_are_not_placeholders(tmp_path: Path) -> None:
    raw = _databricks_raw()
    raw["databricks"]["account_id"] = "11111111-2222-3333-4444-555555555555"
    raw["databricks"]["client_id"] = "66666666-7777-8888-9999-aaaaaaaaaaaa"
    section = _load_raw(tmp_path, raw).databricks
    assert section is not None
    assert section.has_placeholder_ids is False


def test_state_key_with_stack(settings: Settings) -> None:
    assert (
        settings.state_key("databricks-poc", "prod", "account")
        == "project=databricks-poc/env=prod/databricks-poc-prod-account.tfstate"
    )


def test_state_key_without_stack_unchanged(settings: Settings) -> None:
    assert (
        settings.state_key("databricks-poc", "prod")
        == "project=databricks-poc/env=prod/databricks-poc-prod.tfstate"
    )


def test_policy_name_must_be_kebab(tmp_path: Path) -> None:
    raw = _databricks_raw()
    policies = raw["databricks"]["compute_policies"]
    policies["Small_Interactive"] = policies.pop("small-interactive")
    project_entry(raw, "databricks-poc")["databricks"]["compute_policies"] = [
        "Small_Interactive",
        "jobs",
    ]
    with pytest.raises(ConfigError, match="Small_Interactive"):
        _load_raw(tmp_path, raw)


def test_policy_must_set_autotermination(tmp_path: Path) -> None:
    raw = _databricks_raw()
    del raw["databricks"]["compute_policies"]["jobs"]["definition"]["autotermination_minutes"]
    with pytest.raises(ConfigError, match=r"jobs.*autotermination_minutes"):
        _load_raw(tmp_path, raw)


def test_project_policy_must_exist_centrally(tmp_path: Path) -> None:
    raw = _databricks_raw()
    project_entry(raw, "databricks-poc")["databricks"]["compute_policies"] = ["ghost-policy"]
    with pytest.raises(ConfigError, match="ghost-policy"):
        _load_raw(tmp_path, raw)


def test_governance_project_is_no_longer_a_setting(tmp_path: Path) -> None:
    # Databricks manages the system schemas itself, so no workspace enables them.
    raw = _databricks_raw()
    raw["databricks"]["governance_project"] = "databricks-poc"
    with pytest.raises(ConfigError, match="governance_project"):
        _load_raw(tmp_path, raw)


def test_overlapping_vpc_cidrs_rejected(tmp_path: Path) -> None:
    raw = _databricks_raw()
    _second_project(raw, "team-a", "10.40.128.0/17")
    with pytest.raises(ConfigError, match=r"databricks-poc.*team-a|team-a.*databricks-poc"):
        _load_raw(tmp_path, raw)


def test_disjoint_vpc_cidrs_accepted(tmp_path: Path) -> None:
    raw = _databricks_raw()
    _second_project(raw, "team-a", "10.41.0.0/16")
    assert _load_raw(tmp_path, raw).projects["team-a"].databricks is not None


def test_vpc_cidr_overlapping_bot_vpc_rejected(tmp_path: Path) -> None:
    raw = _databricks_raw()
    project_entry(raw, "databricks-poc")["databricks"]["vpc_cidr"] = "10.0.0.0/20"
    with pytest.raises(ConfigError, match=r"10\.0\.0\.0/16"):
        _load_raw(tmp_path, raw)


@pytest.mark.parametrize("cidr", ["10.40.0.0/15", "10.40.0.0/21", "10.40.0.1/16", "nonsense"])
def test_vpc_cidr_must_be_a_16_to_20_network(tmp_path: Path, cidr: str) -> None:
    raw = _databricks_raw()
    project_entry(raw, "databricks-poc")["databricks"]["vpc_cidr"] = cidr
    with pytest.raises(ConfigError, match="vpc_cidr"):
        _load_raw(tmp_path, raw)


def test_databricks_project_name_limited_to_21_characters(tmp_path: Path) -> None:
    raw = _databricks_raw()
    long_name = "a" * 22
    _second_project(raw, long_name, "10.41.0.0/16")
    with pytest.raises(ConfigError, match=rf"{long_name}.*21"):
        _load_raw(tmp_path, raw)


def test_project_databricks_requires_section(tmp_path: Path) -> None:
    raw = _databricks_raw()
    del raw["databricks"]
    with pytest.raises(ConfigError, match=r"databricks-poc.*databricks"):
        _load_raw(tmp_path, raw)


def test_member_emails_must_look_like_emails(tmp_path: Path) -> None:
    raw = _databricks_raw()
    project_entry(raw, "databricks-poc")["databricks"]["admins"] = ["not-an-email"]
    with pytest.raises(ConfigError, match="not-an-email"):
        _load_raw(tmp_path, raw)


# -- placeholders once Databricks is enabled -------------------------------------------

REAL_ACCOUNT = "11111111-1111-1111-1111-111111111111"
REAL_CLIENT = "22222222-2222-2222-2222-222222222222"
REAL_ADMIN = "owner@jwall-engineering.test"


def _enabled(**overrides: Any) -> dict[str, Any]:
    raw = _databricks_raw()
    raw["databricks"].update(
        enabled=True, account_id=REAL_ACCOUNT, client_id=REAL_CLIENT, metastore_admins=[REAL_ADMIN]
    )
    raw["databricks"].update(overrides)
    return raw


def test_an_enabled_section_with_real_values_loads(tmp_path: Path) -> None:
    section = _load_raw(tmp_path, _enabled()).databricks
    assert section is not None and section.enabled and not section.has_placeholder_ids


def test_the_placeholders_are_valid_while_disabled(tmp_path: Path) -> None:
    nil = "00000000-0000-0000-0000-000000000000"
    raw = _enabled(
        enabled=False, account_id=nil, client_id=nil, metastore_admins=["owner@example.com"]
    )
    section = _load_raw(tmp_path, raw).databricks
    assert section is not None and not section.enabled
    assert section.has_placeholder_ids
    assert any(e.endswith("@example.com") for e in section.metastore_admins)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"account_id": "00000000-0000-0000-0000-000000000000"}, "databricks.account_id"),
        ({"client_id": "00000000-0000-0000-0000-000000000000"}, "databricks.client_id"),
        ({"metastore_admins": [REAL_ADMIN, "Owner@Example.com"]}, "databricks.metastore_admins"),
    ],
    ids=["account_id", "client_id", "metastore_admins"],
)
def test_an_enabled_section_refuses_placeholders(
    tmp_path: Path, overrides: dict[str, Any], field: str
) -> None:
    with pytest.raises(ConfigError, match=field) as raised:
        _load_raw(tmp_path, _enabled(**overrides))
    assert "databricks.enabled" in str(raised.value)


# -- monitoring ---------------------------------------------------------------------


def test_the_monitoring_section_loads() -> None:
    monitoring = load_settings(CONFIG_DIR, environ={}).monitoring
    assert monitoring is not None
    assert monitoring.instance_type == "t9g.medium"
    assert monitoring.ami == "al2023-ami-2023.12.20261026.1-kernel-6.18-arm64"
    assert monitoring.domain == "grafana.jwall.engineering"
    assert monitoring.snapshots is True
    schedule = monitoring.schedule
    assert schedule is not None
    assert schedule.timezone == "America/Denver"
    assert schedule.days == ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    assert (schedule.on, schedule.off) == ("08:00", "24:00")
    cost = monitoring.cost
    assert cost is not None
    assert cost.bucket == "jaws-billing-570327089884"
    assert (cost.protect_raw, cost.aws, cost.databricks) == (False, True, True)
    assert cost.budgets.total == 100
    assert (cost.budgets.projects, cost.budgets.accounts) == ({}, {})
    assert cost.anomaly_floor_usd == 2
    slack = monitoring.slack
    assert slack is not None
    assert slack.channels == {
        "platform": "/jaws/monitoring/slack/platform",
        "costs": "/jaws/monitoring/slack/costs",
    }
    assert slack.routes == {"host": "platform", "pipeline": "platform", "cost": "costs"}
    assert monitoring.thresholds == {}


def _load_monitoring(tmp_path: Path, edit: Any) -> Settings:
    """The repository's config with `edit` applied to its raw monitoring section."""
    raw = repo_config()
    edit(raw["monitoring"])
    return _load_raw(tmp_path, raw)


def _set(path: str, value: Any) -> Any:
    """An edit that sets the dotted `path` under monitoring to `value`."""

    def edit(section: dict[str, Any]) -> None:
        *parents, key = path.split(".")
        for part in parents:
            section = section[part]
        section[key] = value

    return edit


def _drop(path: str) -> Any:
    def edit(section: dict[str, Any]) -> None:
        *parents, key = path.split(".")
        for part in parents:
            section = section[part]
        del section[key]

    return edit


def _both(*edits: Any) -> Any:
    def edit(section: dict[str, Any]) -> None:
        for one in edits:
            one(section)

    return edit


@pytest.mark.parametrize(
    ("edit", "key"),
    [
        # The schedule (spec 6.10): whole hours, on before off on one day, at
        # least 4 hours on, unique weekdays, an IANA time zone.
        (_set("schedule.on", "08:30"), r"monitoring\.schedule\.on"),
        (_set("schedule.off", "23:30"), r"monitoring\.schedule\.off"),
        (_set("schedule.on", "8:00"), r"monitoring\.schedule\.on"),
        (_set("schedule.on", "24:00"), r"monitoring\.schedule\.on"),
        (_set("schedule.off", "25:00"), r"monitoring\.schedule\.off"),
        (_both(_set("schedule.on", "20:00"), _set("schedule.off", "06:00")),
         r"monitoring\.schedule\.off 06:00 is not after monitoring\.schedule\.on 20:00"),
        (_both(_set("schedule.on", "08:00"), _set("schedule.off", "11:00")),
         r"monitoring\.schedule\.off.*at least 4 hours"),
        (_both(_set("schedule.on", "00:00"), _set("schedule.off", "24:00")),
         r"monitoring\.schedule\.on 00:00 and monitoring\.schedule\.off 24:00"),
        (_set("schedule.timezone", "Mars/Olympus_Mons"), r"monitoring\.schedule\.timezone"),
        (_set("schedule.timezone", "../../etc/passwd"), r"monitoring\.schedule\.timezone"),
        (_set("schedule.days", []), r"monitoring\.schedule\.days"),
        (_set("schedule.days", ["mon", "mon"]), r"monitoring\.schedule\.days.*mon"),
        (_set("schedule.days", ["monday"]), r"monitoring\.schedule\.days"),
        (_set("schedule.cron", "0 8 * * *"), r"monitoring\.schedule\.cron"),
        # Slack: every route names a channel, host is routed, channels live in SSM
        # under /jaws/monitoring/.
        (_set("slack.routes.cost", "billing"), r"monitoring\.slack\.routes\.cost"),
        (_drop("slack.routes.host"), r"monitoring\.slack\.routes\.host"),
        (_set("slack.routes.deploys", "platform"), r"monitoring\.slack\.routes\.deploys"),
        (_set("slack.channels.platform", "/jaws/databricks/client-secret"),
         r"monitoring\.slack\.channels\.platform"),
        (_set("slack.channels.platform", "jaws/monitoring/slack/platform"),
         r"monitoring\.slack\.channels\.platform"),
        (_set("slack.channels", {"Platform": "/jaws/monitoring/slack/platform"}),
         r"monitoring\.slack\.channels\.Platform"),
        (_set("slack.channels", {}), r"monitoring\.slack\.channels"),
        # Cost: positive budgets, a floor of at least 0, a bucket name, a provider.
        (_set("cost.budgets.total", 0), r"monitoring\.cost\.budgets\.total"),
        (_set("cost.budgets.total", -5), r"monitoring\.cost\.budgets\.total"),
        (_set("cost.budgets.projects", {"braveheart-trainer": 0}),
         r"monitoring\.cost\.budgets\.projects\.braveheart-trainer"),
        (_set("cost.budgets.accounts", {"production": -1}),
         r"monitoring\.cost\.budgets\.accounts\.production"),
        (_set("cost.anomaly_floor_usd", -1), r"monitoring\.cost\.anomaly_floor_usd"),
        (_set("cost.bucket", "Jaws_Billing"), r"monitoring\.cost\.bucket"),
        (_set("cost.bucket", "jb"), r"monitoring\.cost\.bucket"),
        (_both(_set("cost.aws", False), _set("cost.databricks", False)),
         r"monitoring\.cost\.aws.*monitoring\.cost\.databricks"),
        # The node: a pinned arm64 AL2023 image name, a Graviton type, a name in
        # the zone.
        (_set("ami", "ami-0123456789abcdef0"), r"monitoring\.ami"),
        (_set("ami", "al2023-ami-2023.12.20261026.1-kernel-6.18-x86_64"), r"monitoring\.ami"),
        (_set("ami", "amzn2-ami-hvm-2.0.20261026-arm64"), r"monitoring\.ami"),
        (_set("instance_type", "t3.medium"), r"monitoring\.instance_type"),
        (_set("domain", "grafana.example.com"), r"monitoring\.domain"),
        # Overrides of the module's thresholds, by name and shape.
        (_set("thresholds", {"cpu_percnt": {"warning": 50, "critical": 80}}),
         r"monitoring\.thresholds\.cpu_percnt"),
        (_set("thresholds", {"cpu_percent": {"warning": 50}}),
         r"monitoring\.thresholds\.cpu_percent"),
        (_set("thresholds", {"prometheus_size_percent": {"warning": 80, "critical": 95}}),
         r"monitoring\.thresholds\.prometheus_size_percent"),
        # Anything else is a typo.
        (_set("instance_typo", "t9g.small"), r"monitoring\.instance_typo"),
        (_set("cost.protect", True), r"monitoring\.cost\.protect"),
    ],
    ids=[
        "half-hour-on", "half-hour-off", "unpadded-on", "on-at-24", "off-past-24", "overnight",
        "under-4-hours", "whole-day", "unknown-zone", "zone-path", "no-days", "duplicate-day",
        "unknown-day", "raw-cron", "route-to-missing-channel", "no-host-route",
        "unknown-area", "channel-outside-prefix", "channel-relative", "channel-name",
        "no-channels", "zero-budget", "negative-budget", "zero-project-budget",
        "negative-account-budget", "negative-floor", "bucket-name", "bucket-too-short",
        "no-provider", "ami-id", "ami-x86", "ami-not-al2023", "not-graviton",
        "domain-outside-zone", "unknown-threshold", "threshold-missing-critical",
        "threshold-warning-only", "unknown-key", "unknown-cost-key",
    ],
)  # fmt: skip
def test_bad_monitoring_config_names_its_key(tmp_path: Path, edit: Any, key: str) -> None:
    with pytest.raises(ConfigError, match=key):
        _load_monitoring(tmp_path, edit)


@pytest.mark.parametrize(
    "edit",
    [
        _drop("schedule"),
        _drop("slack"),
        _drop("cost"),
        _drop("domain"),
        _drop("slack.routes.cost"),
        _set("schedule.days", ["mon", "tue", "wed", "thu", "fri"]),
        _both(_set("schedule.on", "00:00"), _set("schedule.off", "04:00")),
        _set("schedule.timezone", "UTC"),
        _set("cost.budgets.projects", {"braveheart-trainer": 40}),
        _set("cost.budgets.accounts", {"570327089884": 90}),
        _set("cost.anomaly_floor_usd", 0),
        _set("thresholds", {"cpu_percent": {"warning": 50, "critical": 80},
                            "untagged_daily_usd": {"warning": 1}}),
        _set("instance_type", "m8gd.large"),
    ],
    ids=[
        "always-on", "no-slack", "host-only", "private", "cost-on-host", "weekdays",
        "midnight-start", "utc", "project-budget", "account-budget", "zero-floor",
        "thresholds", "other-graviton",
    ],
)  # fmt: skip
def test_good_monitoring_config_loads(tmp_path: Path, edit: Any) -> None:
    assert _load_monitoring(tmp_path, edit).monitoring is not None


def test_monitoring_is_optional(tmp_path: Path) -> None:
    raw = repo_config()
    del raw["monitoring"]
    assert _load_raw(tmp_path, raw).monitoring is None


@pytest.mark.parametrize(
    "fixture",
    [
        FIXTURES / "sites" / "guitar-knowledge-base.yaml",
        FIXTURES / "bots" / "braveheart.yaml",
        FIXTURES / "bots" / "math-prover.yaml",
        FIXTURES / "bots" / "databricks-poc.yaml",
    ],
    ids=["site", "bot", "research", "databricks"],
)
def test_project_files_cannot_set_monitoring(tmp_path: Path, fixture: Path) -> None:
    """The platform's settings are config/'s alone: neither a project's own file
    nor its entry in config/projects.yaml can name a monitoring key."""
    raw = yaml.safe_load(fixture.read_text())
    raw["monitoring"] = {"schedule": None, "cost": {"budgets": {"total": 1000}}}
    path = tmp_path / "jaws.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match=r"monitoring: Extra inputs are not permitted"):
        load_site_config(path)
    config = repo_config()
    project_entry(config, "braveheart-trainer")["monitoring"] = {"budgets": {"total": 1000}}
    with pytest.raises(ConfigError, match=r"braveheart-trainer\.monitoring"):
        _load_raw(tmp_path, config)
