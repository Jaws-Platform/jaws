"""`platform-ci.yml`: a hub's pull requests, and the three actions it builds with.

The candidate job builds the pull request as the hub's image, checks the hub inside it
offline, and passes it to every plan job as this run's artifact. It is never pushed (ruling
5): an ECR push grant can't be limited by tag, so a pull request role that could push a
candidate could also move `current`. Every plan runs with the candidate (spec 6.3, 6.5): the
foundation, monitoring, data access, and every site, bot, research and Databricks project,
each as its own plan role.

`platform-base` reads the Dockerfile's pinned Jaws base as `jaws platform check` reads it,
and asks ECR Public whether that pin is still published. `platform-build` builds the
Dockerfile with labels naming the base and the hub commit. `platform-project-file` checks
out a project's file and checks the project it names. Their scripts, and the candidate
job's, run here as Actions runs them, with stand-ins for `curl` and `docker`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from jaws import cli
from jaws.platform import FROM_PATTERN, check_hub
from jaws.settings import Settings
from tests.conftest import fixture_config
from tests.test_databricks_workflows import needs_yq
from tests.test_foundation_fixtures import HUB, HUB_REPOSITORY
from tests.test_public_image import FAKE_CURL
from tests.workflow_steps import ACTIONS, WORKFLOWS, action_step, job, run_action_step, run_step

CI = "platform-ci.yml"
#: The jobs that plan with the candidate, and the project each one's plan role is for.
PLAN_ROLES = {
    "foundation": "infra",
    "monitoring": "monitoring",
    "data-access": "data-access",
    "projects": "${{ matrix.project }}",
}
PLAN_JOBS = list(PLAN_ROLES)
TOOL = "./.jaws-tool/.github/actions"
BASE = f"{TOOL}/platform-base"
BUILD = f"{TOOL}/platform-build"
ROLE = f"{TOOL}/platform-role"
IMAGE = f"{TOOL}/platform-image"
PROJECT_FILE = f"{TOOL}/platform-project-file"
JAWS = f"{TOOL}/jaws"
CREDENTIALS = "aws-actions/configure-aws-credentials"
UPLOAD = "actions/upload-artifact"
APP_TOKEN = "actions/create-github-app-token"
COMMENT = "marocchino/sticky-pull-request-comment"
#: What a plan job runs the candidate by: the ID the candidate job's build reports.
CANDIDATE_ID = "${{ needs.candidate.outputs.image-id }}"
#: The candidate's image ID on a runner whose store names it by its config digest, and the
#: build's manifest digest, which the containerd store names it by.
IMAGE_ID = "sha256:" + "c" * 64
MANIFEST_DIGEST = "sha256:" + "b" * 64
#: The Jaws release the hub's Dockerfile builds on.
BASE_NAME = "public.ecr.aws/example-alias/jaws"
BASE_DIGEST = "sha256:" + "a" * 64
PINNED = f"FROM {BASE_NAME}:v0.81.0@{BASE_DIGEST}"
HUB_DOCKERFILE = (
    "# The hub's image: Jaws, and this platform's configuration. FROM pins it.\n"
    f"{PINNED}\n"
    "COPY config/ /etc/jaws/config/\n"
    "COPY datasets/ /etc/jaws/datasets/\n"
)


def _workflow() -> dict[Any, Any]:
    parsed: dict[Any, Any] = yaml.safe_load((WORKFLOWS / CI).read_text())
    return parsed


def _action(name: str) -> dict[str, Any]:
    parsed: dict[str, Any] = yaml.safe_load((ACTIONS / name / "action.yml").read_text())
    return parsed


def _steps(name: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = job(CI, name)["steps"]
    return steps


def _using(name: str, action: str) -> list[dict[str, Any]]:
    """The job's steps that use `action`: a local action's path, or a published action's
    `owner/name`, at any version."""
    return [
        s
        for s in _steps(name)
        if s.get("uses") == action or str(s.get("uses", "")).startswith(f"{action}@")
    ]


def _one(name: str, action: str) -> dict[str, Any]:
    found = _using(name, action)
    assert len(found) == 1, f"{name}: expected one {action} step, found {len(found)}"
    return found[0]


def _by_id(name: str, step_id: str) -> dict[str, Any]:
    (found,) = [s for s in _steps(name) if s.get("id") == step_id]
    return found


def _position(name: str, step: dict[str, Any]) -> int:
    """Where `step` is among the job's steps."""
    return _steps(name).index(step)


# -- the candidate --------------------------------------------------------------------

#: Stands in for docker in the candidate job: logs each call, and answers `config show`
#: with FAKE_SHOWN, `config env` and `config projects` with the files FAKE_ENV and
#: FAKE_PROJECTS, and `platform check` with its verdict.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
case "$*" in
  "run "*" config show") echo "$FAKE_SHOWN" ;;
  "run "*" platform check "*) echo "the hub's pins and identity agree: Jaws v0.81.0" ;;
  "run "*" config env "*) cat "$FAKE_ENV" ;;
  "run "*" config projects "*) cat "$FAKE_PROJECTS" ;;
  "save "*) ;;
  *) echo "unexpected: docker $*" >&2; exit 2 ;;
esac
"""
#: A configuration as `config show` prints it: it must not reach the hub's public log.
SHOWN = '{"aws": {"account_id": "222222222222"}, "context": {"name_root": "jaws"}}'


def _printed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> str:
    """What the CLI prints for the fixture's configuration as a hub's: what the candidate's
    image prints in the job."""
    raw = fixture_config()
    raw["platform"]["repositories"].append(dict(HUB_REPOSITORY))
    raw["platform"]["hub"] = dict(HUB)
    config = tmp_path / "hub-config.yaml"
    config.write_text(yaml.safe_dump(raw, sort_keys=False))
    monkeypatch.chdir(tmp_path)  # the CLI writes its .jaws/ into the working directory
    result = CliRunner().invoke(cli.app, ["--config", str(config), *args])
    assert result.exit_code == 0, result.output
    return result.stdout


def _candidate_step(
    tmp_path: Path, step_id: str, **env: str
) -> tuple[subprocess.CompletedProcess[str], str, list[str]]:
    """Run the candidate job's step `step_id` in a hub's workspace with a stand-in docker;
    the result, GITHUB_OUTPUT and the docker calls."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    log = tmp_path / "docker.log"
    log.write_text("")
    result, output = run_step(
        CI,
        "candidate",
        step_id,
        cwd=workspace,
        env={
            "IMAGE_ID": IMAGE_ID,
            "GITHUB_WORKSPACE": str(workspace),
            "GITHUB_REPOSITORY": "Example-Hub/platform",
            "RUNNER_TEMP": str(tmp_path / "temp"),
            "FAKE_LOG": str(log),
            "FAKE_SHOWN": SHOWN,
            **env,
        },
        fakes={"docker": FAKE_DOCKER},
    )
    return result, output, log.read_text().splitlines()


def test_the_candidate_is_built_once_and_passed_to_every_plan(tmp_path: Path) -> None:
    base, build = _one("candidate", BASE), _one("candidate", BUILD)
    assert base["id"] == "base" and build["id"] == "build"
    assert _position("candidate", base) < _position("candidate", build)
    assert build["with"] == {
        "load": "true",
        "push": "false",
        "revision": "${{ github.event.pull_request.head.sha }}",
        "base-name": "${{ steps.base.outputs.base-name }}",
        "base-tag": "${{ steps.base.outputs.base-tag }}",
        "base-digest": "${{ steps.base.outputs.base-digest }}",
    }
    assert job(CI, "candidate")["outputs"]["image-id"] == "${{ steps.build.outputs.image-id }}"
    builders = [name for name in _workflow()["jobs"] if _using(name, BUILD)]
    assert builders == ["candidate"], "one build per run"

    # The build the plans load: `docker save` of the image the build reports, uploaded as
    # this run's artifact, kept a day.
    save = _by_id("candidate", "save")
    assert save["env"] == {"IMAGE_ID": "${{ steps.build.outputs.image-id }}"}
    result, _, calls = _candidate_step(tmp_path, "save")
    assert result.returncode == 0, result.stdout + result.stderr
    tarball = tmp_path / "temp" / "platform-image" / "platform-image.tar"
    assert calls == [f"docker save --output {tarball} {IMAGE_ID}"]
    assert tarball.parent.is_dir(), "the save has a directory to write to"
    upload = _one("candidate", UPLOAD)
    assert _position("candidate", save) < _position("candidate", upload)
    assert upload["with"]["name"] == "platform-image"
    assert upload["with"]["path"] == "${{ runner.temp }}/platform-image/platform-image.tar"
    assert upload["with"]["retention-days"] == 1
    assert upload["with"]["overwrite"] is True, "a re-run's candidate replaces the first's"

    for name in PLAN_JOBS:
        needs = job(CI, name)["needs"]
        assert "candidate" in ([needs] if isinstance(needs, str) else needs), name
        image = _one(name, IMAGE)
        assert image["id"] == "image", name
        assert image["with"] == {"artifact": "platform-image", "image-id": CANDIDATE_ID}, name
        runs = _using(name, JAWS)
        assert len(runs) == 1, name
        assert _position(name, image) < _position(name, runs[0]), name
        given = runs[0]["with"]
        assert given["image"] == "${{ steps.image.outputs.image-id }}", name
        assert given["platform-commit"] == "${{ steps.image.outputs.platform-commit }}", name
        assert given["platform-source"] == "${{ steps.image.outputs.platform-source }}", name
        assert "role-arn" not in given, f"{name}: the job assumed its role already"


def test_no_pull_request_job_can_push_or_move_current() -> None:
    text = (WORKFLOWS / CI).read_text()
    for spelled in (
        "amazon-ecr-login",
        "put-image",
        "docker push",
        "push: true",
        'push: "true"',
        "ci-apply",
    ):
        assert spelled not in text, spelled
    jobs = _workflow()["jobs"]
    assert jobs["candidate"]["permissions"] == {"contents": "read"}, "no AWS for the build"
    for name, spec in jobs.items():
        assert "environment" not in spec, f"{name}: a pull request never enters an environment"


def test_the_hub_is_checked_inside_its_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = [s.get("id") for s in _steps("candidate")]
    for step_id in ("validate", "check", "env", "projects", "save"):
        assert _by_id("candidate", step_id)["env"] == {
            "IMAGE_ID": "${{ steps.build.outputs.image-id }}"
        }, step_id
        assert ids.index("build") < ids.index(step_id), step_id
    env_file = tmp_path / "env.txt"
    env_file.write_text(
        _printed(
            tmp_path,
            monkeypatch,
            "config",
            "env",
            "--monitoring",
            "--databricks",
            "--brand",
            "--platform",
        )
    )
    projects_file = tmp_path / "projects.json"
    projects_file.write_text(
        _printed(
            tmp_path, monkeypatch, "config", "projects", "site", "bot", "research", "databricks"
        )
    )
    workspace = tmp_path / "workspace"
    ran: dict[str, tuple[subprocess.CompletedProcess[str], str, list[str]]] = {}
    for step_id in ("validate", "check", "env", "projects"):
        result, output, calls = _candidate_step(
            tmp_path, step_id, FAKE_ENV=str(env_file), FAKE_PROJECTS=str(projects_file)
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(calls) == 1, calls
        assert calls[0].startswith("docker run --rm --network none "), f"{step_id} is offline"
        ran[step_id] = (result, output, calls[0].split())

    # `config show` is a validation only: the hub's logs are public.
    result, output, args = ran["validate"]
    assert args[args.index(IMAGE_ID) + 1 :] == ["config", "show"]
    assert "config show > /dev/null" in _by_id("candidate", "validate")["run"]
    assert SHOWN not in result.stdout + result.stderr
    assert output == ""

    # The checkout is read-only, and not at /work, where the CLI writes its .jaws/.
    _, output, args = ran["check"]
    root = args[args.index("--root") + 1]
    assert root != "/work"
    mounts = [args[i + 1] for i, arg in enumerate(args) if arg == "--volume"]
    assert mounts == [f"{workspace}:{root}:ro"]
    assert args[args.index(IMAGE_ID) + 1 :] == ["platform", "check", "--root", root]
    assert "GITHUB_REPOSITORY" in [args[i + 1] for i, arg in enumerate(args) if arg == "--env"]
    assert output == ""

    # The identity and the gates, from the candidate's own configuration.
    _, output, args = ran["env"]
    assert args[args.index(IMAGE_ID) + 1 :] == [
        "config",
        "env",
        "--monitoring",
        "--databricks",
        "--brand",
        "--platform",
    ]
    written = dict(line.split("=", 1) for line in output.splitlines())
    assert written["account_id"] == "222222222222"
    assert written["name_root"] == "jaws"
    assert written["platform_image"] == "jaws-platform"
    outputs = job(CI, "candidate")["outputs"]
    for key in ("account_id", "name_root", "monitoring", "databricks", "platform_image"):
        assert key in written, key
        assert outputs[key] == "${{ steps.env.outputs." + key + " }}"

    _, output, args = ran["projects"]
    assert args[args.index(IMAGE_ID) + 1 :] == [
        "config",
        "projects",
        "site",
        "bot",
        "research",
        "databricks",
    ]
    (line,) = output.splitlines()
    assert line.startswith("projects=")
    listed = json.loads(line.removeprefix("projects="))
    assert {entry["type"] for entry in listed} == {"site", "bot", "research", "databricks"}
    assert all(set(entry) == {"project", "repository", "type"} for entry in listed)
    assert outputs["projects"] == "${{ steps.projects.outputs.projects }}"


# -- the plans ------------------------------------------------------------------------

NAMES = {
    "candidate": "Platform check",
    "foundation": "Terraform plan",
    "monitoring": "Monitoring plan",
    "data-access": "Data access plan",
    "projects": (
        "${{ matrix.type == 'databricks' && 'Databricks' || matrix.type == 'site' && 'Site' "
        "|| 'Bot' }} plan (${{ matrix.project }})"
    ),
}
COMMANDS = {
    "foundation": "platform plan foundation",
    "monitoring": "platform plan monitoring",
    "data-access": "platform plan data-access --base-registry .base/datasets",
    "projects": "--file .consumer/jaws.yaml plan",
}
HEADERS = {
    "foundation": "terraform-plan",
    "monitoring": "monitoring-plan",
    "data-access": "data-access-plan",
    "projects": (
        "${{ matrix.type == 'databricks' && 'databricks' || matrix.type == 'site' && 'site' "
        "|| 'bot' }}-plan-${{ matrix.project }}"
    ),
}


def test_every_platform_stack_and_project_is_planned() -> None:
    jobs = _workflow()["jobs"]
    assert {name: spec["name"] for name, spec in jobs.items()} == NAMES
    for name, command in COMMANDS.items():
        assert _one(name, JAWS)["with"]["command"] == command, name
        comment = _one(name, COMMENT)
        assert comment["with"]["header"] == HEADERS[name], name
        assert comment["with"]["path"] == ".jaws/plan-comment.md", name

    projects = jobs["projects"]
    assert projects["if"] == "needs.candidate.outputs.projects != '[]'"
    assert projects["strategy"] == {
        "fail-fast": False,
        "matrix": {"include": "${{ fromJSON(needs.candidate.outputs.projects) }}"},
    }
    monitoring = " ".join(str(jobs["monitoring"]["if"]).split())
    assert "needs.candidate.outputs.monitoring == 'configured'" in monitoring
    assert "github.event.pull_request.head.repo.full_name == github.repository" in monitoring
    assert jobs["data-access"]["if"] == "github.event.pull_request.user.login != 'dependabot[bot]'"
    assert "if" not in jobs["foundation"]

    # Data access renders with the base branch's registry, so dropping a dataset that a
    # handshake still names fails.
    (registry,) = [s for s in _steps("data-access") if s.get("with", {}).get("path") == ".base"]
    assert str(registry["uses"]).startswith("actions/checkout@")
    assert registry["with"] == {
        "ref": "${{ github.event.pull_request.base.sha }}",
        "path": ".base",
        "sparse-checkout": "datasets",
    }
    assert _position("data-access", registry) < _position("data-access", _one("data-access", JAWS))


def test_each_plan_assumes_its_own_plan_role() -> None:
    for name, project in PLAN_ROLES.items():
        role = _one(name, ROLE)
        assert role["id"] == "role", name
        assert role["with"] == {
            "platform-image": "${{ needs.candidate.outputs.platform_image }}",
            "account-id": "${{ needs.candidate.outputs.account_id }}",
            "name-root": "${{ needs.candidate.outputs.name_root }}",
            "role": "plan",
            "project": project,
        }, name
        credentials = _one(name, CREDENTIALS)
        assert credentials["with"]["role-to-assume"] == "${{ steps.role.outputs.arn }}", name
        assert credentials["with"]["aws-region"] == "us-east-1", name
        order = [_position(name, s) for s in (role, credentials, _one(name, IMAGE))]
        assert order == sorted(order), f"{name}: the role, its credentials, then the candidate"


def test_monitoring_is_planned_once_its_role_exists(tmp_path: Path) -> None:
    """Until the release that creates the stack's roles, the plan is skipped with a notice,
    as ci.yml's is."""
    assume = _one("monitoring", CREDENTIALS)
    assert assume["id"] == "assume"
    assert assume["continue-on-error"] is True
    skip = _by_id("monitoring", "skip")
    assert skip["if"] == "steps.assume.outcome != 'success'"
    assert skip["env"] == {"ROLE": "${{ steps.role.outputs.arn }}"}
    summary = tmp_path / "summary.md"
    summary.write_text("")
    role = "arn:aws:iam::123456789012:role/acme-monitoring-ci-plan"
    result, output = run_step(
        CI,
        "monitoring",
        "skip",
        cwd=tmp_path,
        env={"ROLE": role, "GITHUB_STEP_SUMMARY": str(summary)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith(f"::notice::could not assume {role}")
    assert "## Monitoring plan skipped" in summary.read_text()
    assert output == ""
    for step in (_one("monitoring", IMAGE), _one("monitoring", JAWS)):
        assert step["if"] == "steps.assume.outcome == 'success'"
    assert _position("monitoring", assume) < _position("monitoring", skip)


@pytest.mark.parametrize(
    ("kind", "databricks", "plan"),
    [
        ("databricks", "disabled", "false"),
        ("databricks", "awaiting-host", "true"),
        ("databricks", "ready", "true"),
        ("site", "disabled", "true"),
        ("bot", "disabled", "true"),
        ("research", "disabled", "true"),
    ],
)
def test_a_project_plan_waits_for_databricks_its_file_and_its_role(
    tmp_path: Path, kind: str, databricks: str, plan: str
) -> None:
    gate = _by_id("projects", "gate")
    assert gate["env"] == {
        "TYPE": "${{ matrix.type }}",
        "DATABRICKS": "${{ needs.candidate.outputs.databricks }}",
        "PROJECT": "${{ matrix.project }}",
    }
    result, output = run_step(
        CI,
        "projects",
        "gate",
        cwd=tmp_path,
        env={"TYPE": kind, "DATABRICKS": databricks, "PROJECT": "databricks-poc"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == [f"plan={plan}"]
    notices = [line for line in result.stdout.splitlines() if line.startswith("::notice::")]
    assert len(notices) == (1 if plan == "false" else 0), result.stdout

    file = _one("projects", PROJECT_FILE)
    assert file["id"] == "file"
    assert file["if"] == "steps.gate.outputs.plan == 'true'"
    assert file["with"] == {
        "project": "${{ matrix.project }}",
        "repository": "${{ matrix.repository }}",
        "on-mismatch": "skip",
    }
    role, assume = _one("projects", ROLE), _one("projects", CREDENTIALS)
    assert role["if"] == "steps.file.outputs.matches == 'true'"
    assert assume["if"] == "steps.file.outputs.matches == 'true'"
    assert assume["id"] == "assume"
    assert assume["continue-on-error"] is True, "the role does not exist until the release"
    (skip,) = [s for s in _steps("projects") if "::warning::" in str(s.get("run", ""))]
    assert skip["if"] == "steps.file.outputs.matches == 'true' && steps.assume.outcome != 'success'"
    image, run = _one("projects", IMAGE), _one("projects", JAWS)
    assert image["if"] == run["if"] == "steps.assume.outcome == 'success'"
    order = [_position("projects", s) for s in (gate, file, role, assume, skip, image, run)]
    assert order == sorted(order)


def test_the_project_file_reads_carry_a_token() -> None:
    for name in ("data-access", "projects"):
        assert _one(name, JAWS)["with"]["github-token"] == "${{ github.token }}", name


def test_the_comments_come_from_the_platform_s_app_or_github_actions() -> None:
    call = _workflow()[True]["workflow_call"]
    assert call["inputs"] == {
        "app-client-id": {
            "description": call["inputs"]["app-client-id"]["description"],
            "required": False,
            "type": "string",
            "default": "",
        }
    }
    assert call["secrets"]["app-private-key"]["required"] is False
    posting = [name for name in _workflow()["jobs"] if _using(name, COMMENT)]
    assert posting == PLAN_JOBS
    for name in posting:
        token = _one(name, APP_TOKEN)
        assert token["id"] == "app-token", name
        assert token["continue-on-error"] is True, f"{name}: falls back to github-actions"
        assert "inputs.app-client-id != ''" in token["if"], name
        assert token["with"] == {
            "client-id": "${{ inputs.app-client-id }}",
            "private-key": "${{ secrets.app-private-key }}",
        }, name
        comment = _one(name, COMMENT)
        assert comment["with"]["GITHUB_TOKEN"] == (
            "${{ steps.app-token.outputs.token || github.token }}"
        ), name
        assert _position(name, token) < _position(name, comment), name


def test_each_job_holds_only_the_grants_it_needs() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {}
    assert workflow["jobs"]["candidate"]["permissions"] == {"contents": "read"}
    for name in PLAN_JOBS:
        assert workflow["jobs"][name]["permissions"] == {
            "contents": "read",
            "id-token": "write",
            "pull-requests": "write",
        }, name


def test_every_job_runs_the_tool_from_its_own_commit() -> None:
    """`tests/test_tool_checkout.py` checks each checkout and its verify step; here, that
    every job has them before it uses any of the tool's actions."""
    for name in _workflow()["jobs"]:
        steps = _steps(name)
        tool = [
            i
            for i, s in enumerate(steps)
            if str(s.get("uses", "")).startswith("actions/checkout@")
            and s.get("with", {}).get("repository") == "Jaws-Platform/jaws"
        ]
        assert len(tool) == 1, name
        assert steps[tool[0]]["with"] == {
            "repository": "Jaws-Platform/jaws",
            "ref": "${{ job.workflow_sha }}",
            "path": ".jaws-tool",
        }, name
        assert steps[tool[0] + 1]["name"] == "Check jaws is at this workflow's own commit"
        local = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("./")]
        assert local and min(local) > tool[0] + 1, name


def test_every_plan_keeps_its_run_log() -> None:
    names = []
    for name in PLAN_JOBS:
        upload = _one(name, UPLOAD)
        assert upload["if"] == "always()", name
        assert upload["with"]["path"] == ".jaws/", name
        assert upload["with"]["include-hidden-files"] is True, name
        names.append(upload["with"]["name"])
    assert len(set(names)) == len(names)
    assert "${{ matrix.project }}" in names[PLAN_JOBS.index("projects")], "one per project"


# -- platform-base --------------------------------------------------------------------


def _base(tmp_path: Path, dockerfile: str | None) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run platform-base's `base` beside a Dockerfile holding `dockerfile`, or none."""
    if dockerfile is not None:
        (tmp_path / "Dockerfile").write_text(dockerfile)
    return run_action_step("platform-base", "base", cwd=tmp_path, env={})


#: Rule 1's message (`jaws platform check`), before the FROM lines it quotes.
RULE_1 = (
    "::error::FROM must pin the Jaws image by tag and digest "
    "(FROM public.ecr.aws/<alias>/jaws:vX.Y.Z@sha256:…), not "
)


@pytest.mark.parametrize(
    ("dockerfile", "quoted"),
    [
        pytest.param(HUB_DOCKERFILE, None, id="pinned"),
        pytest.param(f"FROM {BASE_NAME}:v0.81.0\n", f"'FROM {BASE_NAME}:v0.81.0'", id="no-digest"),
        pytest.param(
            f"{PINNED}\nCOPY config/ /etc/jaws/config/\n{PINNED}\n",
            f"'{PINNED}\\n{PINNED}'",
            id="two-froms",
        ),
        pytest.param(f"FROM {BASE_NAME}:latest\n", f"'FROM {BASE_NAME}:latest'", id="latest"),
    ],
)
def test_the_base_must_be_pinned_by_tag_and_digest(
    tmp_path: Path, dockerfile: str, quoted: str | None
) -> None:
    action = _action("platform-base")
    assert {name: spec["value"] for name, spec in action["outputs"].items()} == {
        "base-name": "${{ steps.base.outputs.base-name }}",
        "base-tag": "${{ steps.base.outputs.base-tag }}",
        "base-digest": "${{ steps.base.outputs.base-digest }}",
    }
    result, output = _base(tmp_path, dockerfile)
    if quoted is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert output.splitlines() == [
            f"base-name={BASE_NAME}",
            "base-tag=v0.81.0",
            f"base-digest={BASE_DIGEST}",
        ]
    else:
        assert result.returncode != 0
        assert result.stdout.splitlines() == [RULE_1 + quoted]
        assert output == ""


@pytest.mark.parametrize(
    "dockerfile",
    [
        pytest.param(HUB_DOCKERFILE, id="pinned"),
        pytest.param(HUB_DOCKERFILE.replace("\n", "\r\n"), id="crlf"),
        pytest.param(PINNED, id="no-final-newline"),
        pytest.param(f"FROM {BASE_NAME}:v0.81.0\n", id="no-digest"),
        pytest.param(f"{PINNED}\n{PINNED}\n", id="two-froms"),
        pytest.param(f"FROM {BASE_NAME}:latest\n", id="latest"),
        pytest.param(f"FROM {BASE_NAME}@{BASE_DIGEST}\n", id="no-tag"),
        pytest.param(f"FROM {BASE_NAME}:v0.81@{BASE_DIGEST}\n", id="not-a-release"),
        pytest.param(PINNED.replace("FROM", "from") + "\n", id="lowercase"),
        pytest.param("COPY config/ /etc/jaws/config/\n", id="no-from"),
        pytest.param(None, id="no-dockerfile"),
    ],
)
def test_the_base_is_read_as_the_check_reads_it(
    tmp_path: Path, settings: Settings, dockerfile: str | None
) -> None:
    """The step holds the check's FROM_PATTERN verbatim, and takes what the check takes:
    each Dockerfile the check refuses, the step refuses with the same message."""
    assert FROM_PATTERN in action_step("platform-base", "base")["run"]
    result, output = _base(tmp_path, dockerfile)
    refused = [
        p.message for p in check_hub(tmp_path, settings, "0.81.0", None) if p.path == "Dockerfile"
    ]
    if refused:
        assert result.returncode != 0
        assert result.stdout.splitlines() == [f"::error::{refused[0]}"]
        assert output == ""
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"base-digest={BASE_DIGEST}" in output.splitlines()


#: The manifest ECR Public is asked for: the pinned digest in the base's repository.
MANIFEST = f"https://public.ecr.aws/v2/example-alias/jaws/manifests/{BASE_DIGEST}"
PRUNED = (
    f"::error::the Dockerfile's Jaws base {BASE_NAME}:v0.81.0@{BASE_DIGEST} is no longer in "
    "ECR Public, which keeps only the newest versions until v1: merge the open upgrade PR, "
    "or move the FROM line to a recent Jaws release"
)


def _present(
    tmp_path: Path, code: str, name: str = BASE_NAME
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run platform-base's `present` for the pinned base, with a stand-in curl whose
    manifest request answers `code`; the result and the curl calls."""
    log = tmp_path / "curl.log"
    log.write_text("")
    result, _ = run_action_step(
        "platform-base",
        "present",
        cwd=tmp_path,
        env={
            "NAME": name,
            "TAG": "v0.81.0",
            "DIGEST": BASE_DIGEST,
            "MANIFEST_TYPES": action_step("platform-base", "present")["env"]["MANIFEST_TYPES"],
            "FAKE_LOG": str(log),
            "FAKE_HTTP_CODE": code,
        },
        fakes={"curl": FAKE_CURL},
    )
    return result, log.read_text().splitlines()


@needs_yq
def test_a_pruned_base_fails_naming_the_fix(tmp_path: Path) -> None:
    result, _ = _present(tmp_path, "404")
    assert result.returncode != 0
    assert result.stdout.splitlines() == [PRUNED]
    for named in ("v0.81.0", BASE_DIGEST, "merge the open upgrade PR"):
        assert named in PRUNED


@needs_yq
def test_a_published_base_passes(tmp_path: Path) -> None:
    present = action_step("platform-base", "present")
    decide = next(
        s
        for s in job("release-please.yml", "public-image-check")["steps"]
        if s.get("id") == "decide"
    )
    assert present["env"] == {
        "NAME": "${{ steps.base.outputs.base-name }}",
        "TAG": "${{ steps.base.outputs.base-tag }}",
        "DIGEST": "${{ steps.base.outputs.base-digest }}",
        "MANIFEST_TYPES": decide["env"]["MANIFEST_TYPES"],
    }, "plan 04's Accept types"
    result, calls = _present(tmp_path, "200")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::error::" not in result.stdout
    token, head = calls
    assert (
        "https://public.ecr.aws/token/?service=public.ecr.aws&scope=repository:example-alias/jaws:pull"
    ) in token
    assert " -I " in f" {head} " and head.endswith(f" {MANIFEST}"), "a HEAD of the pinned digest"
    assert "Authorization: Bearer anonymous" in head
    assert f"Accept: {present['env']['MANIFEST_TYPES']}" in head


@needs_yq
def test_a_registry_error_names_the_status(tmp_path: Path) -> None:
    result, _ = _present(tmp_path, "503")
    assert result.returncode != 0
    assert result.stdout.splitlines() == [
        "::error::could not tell whether the Jaws base is still published "
        "(HTTP 503 from public.ecr.aws)"
    ]


def test_the_upgrade_can_skip_asking_whether_the_base_is_published() -> None:
    """The upgrade (Task 14) reads the base too, then replaces the pin, pruned or not."""
    action = _action("platform-base")
    assert [s["id"] for s in action["runs"]["steps"]] == ["base", "present"]
    assert action["inputs"]["require-published"]["default"] == "true"
    assert action_step("platform-base", "base").get("if") is None
    assert action_step("platform-base", "present")["if"] == "inputs.require-published != 'false'"


def test_a_base_outside_ecr_public_is_not_asked_for(tmp_path: Path) -> None:
    result, calls = _present(tmp_path, "404", name="registry.example.com/mirror/jaws")
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == []
    (notice,) = result.stdout.splitlines()
    assert notice.startswith("::notice::") and "registry.example.com/mirror/jaws" in notice


# -- platform-build -------------------------------------------------------------------

LABELS = {
    "org.opencontainers.image.revision=${{ inputs.revision }}",
    "org.opencontainers.image.source=${{ github.server_url }}/${{ github.repository }}",
    "org.opencontainers.image.base.name=${{ inputs.base-name }}:${{ inputs.base-tag }}",
    "org.opencontainers.image.base.digest=${{ inputs.base-digest }}",
}


def test_the_build_records_its_jaws_release_and_hub_commit() -> None:
    action = _action("platform-build")
    inputs = action["inputs"]
    assert set(inputs) == {
        "load",
        "push",
        "tags",
        "revision",
        "base-name",
        "base-tag",
        "base-digest",
    }
    assert inputs["tags"]["default"] == ""
    steps = action["runs"]["steps"]
    assert str(steps[0]["uses"]).startswith("docker/setup-buildx-action@")
    assert steps[1]["id"] == "build"
    assert str(steps[1]["uses"]).startswith("docker/build-push-action@")
    given = dict(steps[1]["with"])
    assert set(str(given.pop("labels")).splitlines()) == LABELS
    assert given == {
        "context": ".",
        "platforms": "linux/amd64",
        "provenance": False,
        "load": "${{ inputs.load }}",
        "push": "${{ inputs.push }}",
        "tags": "${{ inputs.tags }}",
    }
    assert {name: spec["value"] for name, spec in action["outputs"].items()} == {
        "image-id": "${{ steps.loaded.outputs.image-id }}",
        "digest": "${{ inputs.push == 'true' && steps.build.outputs.digest || '' }}",
    }


#: Stands in for docker: `image inspect` answers the IDs in FAKE_KNOWN, as the runner's image
#: store does, and nothing else.
FAKE_INSPECT = """#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
if [[ "$1 $2 $3 $4" != "image inspect --format {{.Id}}" ]]; then
  echo "unexpected: docker $*" >&2
  exit 2
fi
for known in $FAKE_KNOWN; do
  if [[ "$5" == "$known" ]]; then echo "$known"; exit 0; fi
done
echo "Error: No such image: $5" >&2
exit 1
"""


def _loaded(tmp_path: Path, known: str) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run platform-build's `loaded` after a build buildx reports by both digests, on a
    runner whose image store knows `known`."""
    log = tmp_path / "docker.log"
    log.write_text("")
    return run_action_step(
        "platform-build",
        "loaded",
        cwd=tmp_path,
        env={
            "CONFIG_DIGEST": IMAGE_ID,
            "DIGEST": MANIFEST_DIGEST,
            "FAKE_KNOWN": known,
            "FAKE_LOG": str(log),
        },
        fakes={"docker": FAKE_INSPECT},
    )


@pytest.mark.parametrize(
    "store_id", [IMAGE_ID, MANIFEST_DIGEST], ids=["classic-store", "containerd-store"]
)
def test_the_build_s_image_id_is_the_one_the_runner_reports(tmp_path: Path, store_id: str) -> None:
    """Docker's classic image store names a build by its config digest, buildx's imageid,
    and the containerd store by its manifest digest: platform-image checks a candidate
    against what the runner reports."""
    loaded = action_step("platform-build", "loaded")
    assert loaded["if"] == "inputs.load == 'true'"
    assert loaded["env"] == {
        "CONFIG_DIGEST": "${{ steps.build.outputs.imageid }}",
        "DIGEST": "${{ steps.build.outputs.digest }}",
    }
    result, output = _loaded(tmp_path, store_id)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == [f"image-id={store_id}"]


def test_a_build_the_runner_does_not_hold_stops_the_job(tmp_path: Path) -> None:
    result, output = _loaded(tmp_path, "")
    assert result.returncode != 0
    assert result.stdout.startswith("::error::"), result.stdout
    assert output == ""


# -- platform-project-file ------------------------------------------------------------


def test_the_project_file_is_checked_out_as_bot_apply_does() -> None:
    action = _action("platform-project-file")
    inputs = action["inputs"]
    assert {name for name, spec in inputs.items() if spec.get("required")} == {
        "project",
        "repository",
        "on-mismatch",
    }
    assert inputs["ref"]["default"] == ""
    assert action["outputs"]["matches"]["value"] == "${{ steps.names.outputs.matches }}"
    checkout, names = action["runs"]["steps"]
    assert names["id"] == "names"
    bot_apply = next(
        s
        for s in job("bot-apply.yml", "apply")["steps"]
        if s.get("with", {}).get("path") == ".consumer"
    )
    assert checkout["uses"] == bot_apply["uses"]
    assert checkout["with"] == {
        **bot_apply["with"],
        "repository": "${{ inputs.repository }}",
        "ref": "${{ inputs.ref }}",
    }
    assert names["env"] == {
        "PROJECT": "${{ inputs.project }}",
        "ON_MISMATCH": "${{ inputs.on-mismatch }}",
    }


def _names(
    tmp_path: Path, named: str, on_mismatch: str
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    """Run platform-project-file's `names` for braveheart, with a .consumer/jaws.yaml that
    names `named`; the result, GITHUB_OUTPUT and the step summary."""
    consumer = tmp_path / ".consumer"
    consumer.mkdir()
    (consumer / "jaws.yaml").write_text(f"version: 1\nproject: {named}\n")
    summary = tmp_path / "summary.md"
    summary.write_text("")
    result, output = run_action_step(
        "platform-project-file",
        "names",
        cwd=tmp_path,
        env={
            "PROJECT": "braveheart",
            "ON_MISMATCH": on_mismatch,
            "GITHUB_STEP_SUMMARY": str(summary),
        },
    )
    return result, output, summary.read_text()


@needs_yq
@pytest.mark.parametrize("on_mismatch", ["skip", "refuse"])
def test_a_project_file_that_names_another_project_is_skipped_or_refused(
    tmp_path: Path, on_mismatch: str
) -> None:
    result, output, summary = _names(tmp_path, "other", on_mismatch)
    if on_mismatch == "skip":
        assert result.returncode == 0, result.stdout + result.stderr
        assert output.splitlines() == ["matches=false"]
        assert result.stdout.splitlines() == [
            "::warning::the project file names 'other', not 'braveheart'; "
            "the plan for braveheart is skipped"
        ]
        assert "`other`" in summary and "`braveheart`" in summary
    else:
        assert result.returncode == 1
        assert result.stdout.splitlines() == [
            "::error::the project file names 'other', not 'braveheart'; "
            "pass consumer-ref for a ref whose file names braveheart"
        ]
        assert output == ""


@needs_yq
@pytest.mark.parametrize("on_mismatch", ["skip", "refuse"])
def test_a_project_file_that_names_the_project_matches(tmp_path: Path, on_mismatch: str) -> None:
    result, output, summary = _names(tmp_path, "braveheart", on_mismatch)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == ["matches=true"]
    assert result.stdout == "" and summary == ""


def test_a_rule_other_than_skip_or_refuse_is_refused(tmp_path: Path) -> None:
    result, output, _ = _names(tmp_path, "braveheart", "warn")
    assert result.returncode != 0
    assert result.stdout.startswith("::error::on-mismatch "), result.stdout
    assert output == ""
