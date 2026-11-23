from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from jaws import stack as stack_module
from jaws.databricks_auth import terraform_env
from jaws.errors import ConfigError, RunError
from jaws.product import product_pins
from jaws.project import Project
from jaws.settings import Settings
from jaws.site import Site, load_site_config
from jaws.stack import (
    PLAN_CHANGES,
    PLAN_NO_CHANGES,
    Terraform,
    _databricks_account_tfvars,
    _databricks_workspace_tfvars,
    dataset_bucket_addresses,
    dataset_names,
    default_stack_dir,
    deployment_name,
    render_backend,
    render_tfvars,
)
from tests.conftest import FIXTURES, REPO_ROOT, offboard, project_entry

#: What each site's infra/ directory produced before the migration, by project.
#: Step 6's "no changes" plan depends on these staying identical.
EXPECTED_TFVARS = {
    "guitar-knowledge-base": {
        "domain_name": "guitar.jwall.engineering",
        "dev_domain_name": None,
        "enable_preview": True,
        "zone_id": "Z0644006DW6W2HALU9BI",
    },
    "cs-survival-guide": {
        "domain_name": "survival-guide.jwall.engineering",
        "dev_domain_name": None,
        "enable_preview": True,
        "zone_id": "Z0644006DW6W2HALU9BI",
    },
    "main-site": {
        "domain_name": "jwall.engineering",
        "dev_domain_name": None,
        "enable_preview": True,
        "zone_id": "Z0644006DW6W2HALU9BI",
    },
}


def test_rendered_tfvars_match_the_old_infra_directories(site: Site) -> None:
    tfvars = render_tfvars(site)
    expected = EXPECTED_TFVARS[site.project]
    assert {key: tfvars[key] for key in expected} == expected
    assert tfvars["project"] == site.project
    assert tfvars["repository"] == site.config.repository
    assert tfvars["tags"]["Project"] == site.project
    assert tfvars["name_root"] == "jaws"
    assert tfvars["tags"]["Organization"] == site.organization == "jwallace145"
    assert tfvars["tags"]["ManagedBy"] == "JAWS"


def test_rendered_backend_matches_the_old_backend_files(site: Site) -> None:
    assert render_backend(site) == (
        'bucket       = "jaws-terraform-state-570327089884"\n'
        f'key          = "project={site.project}/env=prod/{site.project}-prod.tfstate"\n'
        'region       = "us-east-1"\n'
        "use_lockfile = true\n"
        "encrypt      = true\n"
    )


def test_tfvars_are_valid_for_the_stack_variables(site: Site) -> None:
    """Every variable the stack declares is rendered, and nothing else."""
    declared = {
        line.split('"')[1]
        for line in (REPO_ROOT / "stacks" / "site" / "variables.tf").read_text().splitlines()
        if line.startswith('variable "')
    }
    assert set(render_tfvars(site)) == declared


def _declared(stack: str) -> set[str]:
    return {
        line.split('"')[1]
        for line in (REPO_ROOT / "stacks" / stack / "variables.tf").read_text().splitlines()
        if line.startswith('variable "')
    }


def test_render_tfvars_for_bot(bot: Project, settings: Settings) -> None:
    assert render_tfvars(bot, settings) == {
        "project": "braveheart",
        "repository": "Braveheart-Chess/braveheart",
        "name_root": "jaws",
        "tags": {
            "Project": "braveheart",
            "Environment": "prod",
            "Repository": "Braveheart-Chess/braveheart",
            "Owner": "jwallace145",
            "Organization": "Braveheart-Chess",
            "ManagedBy": "JAWS",
        },
        "bot_enabled": True,
        "instance_type": "t3.micro",
        "architecture": "x86_64",
        "secret_parameters": {"LICHESS_TOKEN": "/jaws/braveheart/lichess-token"},
        "container_environment": {"ENGINE_HASH_MB": "128", "ENGINE_MOVE_OVERHEAD_MS": "500"},
        "bot_name": "rusty-chess-bot",
        "records_enabled": True,
        "records_prefix": "records/",
        "bucket_admin_principal_arns": [
            "arn:aws:iam::570327089884:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_013589f39f92382a",
            "arn:aws:iam::570327089884:root",
        ],
        "records_container_path": "/opt/lichess-bot/game_records",
        "log_retention_days": 30,
        "health_log_pattern": "awaiting challenges",
        "health_seconds": 90,
        "availability_zones": [
            "us-east-1a",
            "us-east-1b",
            "us-east-1c",
            "us-east-1d",
            "us-east-1f",
        ],
        "keep_release_images": 20,
        "expire_untagged_after_days": 7,
        "ami_name": settings.bot.amis["x86_64"],
        "schedule": None,
        "task_runner_enabled": True,
        "task_instance_type": "c8a.16xlarge",
        "task_max_lifetime_hours": 6,
        "task_results_days": 7,
        "task_log_retention_days": 14,
        "task_rust": True,
        "task_rust_toolchain": settings.tasks.rust_toolchain,
        "task_profiles": [
            {
                "name": "gpu",
                "default_instance_type": "g6.xlarge",
                "max_hours": 6,
                "ami_name": (
                    "Deep Learning Base OSS Nvidia Driver GPU AMI (Amazon Linux 2023) 20261027"
                ),
                "root_volume_gb": 200,
                "gpu": True,
                "rust": True,
                "datasets": [
                    {"name": "nnue", "read": ["selfplay/"], "write": ["nets/"], "write_once": []}
                ],
            },
            {
                "name": "sprt",
                "default_instance_type": "c8a.16xlarge",
                "max_hours": 6,
                "ami_name": None,
                "root_volume_gb": 40,
                "gpu": False,
                "rust": True,
                "datasets": [],
            },
            {
                "name": "match",
                "default_instance_type": "c8a.16xlarge",
                "max_hours": 6,
                "ami_name": None,
                "root_volume_gb": 40,
                "gpu": False,
                "rust": True,
                "datasets": [],
            },
            {
                "name": "datagen",
                "default_instance_type": "c8a.16xlarge",
                "max_hours": 6,
                "ami_name": None,
                "root_volume_gb": 40,
                "gpu": False,
                "rust": True,
                "datasets": [
                    {"name": "nnue", "read": [], "write": ["selfplay/"], "write_once": []}
                ],
            },
            {
                "name": "relabel",
                "default_instance_type": "c8a.16xlarge",
                "max_hours": 6,
                "ami_name": None,
                "root_volume_gb": 40,
                "gpu": False,
                "rust": True,
                "datasets": [
                    {
                        "name": "nnue",
                        "read": ["selfplay/"],
                        "write": ["selfplay/relabel/"],
                        "write_once": [],
                    }
                ],
            },
        ],
        "datasets": [
            {
                "name": "nnue",
                "bucket": "jaws-braveheart-nnue",
                "prefix": "data/",
                "writers": ["task-runner"],
                "readers": [],
                "transition_days": 0,
                "versioning": False,
                "expire_noncurrent_days": None,
                "expire_prefixes": {},
            }
        ],
    }


def test_bot_tfvars_are_valid_for_the_bot_stack(bot: Project, settings: Settings) -> None:
    assert set(render_tfvars(bot, settings)) == _declared("bot")


def test_site_project_renders_the_site_tfvars(site: Site, settings: Settings) -> None:
    project = Project.from_config(site.config, settings)
    assert render_tfvars(project, settings) == render_tfvars(site)


def test_stack_dir_by_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JAWS_STACK_DIR", raising=False)
    monkeypatch.setenv("JAWS_STACKS_ROOT", "/somewhere/stacks")
    assert default_stack_dir("bot") == Path("/somewhere/stacks/bot")
    assert default_stack_dir("site") == Path("/somewhere/stacks/site")
    monkeypatch.setenv("JAWS_STACK_DIR", "/explicit")
    assert default_stack_dir("bot") == Path("/explicit")


def _terraform(site: Site, settings: Settings, logger: logging.Logger) -> Terraform:
    return Terraform(
        site, settings, logger, stack_dir=REPO_ROOT / "stacks" / "site", plugin_dir=None
    )


def _debug_file_logger(console_level: int) -> logging.Logger:
    """A logger shaped like the CLI's: DEBUG overall (for the debug log file), the
    console at `console_level`."""
    logger = logging.getLogger(f"keep-workdir-{console_level}")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(console_level)
    logger.addHandler(console)
    logger.addHandler(logging.NullHandler())
    return logger


@pytest.mark.parametrize(
    ("console_level", "keep_env", "kept"),
    [
        (logging.INFO, None, False),  # the debug log file alone must not keep it
        (logging.DEBUG, None, True),  # debug output on the console keeps it
        (logging.INFO, "1", True),  # so does JAWS_KEEP_WORKDIR=1
    ],
)
def test_a_failed_run_keeps_its_workdir_only_when_asked(
    guitar: Site,
    settings: Settings,
    fake_terraform: Path,
    monkeypatch: pytest.MonkeyPatch,
    console_level: int,
    keep_env: str | None,
    kept: bool,
) -> None:
    if keep_env is None:
        monkeypatch.delenv("JAWS_KEEP_WORKDIR", raising=False)
    else:
        monkeypatch.setenv("JAWS_KEEP_WORKDIR", keep_env)
    terraform = _terraform(guitar, settings, _debug_file_logger(console_level))
    workdir = terraform.prepare()
    terraform.cleanup(failed=True)
    try:
        assert workdir.exists() is kept
    finally:
        if workdir.exists():
            shutil.rmtree(workdir)


def test_prepare_copies_vendored_modules_but_not_provider_binaries(
    guitar: Site,
    settings: Settings,
    logger: logging.Logger,
    fake_terraform: Path,
    tmp_path: Path,
) -> None:
    """The image keeps each stack's .terraform/modules so run-time init is offline;
    a local init leaves .terraform/providers (hundreds of MB), which init never reads
    from the copy (providers come from the plugin mirror or the cache)."""
    stack = tmp_path / "stack"
    stack.mkdir()
    (stack / "main.tf").write_text("# stack\n")
    (stack / ".terraform" / "modules" / "network").mkdir(parents=True)
    (stack / ".terraform" / "modules" / "modules.json").write_text("{}\n")
    (stack / ".terraform" / "modules" / "network" / "main.tf").write_text("# module\n")
    (stack / ".terraform" / "providers" / "registry").mkdir(parents=True)
    (stack / ".terraform" / "providers" / "registry" / "huge-binary").write_bytes(b"x" * 1024)
    (stack / ".terraform.lock.hcl").write_text("# lock\n")
    terraform = Terraform(guitar, settings, logger, stack_dir=stack, plugin_dir=None)
    workdir = terraform.prepare()
    try:
        assert (workdir / "main.tf").is_file()
        assert (workdir / ".terraform.lock.hcl").is_file()
        assert (workdir / ".terraform" / "modules" / "modules.json").is_file()
        assert (workdir / ".terraform" / "modules" / "network" / "main.tf").is_file()
        assert not (workdir / ".terraform" / "providers").exists()
    finally:
        terraform.cleanup(failed=False)


def test_prepare_writes_inputs_into_a_copy(
    guitar: Site, settings: Settings, logger: logging.Logger, fake_terraform: Path
) -> None:
    terraform = _terraform(guitar, settings, logger)
    workdir = terraform.prepare()
    try:
        assert (workdir / "main.tf").is_file()
        assert (
            json.loads((workdir / "terraform.tfvars.json").read_text())["project"]
            == "guitar-knowledge-base"
        )
        assert (workdir / "backend.hcl").read_text() == render_backend(guitar)
        assert not (REPO_ROOT / "stacks" / "site" / "terraform.tfvars.json").exists()
    finally:
        terraform.cleanup(failed=False)
    assert not workdir.exists()


def test_version_mismatch_fails_fast(
    guitar: Site,
    settings: Settings,
    logger: logging.Logger,
    fake_terraform: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_TF_VERSION", "1.9.0")
    terraform = _terraform(guitar, settings, logger)
    expected = re.escape(product_pins().terraform_version)
    with pytest.raises(RunError, match=rf"built with {expected} \(src/jaws/product\.yaml\)"):
        terraform.prepare()


def test_init_plan_and_outputs_invoke_terraform(
    guitar: Site,
    settings: Settings,
    logger: logging.Logger,
    fake_terraform: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_TF_PLAN_EXIT", str(PLAN_CHANGES))
    terraform = _terraform(guitar, settings, logger)
    terraform.prepare()
    try:
        terraform.init()
        result = terraform.plan(detailed_exitcode=True)
        assert result.returncode == PLAN_CHANGES
        assert "Plan:" in result.output
        outputs = terraform.outputs()
        assert outputs["prod_distribution_id"] == "E1PROD"
    finally:
        terraform.cleanup(failed=False)
    calls = [c for c in fake_terraform.read_text().splitlines() if not c.startswith("version")]
    assert calls[0] == "init -input=false -no-color -backend-config=backend.hcl -reconfigure"
    assert (
        calls[1] == "plan -input=false -no-color "
        f"-lock-timeout={settings.terraform.lock_timeout} -detailed-exitcode"
    )
    assert calls[2] == "output -no-color -json"


def test_offline_init_uses_plugin_dir_and_no_backend(
    guitar: Site, settings: Settings, logger: logging.Logger, fake_terraform: Path, tmp_path: Path
) -> None:
    terraform = Terraform(
        guitar, settings, logger, stack_dir=REPO_ROOT / "stacks" / "site", plugin_dir=tmp_path
    )
    terraform.prepare()
    try:
        terraform.init(backend=False)
        terraform.validate()
    finally:
        terraform.cleanup(failed=False)
    calls = [c for c in fake_terraform.read_text().splitlines() if not c.startswith("version")]
    assert calls[0] == f"init -input=false -no-color -plugin-dir={tmp_path} -backend=false"
    assert calls[1] == "validate -no-color"


def test_plan_without_detailed_exitcode_treats_changes_as_success(
    guitar: Site,
    settings: Settings,
    logger: logging.Logger,
    fake_terraform: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_TF_PLAN_EXIT", str(PLAN_NO_CHANGES))
    terraform = _terraform(guitar, settings, logger)
    terraform.prepare()
    try:
        result = terraform.plan(out=Path("tfplan"))
    finally:
        terraform.cleanup(failed=False)
    assert result.returncode == 0
    assert fake_terraform.read_text().splitlines()[-1].endswith("-out=tfplan")


def test_lock_info_is_reported(
    guitar: Site,
    settings: Settings,
    logger: logging.Logger,
    fake_terraform: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("FAKE_TF_LOCKED", "1")
    terraform = _terraform(guitar, settings, logger)
    terraform.prepare()
    try:
        with (
            caplog.at_level(logging.ERROR, logger=logger.name),
            pytest.raises(RunError, match="plan failed"),
        ):
            terraform.plan(detailed_exitcode=True)
    finally:
        terraform.cleanup(failed=False)
    assert "the state is locked" in caplog.text
    assert "someone@host" in caplog.text


def test_missing_binary_is_a_run_error(
    guitar: Site, settings: Settings, logger: logging.Logger
) -> None:
    terraform = Terraform(
        guitar,
        settings,
        logger,
        stack_dir=REPO_ROOT / "stacks" / "site",
        plugin_dir=None,
        binary="no-such-terraform",
    )
    with pytest.raises(RunError, match="not found on PATH"):
        terraform.prepare()


def test_missing_stack_is_a_run_error(
    guitar: Site, settings: Settings, logger: logging.Logger, tmp_path: Path
) -> None:
    terraform = Terraform(guitar, settings, logger, stack_dir=tmp_path / "nope", plugin_dir=None)
    with pytest.raises(RunError, match="site stack not found"):
        terraform.prepare()


def test_failed_run_keeps_workdir_when_asked(
    guitar: Site,
    settings: Settings,
    logger: logging.Logger,
    fake_terraform: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAWS_KEEP_WORKDIR", "1")
    terraform = _terraform(guitar, settings, logger)
    workdir = terraform.prepare()
    terraform.cleanup(failed=True)
    assert workdir.exists()
    terraform.cleanup(failed=False)


def test_bot_tfvars_follow_the_latest_image_without_a_pin(bot: Project, settings: Settings) -> None:
    unpinned = settings.model_copy(update={"bot": settings.bot.model_copy(update={"amis": {}})})
    assert render_tfvars(bot, unpinned)["ami_name"] is None


def test_config_pins_the_x86_64_image(settings: Settings) -> None:
    """The bot instance only changes OS when this pin changes; it is pinned by name."""
    name = settings.bot.amis["x86_64"]
    assert name.startswith("al2023-ami-") and name.endswith("-x86_64")


def test_bot_tfvars_without_datasets(bot: Project, settings: Settings) -> None:
    components = tuple(c for c in bot.config.components if c.kind != "dataset")
    plain = bot.model_copy(
        update={"config": bot.config.model_copy(update={"components": components})}
    )
    assert render_tfvars(plain, settings)["datasets"] == []


def test_bot_tfvars_without_a_task_runner(tmp_path: Path, bot: Project, settings: Settings) -> None:
    components = tuple(c for c in bot.config.components if c.kind not in ("task-runner", "dataset"))
    plain = bot.model_copy(
        update={"config": bot.config.model_copy(update={"components": components})}
    )
    tfvars = render_tfvars(plain, settings)
    assert tfvars["task_runner_enabled"] is False
    # The other task variables keep valid values so the stack's validations hold.
    assert tfvars["task_instance_type"] == "c8a.16xlarge"
    assert set(tfvars) == _declared("bot")


# -- the bot stack's gating ---------------------------------------------------


def _blocks(path: Path) -> list[tuple[str, list[str], dict[str, str]]]:
    """(type, labels, attributes) of each top-level block of a `terraform fmt`-ed file.

    fmt puts a block's closing brace in column one and indents its own attributes
    by exactly two spaces, so nested blocks' attributes are not mistaken for them.
    An attribute's value is its first line.
    """
    blocks: list[tuple[str, list[str], dict[str, str]]] = []
    attributes: dict[str, str] = {}
    for line in path.read_text().splitlines():
        opening = re.fullmatch(r'(\w+)((?: "[^"]+")*) \{', line)
        attribute = re.fullmatch(r"  (\w+)\s*=\s*(.*)", line)
        if opening:
            attributes = {}
            labels = re.findall(r'"([^"]+)"', opening.group(2))
            blocks.append((opening.group(1), labels, attributes))
        elif attribute:
            attributes[attribute.group(1)] = attribute.group(2)
    return blocks


def _bot_stack(block_type: str, file: str = "main.tf") -> dict[str, dict[str, str]]:
    """Blocks of one type in a stacks/bot file, by first label."""
    return {
        labels[0]: attributes
        for kind, labels, attributes in _blocks(REPO_ROOT / "stacks" / "bot" / file)
        if kind == block_type
    }


def _strip_new_keys(tfvars: dict[str, Any]) -> dict[str, Any]:
    """`tfvars` without the keys stack gating added."""
    old = {
        k: v
        for k, v in tfvars.items()
        if k
        not in ("bot_enabled", "task_rust", "schedule", "bucket_admin_principal_arns", "name_root")
    }
    old["task_profiles"] = [
        {
            **{k: v for k, v in profile.items() if k != "rust"},
            "datasets": [
                {k: v for k, v in dataset.items() if k != "write_once"}
                for dataset in profile["datasets"]
            ],
        }
        for profile in tfvars["task_profiles"]
    ]
    old["datasets"] = [
        {
            k: v
            for k, v in dataset.items()
            if k not in ("versioning", "expire_noncurrent_days", "expire_prefixes")
        }
        for dataset in tfvars["datasets"]
    ]
    return old


def test_braveheart_tfvars_are_unchanged(bot: Project, settings: Settings) -> None:
    """The braveheart fixture's inputs are what they were before gating, plus new keys
    at their defaults. The fixture is a sample, not the live bot's file.

    The snapshot was rendered by the code before this change (commit 76187b0). It
    holds the pinned AMIs and Rust toolchain from config/bots.yaml, so regenerate it when
    `bot.amis`, `tasks.images` or `tasks.rust_toolchain` is bumped.
    """
    snapshot = json.loads((FIXTURES / "bots" / "braveheart.tfvars.json").read_text())
    tfvars = render_tfvars(bot, settings)
    assert _strip_new_keys(tfvars) == snapshot

    assert tfvars["bot_enabled"] is True
    assert tfvars["task_rust"] is True
    assert tfvars["task_profiles"], "the snapshot must exercise task profiles"
    for profile in tfvars["task_profiles"]:
        assert profile["rust"] is True
        for dataset in profile["datasets"]:
            assert dataset["write_once"] == []
    assert tfvars["datasets"], "the snapshot must exercise datasets"
    for dataset in tfvars["datasets"]:
        assert dataset["versioning"] is False
        assert dataset["expire_noncurrent_days"] is None
        assert dataset["expire_prefixes"] == {}


def test_research_tfvars(research: Project, settings: Settings) -> None:
    tfvars = render_tfvars(research, settings)
    assert tfvars["bot_enabled"] is False
    assert tfvars["records_enabled"] is False
    assert tfvars["architecture"] == "x86_64"
    assert tfvars["task_runner_enabled"] is True
    assert tfvars["task_rust"] is False
    # A task runner needs the network and the cpu profile's pinned image.
    assert tfvars["availability_zones"] == list(settings.bot.availability_zones)
    assert tfvars["ami_name"] == settings.bot.amis["x86_64"]

    profiles = {p["name"]: p for p in tfvars["task_profiles"]}
    assert set(profiles) == {"train"}
    train = profiles["train"]
    assert train["rust"] is False
    assert train["ami_name"] == settings.tasks.images["deep-learning-gpu"]
    assert train["datasets"] == [
        {
            "name": "artifacts",
            "read": ["datasets/", "models/", "runs/", "tmp/"],
            "write": ["tmp/"],
            "write_once": ["runs/", "models/"],
        }
    ]

    assert tfvars["datasets"] == [
        {
            "name": "artifacts",
            "bucket": "jaws-math-prover-artifacts",
            "prefix": "data/",
            "writers": [],
            "readers": [],
            "transition_days": 0,
            "versioning": True,
            "expire_noncurrent_days": 90,
            "expire_prefixes": {"tmp/": 30},
        }
    ]


def test_research_tfvars_leave_the_bots_inputs_to_the_stacks_defaults(
    research: Project, settings: Settings
) -> None:
    tfvars = render_tfvars(research, settings)
    bot_only = {
        "instance_type",
        "secret_parameters",
        "container_environment",
        "bot_name",
        "records_prefix",
        "records_container_path",
        "log_retention_days",
        "health_log_pattern",
        "health_seconds",
        "keep_release_images",
        "expire_untagged_after_days",
    }
    assert not bot_only & set(tfvars)
    variables = _bot_stack("variable", "variables.tf")
    assert bot_only <= {name for name, block in variables.items() if "default" in block}


def _dataset_only(research: Project) -> Project:
    components = tuple(c for c in research.config.components if c.kind == "dataset")
    config = research.config.model_copy(update={"components": components})
    return research.model_copy(update={"config": config})


def test_dataset_only_project_disables_network(research: Project, settings: Settings) -> None:
    """A research file with only a dataset creates no VPC and no task resources."""
    tfvars = render_tfvars(_dataset_only(research), settings)
    assert tfvars["bot_enabled"] is False
    assert tfvars["task_runner_enabled"] is False
    assert tfvars["task_profiles"] == []
    assert [d["name"] for d in tfvars["datasets"]] == ["artifacts"]
    assert tfvars["ami_name"] is None, "nothing launches, so no image to resolve"


def test_network_exists_for_a_bot_or_a_task_runner() -> None:
    locals_blocks = [
        attributes
        for kind, _, attributes in _blocks(REPO_ROOT / "stacks" / "bot" / "main.tf")
        if kind == "locals"
    ]
    assert locals_blocks[0]["network_enabled"] == "var.bot_enabled || var.task_runner_enabled"
    modules = _bot_stack("module")
    assert modules["network"]["count"] == "local.network_enabled ? 1 : 0"
    assert modules["image"]["count"] == "var.bot_enabled ? 1 : 0"
    assert modules["bot"]["count"] == "var.bot_enabled ? 1 : 0"
    assert modules["records"]["count"] == "var.records_enabled ? 1 : 0"
    assert modules["tasks"]["count"] == "var.task_runner_enabled ? 1 : 0"
    assert modules["task_results"]["count"] == "var.task_runner_enabled ? 1 : 0"


def test_gated_modules_are_only_referenced_by_index() -> None:
    """Outside the moved blocks, an unindexed reference to a counted module is invalid."""
    for path in (REPO_ROOT / "stacks" / "bot").glob("*.tf"):
        for line in path.read_text().splitlines():
            code = line.split("#", 1)[0]
            if re.fullmatch(r"\s*from\s*=\s*module\.(image|bot|network)\s*", code):
                continue
            unindexed = re.findall(r"module\.(?:image|bot|network)\b(?!\[0\])", code)
            assert not unindexed, f"{path.name}: {line.strip()}"


def test_outputs_keep_their_names_and_are_null_safe() -> None:
    outputs = _bot_stack("output", "outputs.tf")
    expected = {
        "image_repository_url": "module.image[0].url",
        "instance_id": "module.bot[0].instance_id",
        "log_group_name": "module.bot[0].log_group_name",
        "parameter_names": "module.bot[0].parameter_names",
        "records_uri": "module.bot[0].records_uri",
        "vpc_id": "module.network[0].vpc_id",
    }
    for name, source in expected.items():
        assert outputs[name]["value"] == f"try({source}, null)"
    assert set(outputs) == {
        *expected,
        "task_launch_template",
        "task_log_group",
        "task_results_uri",
        "dataset_uris",
        "task_profile_launch_templates",
    }


def test_no_output_follows_the_public_ip() -> None:
    """A scheduled bot gets a new public IP at every start, so an output of it
    would put a change in every plan. `bot status` reads the IP from EC2."""
    outputs = _bot_stack("output", "outputs.tf")
    assert "public_ip" not in outputs
    assert not [name for name, o in outputs.items() if "public_ip" in o["value"]]


def test_rust_toolchain_follows_the_rust_flags() -> None:
    modules = _bot_stack("module")
    assert modules["tasks"]["rust_toolchain"] == "var.task_rust ? var.task_rust_toolchain : null"
    assert (
        modules["task_profiles"]["rust_toolchain"]
        == "each.value.rust ? var.task_rust_toolchain : null"
    )


def test_datasets_receive_retention_and_write_once() -> None:
    dataset = _bot_stack("module")["datasets"]
    assert dataset["versioning"] == "each.value.versioning"
    assert dataset["expire_noncurrent_days"] == "each.value.expire_noncurrent_days"
    assert dataset["expire_prefixes"] == "each.value.expire_prefixes"
    main_tf = (REPO_ROOT / "stacks" / "bot" / "main.tf").read_text()
    assert re.search(
        r"write_once\s*=\s*one\(\[for d in p\.datasets : d\.write_once if d\.name == each\.key\]\)",
        main_tf,
    )


def _assert_keys_match_stack_variables(tfvars: dict[str, Any]) -> None:
    """Rendered keys are all declared, and every variable without a default is rendered."""
    variables = _bot_stack("variable", "variables.tf")
    assert set(tfvars) <= set(variables)
    assert {name for name, block in variables.items() if "default" not in block} <= set(tfvars)


def test_tfvars_keys_match_stack_variables(
    bot: Project, research: Project, settings: Settings
) -> None:
    _assert_keys_match_stack_variables(render_tfvars(bot, settings))
    _assert_keys_match_stack_variables(render_tfvars(research, settings))
    _assert_keys_match_stack_variables(render_tfvars(_dataset_only(research), settings))


def test_new_variables_are_typed_for_the_rendered_values() -> None:
    """A key added to an object type but not to the tfvars (or back) fails `terraform plan`."""
    source = (REPO_ROOT / "stacks" / "bot" / "variables.tf").read_text()
    profiles = source[
        source.index('variable "task_profiles"') : source.index('variable "datasets"')
    ]
    assert re.search(r"^\s+rust\s+= bool$", profiles, re.MULTILINE)
    assert re.search(r"^\s+write_once = list\(string\)$", profiles, re.MULTILINE)
    datasets = source[source.index('variable "datasets"') :]
    assert re.search(r"^\s+versioning\s+= bool$", datasets, re.MULTILINE)
    assert re.search(r"^\s+expire_noncurrent_days\s+= number$", datasets, re.MULTILINE)
    assert re.search(r"^\s+expire_prefixes\s+= map\(number\)$", datasets, re.MULTILINE)


def test_research_uses_the_bot_stack(
    research: Project,
    settings: Settings,
    logger: logging.Logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JAWS_STACK_DIR", raising=False)
    monkeypatch.setenv("JAWS_STACKS_ROOT", "/somewhere/stacks")
    terraform = Terraform(research, settings, logger, plugin_dir=None)
    assert terraform.stack_dir == Path("/somewhere/stacks/bot")


def test_prepare_renders_a_research_project_into_the_bot_stack(
    research: Project, settings: Settings, logger: logging.Logger, fake_terraform: Path
) -> None:
    terraform = Terraform(research, settings, logger, plugin_dir=None)
    workdir = terraform.prepare()
    try:
        assert (workdir / "main.tf").read_text() == (
            REPO_ROOT / "stacks" / "bot" / "main.tf"
        ).read_text()
        assert json.loads((workdir / "terraform.tfvars.json").read_text())["bot_enabled"] is False
    finally:
        terraform.cleanup(failed=False)


# -- releasing dataset buckets from state --------------------------------------


def test_dataset_bucket_addresses_keeps_the_buckets_and_leaves_the_grants() -> None:
    bucket = 'module.datasets["nnue"].aws_s3_bucket.this'
    policy = 'module.datasets["nnue"].aws_s3_bucket_policy.this'
    lifecycle = 'module.datasets["nnue"].aws_s3_bucket_lifecycle_configuration.this'
    state = [
        "aws_s3_bucket.outside_the_module",
        "module.records[0].aws_s3_bucket.this",
        'module.datasets_old["nnue"].aws_s3_bucket.this',
        lifecycle,
        'module.datasets["nnue"].aws_iam_role_policy.grant["x"]',
        'module.datasets["nnue"].aws_iam_role_policy.writer["x"]',
        'module.datasets["nnue"].data.aws_s3_bucket.lookup',
        bucket,
        policy,
    ]
    assert dataset_bucket_addresses(state) == [lifecycle, bucket, policy]


@pytest.mark.parametrize(
    "address",
    [
        # A role whose name holds the type, in the instance key.
        'module.datasets["nnue"].aws_iam_role_policy.grant["aws_s3_bucket.this"]',
        # A dataset whose name holds the type, or looks like an address.
        'module.datasets["aws_s3_bucket"].aws_iam_role_policy.grant["x"]',
        'module.datasets["a.aws_s3_bucket.b"].aws_iam_role_policy.writer["x"]',
        'module.datasets["a\\"].aws_s3_bucket.b"].aws_iam_role_policy.grant["x"]',
    ],
)
def test_dataset_bucket_addresses_ignores_names_holding_the_type(address: str) -> None:
    assert dataset_bucket_addresses([address]) == []


def test_dataset_bucket_addresses_finds_a_bucket_of_a_dataset_named_like_one() -> None:
    address = 'module.datasets["aws_s3_bucket_x"].aws_s3_bucket.this'
    assert dataset_bucket_addresses([address]) == [address]


def test_dataset_bucket_addresses_of_nothing() -> None:
    assert dataset_bucket_addresses([]) == []


def test_dataset_names_are_those_with_a_released_bucket() -> None:
    state = [
        'module.datasets["b"].aws_s3_bucket.this',
        'module.datasets["a"].aws_s3_bucket.this',
        'module.datasets["a"].aws_s3_bucket_policy.this',
        'module.datasets["c"].aws_iam_role_policy.grant["x"]',
    ]
    assert dataset_names(dataset_bucket_addresses(state)) == ["a", "b"]


# -- Databricks projects: two stacks, the secret only in the environment -------

DATABRICKS_SENTINEL = "S3CR3T-SENTINEL"

#: What the account stack hands the workspace stack (its outputs, by name).
ACCOUNT_OUTPUTS: dict[str, Any] = {
    "workspace_id": "1234567890123456",
    "workspace_url": "https://jwall-databricks-poc.cloud.databricks.com",
    "admin_group_name": "databricks-poc-workspace-admins",
    "users_group_name": "databricks-poc-workspace-users",
    "metastore_id": "abcdef01-2345-6789-abcd-ef0123456789",
    "root_bucket_name": "jaws-databricks-poc-databricks-root",
}

ACCOUNT_TFVARS_KEYS = {
    "deployer",
    "project",
    "name_root",
    "environment",
    "repository",
    "tags",
    "vpc_cidr",
    "nat_ami_name",
    "metastore_name",
    "deployment_name",
    "admin_user_names",
    "user_names",
    "service_principal_application_id",
    "account_id",
    "read_only_datasets",
}

WORKSPACE_TFVARS_KEYS = {
    "project",
    "name_root",
    "environment",
    "repository",
    "tags",
    "workspace_url",
    "workspace_id",
    "admin_group_name",
    "users_group_name",
    "metastore_id",
    "compute_policies",
    "fixed_tags",
    "apply_role_arn",
    "management_role_arns",
    "catalog_tags",
}


@pytest.fixture
def databricks(settings: Settings) -> Project:
    return Project.from_config(
        load_site_config(FIXTURES / "bots" / "databricks-poc.yaml"), settings
    )


def test_databricks_account_tfvars(databricks: Project, settings: Settings) -> None:
    tfvars = _databricks_account_tfvars(databricks, settings)
    assert set(tfvars) == ACCOUNT_TFVARS_KEYS
    assert settings.databricks is not None
    assert tfvars == {
        "project": "databricks-poc",
        "name_root": "jaws",
        "environment": "prod",
        "repository": "example-org/databricks-poc",
        "tags": databricks.databricks_tags,
        "vpc_cidr": "10.40.0.0/16",
        "nat_ami_name": settings.databricks.nat_ami,
        "metastore_name": "jaws-us-east-1",
        "deployment_name": None,  # no prefix configured: Databricks picks the URL
        "admin_user_names": ["jimmy.wallace145@gmail.com"],
        "user_names": ["user@example.com"],  # the project file's users, not config/projects.yaml
        "service_principal_application_id": settings.databricks.client_id,
        "account_id": settings.databricks.account_id,
        "read_only_datasets": {},  # databricks-poc consumes no shared dataset
        "deployer": None,  # the project file asks for none
    }
    assert tfvars["tags"]["CostCenter"] == "cc-0000"
    assert tfvars["tags"]["Workspace"] == "databricks-poc-prod"


def _registered(settings: Settings, owner: str, owner_id: str = "2222") -> Settings:
    """`settings` with databricks-poc onboarded under `owner`, as repository ID 1111."""
    raw = settings.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    entry = project_entry(raw, "databricks-poc")
    offboard(raw, "databricks-poc")
    entry.update(repository="databricks-poc", repository_id="1111")
    group = raw["projects"].setdefault(owner, {"owner_id": owner_id, "projects": {}})
    group["projects"]["databricks-poc"] = entry
    return Settings.model_validate(raw)


def _databricks_with_deployer(tmp_path: Path, settings: Settings) -> Project:
    raw = yaml.safe_load((FIXTURES / "bots" / "databricks-poc.yaml").read_text())
    raw["components"][0]["deployer"] = True
    path = tmp_path / "jaws.yaml"
    path.write_text(yaml.safe_dump(raw))
    return Project.from_config(load_site_config(path), settings)


def test_databricks_account_tfvars_deployer_comes_from_the_registry(
    tmp_path: Path, settings: Settings
) -> None:
    registered = _registered(settings, "example-org")
    project = _databricks_with_deployer(tmp_path, registered)
    assert _databricks_account_tfvars(project, registered)["deployer"] == {
        "repository": "example-org/databricks-poc",
        "repository_id": "1111",
        "owner_id": "2222",
    }


# A registered project without numeric IDs cannot reach the stack: the loader
# refuses a repository_id or owner_id that is not digits (tests/test_settings.py).


def test_a_deployer_whose_registry_repository_differs_is_refused(
    tmp_path: Path, settings: Settings
) -> None:
    registered = _registered(settings, "someone-else")
    project = _databricks_with_deployer(tmp_path, registered)
    with pytest.raises(
        ConfigError, match=r"example-org/databricks-poc.*someone-else/databricks-poc"
    ):
        _databricks_account_tfvars(project, registered)


def test_without_a_deployer_no_registry_ids_are_needed(
    databricks: Project, settings: Settings
) -> None:
    assert _databricks_account_tfvars(databricks, settings)["deployer"] is None


def test_databricks_tfvars_are_json_serialisable(databricks: Project, settings: Settings) -> None:
    json.dumps(_databricks_account_tfvars(databricks, settings))
    json.dumps(_databricks_workspace_tfvars(databricks, settings, ACCOUNT_OUTPUTS))


def _with_prefix(settings: Settings, prefix: str | None) -> Settings:
    assert settings.databricks is not None
    section = settings.databricks.model_copy(update={"deployment_name_prefix": prefix})
    return settings.model_copy(update={"databricks": section})


def _with_deployment_name(project: Project, name: str | None) -> Project:
    components = tuple(
        c.model_copy(update={"deployment_name": name}) for c in project.config.components
    )
    return project.model_copy(
        update={"config": project.config.model_copy(update={"components": components})}
    )


def test_config_leaves_the_deployment_name_prefix_unset(settings: Settings) -> None:
    assert settings.databricks is not None
    assert settings.databricks.deployment_name_prefix is None


def test_without_a_prefix_databricks_picks_the_url(databricks: Project, settings: Settings) -> None:
    assert _databricks_account_tfvars(databricks, settings)["deployment_name"] is None
    # The project file's name is ignored too: Databricks would reject it.
    named = _with_deployment_name(databricks, "poc-one")
    assert _databricks_account_tfvars(named, settings)["deployment_name"] is None


def test_with_a_prefix_the_deployment_name_is_the_project(
    databricks: Project, settings: Settings
) -> None:
    name = _databricks_account_tfvars(databricks, _with_prefix(settings, "acme"))["deployment_name"]
    assert name == "databricks-poc"
    assert re.fullmatch(r"^[a-z0-9-]{3,30}$", name)


def test_with_a_prefix_the_project_files_name_wins(databricks: Project, settings: Settings) -> None:
    named = _with_deployment_name(databricks, "poc-one")
    tfvars = _databricks_account_tfvars(named, _with_prefix(settings, "acme"))
    assert tfvars["deployment_name"] == "poc-one"


def test_deployment_name_of_the_longest_project_fits() -> None:
    longest = "a" * 21  # DATABRICKS_PROJECT_NAME_MAX
    assert deployment_name(longest, "acme") == longest


def test_too_long_deployment_name_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="deployment_name"):
        deployment_name("databricks-poc", "acme", "x" * 31)


def test_too_long_url_label_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="URL label"):
        deployment_name("databricks-poc", "p" * 40, "x" * 30)


def test_prefix_must_be_kebab_case(settings: Settings) -> None:
    raw = settings.model_dump()
    raw["databricks"]["deployment_name_prefix"] = "Acme_Corp"
    with pytest.raises(ValidationError):
        Settings.model_validate(raw)


def test_workspace_tfvars_take_account_outputs(databricks: Project, settings: Settings) -> None:
    tfvars = _databricks_workspace_tfvars(databricks, settings, ACCOUNT_OUTPUTS)
    assert set(tfvars) == WORKSPACE_TFVARS_KEYS
    for key in ("workspace_url", "workspace_id", "admin_group_name", "users_group_name"):
        assert tfvars[key] == ACCOUNT_OUTPUTS[key]
    assert tfvars["metastore_id"] == ACCOUNT_OUTPUTS["metastore_id"]
    assert tfvars["project"] == "databricks-poc"
    assert tfvars["environment"] == "prod"
    assert tfvars["repository"] == "example-org/databricks-poc"
    assert tfvars["tags"] == databricks.databricks_tags
    assert tfvars["fixed_tags"] == databricks.databricks_tags
    assert "governance_project" not in tfvars
    assert tfvars["apply_role_arn"] == (
        "arn:aws:iam::570327089884:role/jaws-databricks-poc-ci-apply"
    )
    assert tfvars["management_role_arns"] == [
        "arn:aws:iam::570327089884:role/jaws-databricks-poc-ci-plan"
    ]
    assert tfvars["catalog_tags"] == {"Project": "databricks-poc", "Owner": "owner@example.com"}


@pytest.mark.parametrize("stack", ["account", "workspace"])
def test_databricks_tfvars_are_valid_for_the_stack_variables(
    stack: str, databricks: Project, settings: Settings
) -> None:
    """Every variable stacks/databricks-<stack> declares is rendered, and nothing else."""
    tfvars = render_tfvars(databricks, settings, stack=stack, account_outputs=ACCOUNT_OUTPUTS)
    assert set(tfvars) == _declared(f"databricks-{stack}")


#: Account-stack outputs for people, not for the workspace stack: the deployer's
#: application ID goes to the project's GitHub environment `prod`.
ACCOUNT_OUTPUTS_FOR_PEOPLE = {"deployer_application_id"}


def test_account_stack_outputs_what_the_workspace_stack_takes() -> None:
    declared = {
        labels[0]
        for kind, labels, _ in _blocks(REPO_ROOT / "stacks" / "databricks-account" / "outputs.tf")
        if kind == "output"
    }
    assert declared == set(ACCOUNT_OUTPUTS) | ACCOUNT_OUTPUTS_FOR_PEOPLE


@pytest.mark.parametrize("stack", ["databricks-account", "databricks-workspace"])
def test_databricks_providers_take_credentials_from_the_environment(stack: str) -> None:
    """The client secret reaches Terraform only through the child's environment: no
    provider block names a credential, and no variable could carry one."""
    providers = [
        attributes
        for kind, labels, attributes in _blocks(REPO_ROOT / "stacks" / stack / "providers.tf")
        if kind == "provider" and labels == ["databricks"]
    ]
    assert len(providers) == 1
    (provider,) = providers
    assert provider["auth_type"] == '"oauth-m2m"'
    assert not {"client_id", "client_secret", "token", "password", "account_id"} & set(provider)
    assert not {v for v in _declared(stack) if "secret" in v or "token" in v}
    if stack == "databricks-account":
        assert provider["alias"] == '"account"'
        assert provider["host"] == '"https://accounts.cloud.databricks.com"'
    else:
        assert provider["alias"] == '"workspace"'
        assert provider["host"] == "var.workspace_url"


def test_workspace_tfvars_render_through_render_tfvars(
    databricks: Project, settings: Settings
) -> None:
    assert render_tfvars(
        databricks, settings, stack="workspace", account_outputs=ACCOUNT_OUTPUTS
    ) == _databricks_workspace_tfvars(databricks, settings, ACCOUNT_OUTPUTS)


@pytest.mark.parametrize(
    "missing",
    ["workspace_url", "workspace_id", "admin_group_name", "users_group_name", "metastore_id"],
)
def test_missing_account_output_is_a_config_error_naming_it(
    databricks: Project, settings: Settings, missing: str
) -> None:
    outputs = {k: v for k, v in ACCOUNT_OUTPUTS.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        _databricks_workspace_tfvars(databricks, settings, outputs)


def test_workspace_tfvars_without_outputs_is_a_config_error(
    databricks: Project, settings: Settings
) -> None:
    with pytest.raises(ConfigError, match="account stack"):
        render_tfvars(databricks, settings, stack="workspace")


def test_compute_policies_are_filtered_to_the_projects_file(
    databricks: Project, settings: Settings
) -> None:
    assert settings.databricks is not None
    central = settings.databricks.compute_policies
    extra = central["jobs"].model_copy(update={"description": "Not this project's"})
    widened = settings.model_copy(
        update={
            "databricks": settings.databricks.model_copy(
                update={"compute_policies": {**central, "gpu-large": extra}}
            )
        }
    )
    only_jobs = databricks.model_copy(
        update={
            "config": databricks.config.model_copy(
                update={
                    "components": tuple(
                        c.model_copy(update={"compute_policies": ("jobs",)})
                        for c in databricks.config.components
                    )
                }
            )
        }
    )
    assert only_jobs.databricks.compute_policies == ("jobs",)
    policies = _databricks_workspace_tfvars(only_jobs, widened, ACCOUNT_OUTPUTS)["compute_policies"]
    assert policies == {
        "jobs": {
            "description": central["jobs"].description,
            "definition": json.dumps(central["jobs"].definition, sort_keys=True),
        }
    }
    full = _databricks_workspace_tfvars(databricks, widened, ACCOUNT_OUTPUTS)["compute_policies"]
    assert set(full) == {"small-interactive", "jobs"}
    definition = full["small-interactive"]["definition"]
    assert isinstance(definition, str)
    assert definition == json.dumps(json.loads(definition), sort_keys=True)
    assert json.loads(definition)["num_workers"] == {
        "type": "range",
        "maxValue": 2,
    }


def test_databricks_is_routed_away_from_bot_and_research(
    databricks: Project, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any) -> dict[str, Any]:
        raise AssertionError("a databricks project reached the bot stack's tfvars")

    monkeypatch.setattr(stack_module, "_bot_tfvars", refuse)
    monkeypatch.setattr(stack_module, "_research_tfvars", refuse)
    monkeypatch.setattr(stack_module, "_lichess_bot_tfvars", refuse)
    tfvars = render_tfvars(databricks, settings, stack="account")
    assert set(tfvars) == ACCOUNT_TFVARS_KEYS
    assert "bot_enabled" not in tfvars


def test_databricks_needs_a_known_stack(databricks: Project, settings: Settings) -> None:
    with pytest.raises(ValueError, match="stack"):
        render_tfvars(databricks, settings)
    with pytest.raises(ValueError, match="stack"):
        render_tfvars(databricks, settings, stack="bogus")


def test_existing_kinds_ignore_the_new_arguments(
    bot: Project, research: Project, guitar: Site, settings: Settings
) -> None:
    assert render_tfvars(bot, settings) == render_tfvars(bot, settings, stack=None)
    assert render_tfvars(research, settings)["bot_enabled"] is False
    assert render_tfvars(guitar) == render_tfvars(guitar, settings)


def test_per_stack_state_keys(
    databricks: Project, settings: Settings, logger: logging.Logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("JAWS_STACK_DIR", raising=False)
    monkeypatch.setenv("JAWS_STACKS_ROOT", "/somewhere/stacks")
    account = Terraform(databricks, settings, logger, plugin_dir=None, stack="account")
    workspace = Terraform(
        databricks,
        settings,
        logger,
        plugin_dir=None,
        stack="workspace",
        tfvars_override={"project": "databricks-poc"},
    )
    assert account.stack_dir == Path("/somewhere/stacks/databricks-account")
    assert workspace.stack_dir == Path("/somewhere/stacks/databricks-workspace")
    assert account.stack_name == "databricks-account"
    assert workspace.stack_name == "databricks-workspace"
    assert account.state_key == (
        "project=databricks-poc/env=prod/databricks-poc-prod-account.tfstate"
    )
    assert workspace.state_key == (
        "project=databricks-poc/env=prod/databricks-poc-prod-workspace.tfstate"
    )
    assert f'key          = "{account.state_key}"\n' in account.backend()
    assert f'key          = "{workspace.state_key}"\n' in workspace.backend()
    # The project's own key (no stack) is never used for a Databricks stack.
    assert databricks.state_key not in (account.state_key, workspace.state_key)


def test_existing_kinds_keep_their_stack_and_key(
    bot: Project, guitar: Site, settings: Settings, logger: logging.Logger
) -> None:
    terraform = Terraform(bot, settings, logger, plugin_dir=None)
    assert terraform.state_key == bot.state_key
    assert terraform.stack_name == "bot"
    assert terraform.backend() == render_backend(bot)
    site = Terraform(guitar, settings, logger, plugin_dir=None)
    assert site.backend() == render_backend(guitar)


def _databricks_stack_dir(tmp_path: Path) -> Path:
    stack = tmp_path / "stack"
    stack.mkdir()
    (stack / "main.tf").write_text("# empty\n")
    return stack


def test_secret_only_in_env(
    databricks: Project,
    settings: Settings,
    logger: logging.Logger,
    fake_terraform: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    env_dump = tmp_path / "child.env"
    monkeypatch.setenv("FAKE_TF_ENV", str(env_dump))
    caplog.set_level(logging.DEBUG)
    secret_env = terraform_env(settings, DATABRICKS_SENTINEL)
    stack_dir = _databricks_stack_dir(tmp_path)
    for stack, override in (
        ("account", None),
        ("workspace", _databricks_workspace_tfvars(databricks, settings, ACCOUNT_OUTPUTS)),
    ):
        terraform = Terraform(
            databricks,
            settings,
            logger,
            stack_dir=stack_dir,
            plugin_dir=None,
            stack=stack,
            extra_env=secret_env,
            tfvars_override=override,
        )
        workdir = terraform.prepare()
        try:
            terraform.init()
            terraform.plan(detailed_exitcode=True)
            tfvars = (workdir / "terraform.tfvars.json").read_text()
            backend = (workdir / "backend.hcl").read_text()
            assert DATABRICKS_SENTINEL not in tfvars
            assert DATABRICKS_SENTINEL not in backend
            assert json.loads(tfvars)["project"] == "databricks-poc"
            if override is not None:
                assert json.loads(tfvars) == override
        finally:
            terraform.cleanup(failed=False)

    assert caplog.records, "the debug log must have been captured"
    assert DATABRICKS_SENTINEL not in caplog.text
    assert all(DATABRICKS_SENTINEL not in repr(r.args) for r in caplog.records)
    child = env_dump.read_text()
    assert f"DATABRICKS_CLIENT_SECRET={DATABRICKS_SENTINEL}" in child
    assert f"DATABRICKS_CLIENT_ID={settings.databricks.client_id}" in child  # type: ignore[union-attr]
    assert "TF_IN_AUTOMATION=1" in child
    assert DATABRICKS_SENTINEL not in fake_terraform.read_text()  # the argv log


def test_extra_env_is_not_in_the_parent_environment(
    databricks: Project, settings: Settings, logger: logging.Logger
) -> None:
    terraform = Terraform(
        databricks,
        settings,
        logger,
        plugin_dir=None,
        stack="account",
        extra_env={"DATABRICKS_CLIENT_SECRET": DATABRICKS_SENTINEL},
    )
    assert terraform._environment()["DATABRICKS_CLIENT_SECRET"] == DATABRICKS_SENTINEL
    assert "DATABRICKS_CLIENT_SECRET" not in os.environ
    assert DATABRICKS_SENTINEL not in repr(terraform)


# -- readers and endpoints from handshakes (access.py) -----------------------------

_ROLES = "arn:aws:iam::570327089884:role/"
_TRAINER_GPU = _ROLES + "jaws-braveheart-trainer-task-gpu"
_POSITIONS_ROLE = _ROLES + "jaws-ds-braveheart-selfplay-positions"


def _registry_project(name: str, settings: Settings) -> Project:
    return Project.from_config(load_site_config(FIXTURES / "registry" / f"{name}.yaml"), settings)


def _access(consumer_reads: bool = True) -> Any:
    from jaws.access import compute_access, load_registry

    consumer = load_site_config(FIXTURES / "registry" / "braveheart-databricks.yaml")
    if not consumer_reads:
        workspace = consumer.components[0]
        consumer = consumer.model_copy(
            update={"components": [workspace.model_copy(update={"reads": ()})]}
        )
    return compute_access(
        load_registry(FIXTURES / "datasets"),
        {
            "braveheart-selfplay": load_site_config(
                FIXTURES / "registry" / "braveheart-selfplay.yaml"
            ),
            "braveheart-databricks": consumer,
        },
    )


def test_a_shared_dataset_names_its_platform_role_as_a_reader(settings: Settings) -> None:
    tfvars = render_tfvars(
        _registry_project("braveheart-selfplay", settings), settings, access=_access()
    )
    (dataset,) = tfvars["datasets"]
    assert dataset["readers"] == [_TRAINER_GPU, _POSITIONS_ROLE]


def test_a_pending_handshake_adds_no_reader(settings: Settings) -> None:
    project = _registry_project("braveheart-selfplay", settings)
    for access in (_access(consumer_reads=False), None):
        (dataset,) = render_tfvars(project, settings, access=access)["datasets"]
        assert dataset["readers"] == [_TRAINER_GPU]


def test_the_consumer_endpoint_gets_each_edge(settings: Settings) -> None:
    project = _registry_project("braveheart-databricks", settings)
    tfvars = render_tfvars(project, settings, stack="account", access=_access())
    assert tfvars["read_only_datasets"] == {
        "braveheart-selfplay-positions": {
            "bucket": "jaws-braveheart-selfplay-positions",
            "prefix": "data/",
            "role_arn": _POSITIONS_ROLE,
        }
    }
    pending = render_tfvars(
        project, settings, stack="account", access=_access(consumer_reads=False)
    )
    assert pending["read_only_datasets"] == {}


def test_the_records_bucket_admins_are_the_break_glass_principals(
    bot: Project, settings: Settings
) -> None:
    """The stack adds the project's apply role, which applies the bucket; the CLI
    names the owner's admin role and root of the primary account."""
    assert render_tfvars(bot, settings)["bucket_admin_principal_arns"] == [
        settings.aws.admin_role_arn,
        f"arn:aws:iam::{settings.aws.account_id}:root",
    ]
    main = (REPO_ROOT / "stacks" / "bot" / "main.tf").read_text()
    admins = "admin_principal_arns = distinct(concat(var.bucket_admin_principal_arns, "
    assert admins + '["${local.ci_role_arn}-apply"]))' in main
    assert 'listers              = ["${local.ci_role_arn}-plan"]' in main
    assert "{ (var.records_prefix) = [module.bot[0].role_arn] }" in main
