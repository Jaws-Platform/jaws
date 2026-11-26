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

import json
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Any, Literal

import yaml

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
    use instead. The tfvars are empty unless given (data access's are rendered), `files`
    are written into the working copy, and `extra_env` (the stack's variables and any
    credential) reaches only the Terraform process.
    """

    def __init__(
        self,
        stack: PlatformStack,
        settings: Settings,
        logger: Logger,
        extra_env: Mapping[str, str] = {},  # copied, never mutated
        tfvars: Mapping[str, Any] = {},
        files: Mapping[str, str] = {},
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
        self.tfvars_override = dict(tfvars)
        self.files = dict(files)

    def prepare(self) -> Path:
        """As `Terraform.prepare`, then `files` (name to text) beside the stack's."""
        workdir = super().prepare()
        for name, text in self.files.items():
            (workdir / name).write_text(text)
        return workdir

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
    terraform: PlatformTerraform,
    artifacts: Path,
    version: str,
    secrets: Sequence[str],
    comment_suffix: str = "",
) -> None:
    """Plan the stack, then write .jaws/plan.txt, the plan comment, the outputs `result`
    and `changes`, and the step summary. A failed plan is written and commented, then
    raised. `secrets` are masked in the plan text. `comment_suffix` follows the comment,
    after a blank line."""
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
        if comment_suffix:
            comment += "\n" + comment_suffix
        (artifacts / "plan-comment.md").write_text(comment)
        github.write_output("result", report.plan_result_name(exit_code))
        github.write_output("changes", "true" if exit_code == PLAN_CHANGES else "false")
    github.append_summary(
        report.run_summary(
            f"Terraform plan: {report.plan_result_name(exit_code)}",
            {"stack": subject, "tool": version},
        )
    )


#: The outputs of data access's applied state that its step summary shows.
SWEEP_OUTPUTS = ("edges", "awaiting_onboarding", "missing_workspaces")


def sweep_failed(access_summary: str | None) -> None:
    """Write the sweep's step summary for a failed run: no result and no applied state."""
    text = "**Sweep: failed**\n"
    if access_summary is not None:
        text += f"\n{access_summary}"
    github.append_summary(text)


def apply(terraform: PlatformTerraform, version: str, sweep_summary: str | None = None) -> None:
    """Plan the stack, and apply the saved plan only when it has changes: the sweep's
    rule. Then write the output `result`, `no-changes` or `applied`, and the step summary.

    Given `sweep_summary` (data access's access summary), the step summary is the sweep's
    instead: the result, that summary and the applied state's outputs."""
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
        applied = terraform.outputs() if sweep_summary is not None else {}
    github.write_output("result", result)
    if sweep_summary is None:
        github.append_summary(
            report.run_summary(f"Terraform apply: {result}", {"stack": subject, "tool": version})
        )
        return
    state = json.dumps({name: applied.get(name) for name in SWEEP_OUTPUTS}, indent=2)
    github.append_summary(
        f"**Sweep: {result}**\n\n{sweep_summary.rstrip()}\n\n"
        f"### Applied state\n\n```json\n{state}\n```\n"
    )


# -- the hub's check ------------------------------------------------------------------

#: The workflows that run a project as the platform, so take its identity as inputs.
IDENTITY_WORKFLOWS = frozenset(
    {
        "site-plan.yml",
        "site-preview.yml",
        "site-deploy.yml",
        "remote-task.yml",
        "container-release.yml",
        "platform-release.yml",
        "platform-rollback.yml",
        "platform-bot-apply.yml",
        "platform-databricks-apply.yml",
        "platform-sweep.yml",
    }
)
#: The workflows that also name their checks with the brand's `check_prefix`.
CHECK_PREFIX_WORKFLOWS = frozenset({"site-plan.yml", "site-preview.yml", "site-deploy.yml"})
#: A hub Dockerfile's one FROM. `platform-base` holds it verbatim, so the check and the
#: build read one FROM alike.
FROM_PATTERN = r"^FROM ([^ @]+):(v[0-9]+\.[0-9]+\.[0-9]+)@(sha256:[0-9a-f]{64})$"
_CALL = re.compile(r"^Jaws-Platform/jaws/\.github/workflows/([^@/]+)@(.+)$")
_WORKFLOWS = Path(".github/workflows")


@dataclass(frozen=True)
class HubProblem:
    """One way a hub's pins or identity disagree: `path` is relative to the hub's root."""

    path: str
    message: str


def _identity_keys(file: str) -> tuple[str, ...]:
    keys = ("platform-image", "account-id", "name-root")
    return (*keys, "check-prefix") if file in CHECK_PREFIX_WORKFLOWS else keys


def _check_key(job: str, key: str, value: object, expected: str | None) -> str | None:
    """What is wrong with the literal `value` of input `key`, or None."""
    if not isinstance(value, str):
        return f"job {job} passes {key} as {value!r}: pass {key} as a quoted string"
    if "${{" in value:
        return (
            f"job {job} passes {key} as an expression: a project's run needs the "
            "platform's identity before it can read anything, so it is a literal"
        )
    if expected is not None and value != expected:
        return f"job {job} passes {key}: {value!r}, but the configuration says {expected!r}"
    return None


def _check_workflow(
    path: str, document: object, tag: str | None, expected: Mapping[str, str | None]
) -> tuple[list[HubProblem], int]:
    """The problems in one workflow's calls of Jaws's, and how many calls it makes."""
    jobs = document.get("jobs") if isinstance(document, dict) else None
    problems: list[HubProblem] = []
    calls = 0
    for job, spec in jobs.items() if isinstance(jobs, dict) else ():
        called = _CALL.match(str(spec.get("uses", ""))) if isinstance(spec, dict) else None
        if called is None:
            continue
        calls += 1
        file, ref = called.groups()
        if tag is not None and ref != tag:
            problems.append(
                HubProblem(
                    path,
                    f"job {job} calls Jaws-Platform/jaws at {ref}, but the Dockerfile pins "
                    f"{tag}: one pull request bumps every pin",
                )
            )
        passed = spec.get("with")
        passed = passed if isinstance(passed, dict) else {}
        if file not in IDENTITY_WORKFLOWS:
            continue
        for key in _identity_keys(file):
            if key not in passed:
                message: str | None = (
                    f"job {job} calls {file} without {key}: it would run as one of "
                    "Jaws's own projects, not this platform's"
                )
            else:
                message = _check_key(str(job), key, passed[key], expected[key])
            if message is not None:
                problems.append(HubProblem(path, message))
    return problems, calls


def check_hub(
    root: Path, settings: Settings, version: str, repository: str | None
) -> list[HubProblem]:
    """Where the hub at `root` disagrees with its configuration and the image running this.

    `version` is the Jaws the image runs; `repository` is where the check runs. Nothing
    comes back when the hub agrees."""
    problems: list[HubProblem] = []
    dockerfile = root / "Dockerfile"
    froms = (
        [line for line in dockerfile.read_text().splitlines() if line.startswith("FROM ")]
        if dockerfile.is_file()
        else []
    )
    matched = re.match(FROM_PATTERN, froms[0]) if len(froms) == 1 else None
    tag = matched.group(2) if matched else None
    if matched is None:
        line = froms[0] if len(froms) == 1 else ("\n".join(froms) if froms else "")
        problems.append(
            HubProblem(
                "Dockerfile",
                "FROM must pin the Jaws image by tag and digest "
                f"(FROM public.ecr.aws/<alias>/jaws:vX.Y.Z@sha256:…), not {line!r}",
            )
        )
    elif tag != f"v{version}":
        problems.append(
            HubProblem(
                "Dockerfile",
                f"the Dockerfile pins {tag}, but the image it built runs Jaws v{version}: "
                "its digest is another release's",
            )
        )

    hub = settings.platform.hub
    expected: dict[str, str | None] = {
        "platform-image": hub.image if hub else None,
        "account-id": settings.aws.account_id,
        "name-root": settings.context.name_root,
        "check-prefix": settings.brand.check_prefix,
    }
    calls = 0
    directory = root / _WORKFLOWS
    files = (
        sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")]) if directory.is_dir() else []
    )
    for file in files:
        found, count = _check_workflow(
            file.relative_to(root).as_posix(), yaml.safe_load(file.read_text()), tag, expected
        )
        problems += found
        calls += count
    if calls == 0:
        problems.append(
            HubProblem(_WORKFLOWS.as_posix(), "no job calls a Jaws-Platform/jaws workflow")
        )

    if hub is None:
        problems.append(HubProblem("config", "platform.hub is not set (config/platform.yaml)"))
    elif repository is not None and hub.repository != repository:
        problems.append(
            HubProblem(
                "config",
                f"platform.hub.repository is {hub.repository}, but this check runs in {repository}",
            )
        )
    return problems
