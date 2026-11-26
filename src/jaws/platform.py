"""The platform's own stacks: the foundation, monitoring and data access.

A hub's workflows run them from the image, which holds each root module at
/opt/jaws/stacks/<name>, as `jaws platform plan|apply <stack>`. Each run works in a
copy of the stack's directory. Each backend is the stack's `backend/prod.hcl`, built
from `state`: the state `jaws`'s own workflows plan and apply, so no state moves
(spec 6.10). The stacks read the configuration themselves, from the paths in their
environment. The Databricks credential, for a stack that needs it, reaches Terraform's
environment and nothing else.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Literal

from . import github, report
from .diagnose import _redact
from .errors import ConfigError, RunError
from .log import phase
from .product import PLAN_COMMENT_MAX_BYTES
from .settings import Settings
from .site import ENVIRONMENT
from .stack import PLAN_CHANGES, PLAN_ERROR, Terraform, default_plugin_dir, default_stack_dir


@dataclass(frozen=True)
class PlatformStack:
    """One of the platform's own stacks."""

    #: Its root module's directory: the image's /opt/jaws/stacks/<name>.
    name: str
    #: The project its state key and its CI roles are named for.
    state_project: str
    #: Whether it manages Databricks, and so needs the Databricks credential.
    databricks: bool


#: The platform's stacks by name. Nothing else runs as one.
PLATFORM_STACKS: Mapping[str, PlatformStack] = {
    "foundation": PlatformStack("foundation", state_project="infra", databricks=True),
    "monitoring": PlatformStack("monitoring", state_project="monitoring", databricks=False),
    "data-access": PlatformStack("data-access", state_project="data-access", databricks=True),
}


def platform_stack(name: str) -> PlatformStack:
    """The platform's stack `name`. Any other name is refused."""
    found = PLATFORM_STACKS.get(name)
    if found is None:
        raise ConfigError(
            f"{name} is not one of the platform's stacks: {', '.join(PLATFORM_STACKS)}"
        )
    return found


def platform_backend(settings: Settings, stack: PlatformStack) -> str:
    """backend.hcl for `terraform init -backend-config=`: the stack's backend/prod.hcl,
    laid out the same way, from `state`."""
    return (
        f'bucket       = "{settings.state.bucket}"\n'
        f'key          = "{settings.state_key(stack.state_project, ENVIRONMENT)}"\n'
        f'region       = "{settings.state.region}"\n'
        "use_lockfile = true\n"
        "encrypt      = true\n"
    )


def platform_role(settings: Settings, stack: PlatformStack, role: Literal["plan", "apply"]) -> str:
    """The CI role a run of the stack must be: `<name_root>-<state_project>-ci-<role>`."""
    return f"{settings.context.name_root}-{stack.state_project}-ci-{role}"


def platform_subject(settings: Settings, stack: PlatformStack) -> str:
    """What the stack's plan comment and summaries are about: `<name_root>/<name>`."""
    return f"{settings.context.name_root}/{stack.name}"


def stack_variables(stack: PlatformStack, config_path: Path, datasets_path: Path) -> dict[str, str]:
    """The stack's variables, for Terraform's environment. The foundation reads the
    configuration and the onboarded datasets, monitoring the configuration, and data
    access neither."""
    if stack.name == "foundation":
        return {"TF_VAR_config_path": str(config_path), "TF_VAR_datasets_path": str(datasets_path)}
    if stack.name == "monitoring":
        return {"TF_VAR_config_path": str(config_path)}
    return {}


class PlatformTerraform(Terraform):
    """Terraform for one of the platform's stacks, in a working copy of its directory.

    `Terraform.__init__` is not called: it takes a site or a project, reads its state
    key and picks stacks/site for anything but a project. This sets what the commands
    use instead. The tfvars are empty, and `extra_env` (the stack's variables and any
    credential) reaches only the Terraform process.
    """

    def __init__(
        self,
        stack: PlatformStack,
        settings: Settings,
        logger: Logger,
        extra_env: Mapping[str, str] = {},  # copied, never mutated
    ) -> None:
        self.platform_stack = stack
        self.settings = settings
        self.logger = logger
        self.stack_name = stack.name
        self.stack_dir = default_stack_dir(stack.name)
        self.plugin_dir = default_plugin_dir()
        self.binary = "terraform"
        self.workdir = None
        self._extra_env = dict(extra_env)
        self.tfvars_override = {}

    def backend(self) -> str:
        return platform_backend(self.settings, self.platform_stack)

    def _environment(self) -> Mapping[str, str]:
        """As `Terraform._environment`, in the state's region: no target gives one."""
        region = self.settings.state.region
        env = dict(os.environ)
        env.update(
            {
                "TF_IN_AUTOMATION": "1",
                "TF_INPUT": "0",
                "AWS_REGION": region,
                "AWS_DEFAULT_REGION": region,
            }
        )
        env.update(self._extra_env)  # credentials: never logged or written to a file
        return env


@contextmanager
def _working_copy(terraform: Terraform) -> Iterator[Path]:
    """The stack's working copy, removed afterwards (kept after a failure when asked)."""
    failed = True
    try:
        workdir = terraform.prepare()
        yield workdir
        failed = False
    finally:
        terraform.cleanup(failed=failed)


def plan(
    terraform: PlatformTerraform, artifacts: Path, version: str, secrets: Sequence[str]
) -> None:
    """Plan the stack, then write .jaws/plan.txt, the plan comment, the outputs `result`
    and `changes`, and the step summary. A failed plan is written and commented, then
    raised. `secrets` are masked in the plan text."""
    settings = terraform.settings
    subject = platform_subject(settings, terraform.platform_stack)
    exit_code = PLAN_ERROR
    plan_text = ""
    try:
        with _working_copy(terraform):
            with phase("init"):
                terraform.init()
            with phase("plan"):
                result = terraform.plan(detailed_exitcode=True)
            exit_code, plan_text = result.returncode, result.output
    except RunError as exc:
        plan_text = exc.output or ""  # what Terraform printed as it failed
        raise
    finally:
        plan_text = _redact(plan_text, secrets)
        (artifacts / "plan.txt").write_text(plan_text)
        comment = report.plan_comment(
            exit_code,
            plan_text,
            PLAN_COMMENT_MAX_BYTES,
            subject,
            github.provenance(version),
            brand=settings.brand,
        )
        (artifacts / "plan-comment.md").write_text(comment)
        github.write_output("result", report.plan_result_name(exit_code))
        github.write_output("changes", "true" if exit_code == PLAN_CHANGES else "false")
    github.append_summary(
        report.run_summary(
            f"Terraform plan: {report.plan_result_name(exit_code)}",
            {"stack": subject, "tool": version},
        )
    )


def apply(terraform: PlatformTerraform, version: str) -> None:
    """Plan the stack, and apply the saved plan only when it has changes: the sweep's
    rule. Then write the output `result`, `no-changes` or `applied`, and the step summary."""
    subject = platform_subject(terraform.settings, terraform.platform_stack)
    with _working_copy(terraform) as workdir:
        with phase("init"):
            terraform.init()
        planfile = workdir / "tfplan"
        with phase("plan"):
            planned = terraform.plan(out=planfile, detailed_exitcode=True)
        if planned.returncode == PLAN_CHANGES:
            with phase("apply"):
                terraform.apply(planfile)
            result = "applied"
        else:
            terraform.logger.info("%s has no changes: nothing to apply", subject)
            result = "no-changes"
    github.write_output("result", result)
    github.append_summary(
        report.run_summary(f"Terraform apply: {result}", {"stack": subject, "tool": version})
    )
