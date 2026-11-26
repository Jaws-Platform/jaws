"""`platform-release.yml` and `platform-rollback.yml`: a hub's release and its rollback, and
`platform-move`, which moves `current` and `live` for both.

A release is gated, as `jaws`'s is: merging the hub's Release Please PR releases. The `image`
job builds the release commit and pushes it as `sha-<commit>`, a tag that never moves, and a
re-run finds its own build. The foundation, then monitoring, are applied with that build, by
its digest, never with whatever `current` names. `current` moves once the foundation's apply
succeeds, without waiting for monitoring's (ruling 7), and `live` follows, moved by the hub's
mover App, never the release App (ruling 8). A re-run of an older release's job, once a newer
release is live, stops before it changes anything. A rollback moves both to a kept build,
`live` by force, and applies nothing (ruling 9).

`platform-move`'s scripts, the steps that look a build up, and the checks on the `image`
job's outputs run here as Actions runs them, with stand-ins for `aws`, `gh`, `docker` and
`git`.
"""

from __future__ import annotations

import itertools
import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import yaml

from tests.test_databricks_workflows import needs_yq
from tests.test_github import HUB_COMMIT
from tests.test_platform_actions import CONFIG_DIGEST, DIGEST, FOUND, NOT_FOUND, REPOSITORY
from tests.test_platform_ci import _printed
from tests.workflow_steps import ACTIONS, WORKFLOWS, action_step, job, run_action_step, run_step

RELEASE = "platform-release.yml"
ROLLBACK = "platform-rollback.yml"
TOOL = "./.jaws-tool/.github/actions"
ROLE = f"{TOOL}/platform-role"
IMAGE = f"{TOOL}/platform-image"
BASE = f"{TOOL}/platform-base"
BUILD = f"{TOOL}/platform-build"
MOVE = f"{TOOL}/platform-move"
JAWS = f"{TOOL}/jaws"
CREDENTIALS = "aws-actions/configure-aws-credentials"
ECR_LOGIN = "aws-actions/amazon-ecr-login"
APP_TOKEN = "actions/create-github-app-token"

#: The jobs of a release that change something, in the order they run.
CHANGING = ["image", "apply", "current", "live", "monitoring-apply"]
#: monitoring-apply's condition: after the moves, whatever they did, once the foundation's
#: apply has succeeded and the build's configuration has a monitoring section.
AFTER_THE_MOVES = (
    "${{ !cancelled() && needs.apply.result == 'success' && "
    "needs.image.outputs.monitoring == 'configured' }}"
)
RELEASED = "needs.release-please.outputs.release_created == 'true'"
#: The build and the release commit the later jobs of a release read from the image job.
BUILD_DIGEST = "${{ needs.image.outputs.digest }}"
BUILD_COMMIT = "${{ needs.image.outputs.commit }}"
#: The platform's identity, as each job passes it to platform-role.
IDENTITY = {
    "platform-image": "${{ inputs.platform-image }}",
    "account-id": "${{ inputs.account-id }}",
    "name-root": "${{ inputs.name-root }}",
}
#: The mover App's token is minted from exactly its client ID and its key.
MINTED = {
    "client-id": "${{ inputs.live-app-client-id }}",
    "private-key": "${{ secrets.live-app-private-key }}",
}
LIVE_TOKEN = "${{ steps.live-token.outputs.token }}"
GROUP = {"group": "platform-release", "cancel-in-progress": False}

COMMIT = HUB_COMMIT
HUB_NAME = "Example-Hub/platform"
MOVER_TOKEN = "the-mover-app-s-token"
JOB_TOKEN = "the-job-s-own-token"
#: The build's manifest as batch-get-image returns it, and its media type.
MANIFEST: str = FOUND["images"][0]["imageManifest"]
MEDIA_TYPE: str = FOUND["images"][0]["imageManifestMediaType"]
#: batch-get-image's answer for the release's build, looked up by its tag.
KEPT: Mapping[str, Any] = {
    **FOUND,
    "images": [
        {**FOUND["images"][0], "imageId": {"imageDigest": DIGEST, "imageTag": f"sha-{COMMIT}"}}
    ],
}

#: Stands in for aws: logs each call. `ecr batch-get-image` answers with the file FAKE_IMAGES.
#: `ecr put-image` writes the manifest it is given to FAKE_MANIFEST, then fails as the CLI does
#: with the exception FAKE_PUT_ERROR names, when that is set.
FAKE_AWS = """#!/usr/bin/env bash
echo "aws $*" >> "$FAKE_LOG"
case "$1 $2" in
  "ecr batch-get-image") cat "$FAKE_IMAGES" ;;
  "ecr put-image")
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == --image-manifest ]]; then printf '%s' "$2" > "$FAKE_MANIFEST"; fi
      shift
    done
    if [[ -n "${FAKE_PUT_ERROR:-}" ]]; then
      echo >&2
      echo "An error occurred ($FAKE_PUT_ERROR) when calling the PutImage operation: refused" >&2
      exit 254
    fi
    echo '{"image": {"imageId": {"imageTag": "current"}}}'
    ;;
  *) echo "unexpected: aws $*" >&2; exit 2 ;;
esac
"""
#: Stands in for gh: logs each call, and answers only the token FAKE_TOKEN, as GitHub answers
#: only a valid one. A PATCH fails with FAKE_PATCH_ERROR and a POST with FAKE_POST_ERROR when
#: set, as gh fails: GitHub's answer on stdout, its message on stderr, exit 1. A compare, asked
#: for its answer's `--jq .status`, prints FAKE_STATUS, or fails with FAKE_COMPARE_ERROR, as
#: HTTP FAKE_COMPARE_CODE (404 when unset).
FAKE_GH = """#!/usr/bin/env bash
echo "gh $*" >> "$FAKE_LOG"
fail() {
  echo "{\\"message\\": \\"$1\\", \\"status\\": \\"$2\\"}"
  echo "gh: $1 (HTTP $2)" >&2
  exit 1
}
[[ "${GH_TOKEN:-}" == "$FAKE_TOKEN" ]] || fail "Bad credentials" 401
case "$*" in
  "api --method PATCH "*)
    [[ -z "${FAKE_PATCH_ERROR:-}" ]] || fail "$FAKE_PATCH_ERROR" 422
    echo '{"ref": "refs/heads/live"}'
    ;;
  "api --method POST "*)
    [[ -z "${FAKE_POST_ERROR:-}" ]] || fail "$FAKE_POST_ERROR" 422
    echo '{"ref": "refs/heads/live"}'
    ;;
  "api repos/"*"/compare/"*" --jq .status")
    [[ -z "${FAKE_COMPARE_ERROR:-}" ]] || fail "$FAKE_COMPARE_ERROR" "${FAKE_COMPARE_CODE:-404}"
    echo "$FAKE_STATUS"
    ;;
  *) echo "unexpected: gh $*" >&2; exit 2 ;;
esac
"""
#: Stands in for docker: logs each call, and answers `config env` with the file FAKE_ENV.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
case "$*" in
  "run "*" config env "*) cat "$FAKE_ENV" ;;
  *) echo "unexpected: docker $*" >&2; exit 2 ;;
esac
"""
#: Stands in for git: answers `rev-parse HEAD` with FAKE_HEAD, the checked-out tag's commit.
FAKE_GIT = """#!/usr/bin/env bash
echo "git $*" >> "$FAKE_LOG"
case "$*" in
  "rev-parse HEAD") echo "$FAKE_HEAD" ;;
  *) echo "unexpected: git $*" >&2; exit 2 ;;
esac
"""
#: Every command a script here may call, each refusing what it doesn't expect: no real aws,
#: gh, docker or git ever runs.
FAKES = {"aws": FAKE_AWS, "gh": FAKE_GH, "docker": FAKE_DOCKER, "git": FAKE_GIT}

#: platform-move's environment for each move: the release's build, and the mover's token.
CURRENT = {"REPOSITORY": REPOSITORY, "DIGEST": DIGEST, "COMMIT": COMMIT}
LIVE = {"COMMIT": COMMIT, "FORCE": "false", "GH_TOKEN": MOVER_TOKEN}
PATCH = f"gh api --method PATCH repos/{HUB_NAME}/git/refs/heads/live -f sha={COMMIT} -F force="
POST = f"gh api --method POST repos/{HUB_NAME}/git/refs -f ref=refs/heads/live -f sha={COMMIT}"
#: The line `current`'s move adds to the step summary.
MOVED = f"`current` is `{REPOSITORY}@{DIGEST}` (`sha-{COMMIT}`)"


class Ran(NamedTuple):
    """A script's run: its result, GITHUB_OUTPUT, the stand-ins' calls and the step summary."""

    result: subprocess.CompletedProcess[str]
    output: str
    calls: list[str]
    summary: str


def _stand_ins(tmp_path: Path, images: Mapping[str, Any]) -> dict[str, str]:
    """The stand-ins' environment, with an empty log and summary: batch-get-image answers
    `images`, and GitHub takes only the mover App's token."""
    for name in ("calls.log", "summary.md"):
        (tmp_path / name).write_text("")
    answer = tmp_path / "images.json"
    answer.write_text(json.dumps(images))
    return {
        "FAKE_LOG": str(tmp_path / "calls.log"),
        "FAKE_IMAGES": str(answer),
        "FAKE_MANIFEST": str(tmp_path / "manifest.json"),
        "FAKE_TOKEN": MOVER_TOKEN,
        "GITHUB_REPOSITORY": HUB_NAME,
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }


def _ran(tmp_path: Path, result: subprocess.CompletedProcess[str], output: str) -> Ran:
    calls = (tmp_path / "calls.log").read_text().splitlines()
    return Ran(result, output, calls, (tmp_path / "summary.md").read_text())


def _move(tmp_path: Path, step_id: str, images: Mapping[str, Any] = FOUND, /, **env: str) -> Ran:
    """Run platform-move's step `step_id` with the stand-ins; `env` is the step's own."""
    stand_ins = _stand_ins(tmp_path, images)
    result, output = run_action_step(
        "platform-move", step_id, cwd=tmp_path, env={**stand_ins, **env}, fakes=FAKES
    )
    return _ran(tmp_path, result, output)


def _step(
    tmp_path: Path,
    workflow: str,
    name: str,
    step_id: str,
    images: Mapping[str, Any] = FOUND,
    /,
    **env: str,
) -> Ran:
    """Run the workflow's job `name`'s step `step_id` with the stand-ins; `env` is the step's
    own."""
    stand_ins = _stand_ins(tmp_path, images)
    result, output = run_step(
        workflow, name, step_id, cwd=tmp_path, env={**stand_ins, **env}, fakes=FAKES
    )
    return _ran(tmp_path, result, output)


def _workflow(name: str) -> dict[Any, Any]:
    parsed: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text())
    return parsed


def _jobs(workflow: str) -> dict[str, Any]:
    jobs: dict[str, Any] = _workflow(workflow)["jobs"]
    return jobs


def _action(name: str) -> dict[str, Any]:
    parsed: dict[str, Any] = yaml.safe_load((ACTIONS / name / "action.yml").read_text())
    return parsed


def _steps(workflow: str, name: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = job(workflow, name)["steps"]
    return steps


def _using(workflow: str, name: str, action: str) -> list[dict[str, Any]]:
    """The job's steps that use `action`: a local action's path, or a published action's
    `owner/name`, at any version."""
    return [
        s
        for s in _steps(workflow, name)
        if s.get("uses") == action or str(s.get("uses", "")).startswith(f"{action}@")
    ]


def _one(workflow: str, name: str, action: str) -> dict[str, Any]:
    found = _using(workflow, name, action)
    assert len(found) == 1, f"{workflow} {name}: expected one {action} step, found {len(found)}"
    return found[0]


def _by_id(workflow: str, name: str, step_id: str) -> dict[str, Any]:
    (found,) = [s for s in _steps(workflow, name) if s.get("id") == step_id]
    return found


def _position(workflow: str, name: str, step: dict[str, Any]) -> int:
    """Where `step` is among the job's steps."""
    return _steps(workflow, name).index(step)


def _needs(spec: Mapping[str, Any]) -> list[str]:
    needs = spec.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _environment(spec: Mapping[str, Any]) -> str | None:
    environment = spec.get("environment")
    return environment.get("name") if isinstance(environment, dict) else environment


def _conditions(workflow: str, name: str) -> list[str]:
    """The job's `if` and the `if` of every job it needs, recursively, each on one line."""
    spec = job(workflow, name)
    found = [" ".join(str(spec["if"]).split())] if "if" in spec else []
    for need in _needs(spec):
        found += _conditions(workflow, need)
    return found


def _errors(ran: Ran) -> list[str]:
    return [line for line in ran.result.stdout.splitlines() if line.startswith("::error::")]


# -- the release's jobs ---------------------------------------------------------------

NAMES = {
    "release-please": "Release Please",
    "image": "Build the platform image (${{ needs.release-please.outputs.tag_name }})",
    "apply": "Terraform apply (${{ needs.image.outputs.tag }})",
    "monitoring-apply": "Monitoring apply (${{ needs.image.outputs.tag }})",
    "current": "Move current to ${{ needs.image.outputs.tag }}",
    "live": "Move live to ${{ needs.image.outputs.tag }}",
}


def test_nothing_moves_without_a_release() -> None:
    """Each job that changes something runs only after a release: it, or a job it needs,
    holds Release Please's `release_created`, and none of them runs once a job it needs is
    skipped. The one exception, `!cancelled()`, comes with the foundation's successful apply,
    which only the release's build can have."""
    for name in CHANGING:
        conditions = _conditions(RELEASE, name)
        assert RELEASED in conditions, name
        for condition in conditions:
            assert not re.search(r"\b(always|failure)\(", condition), f"{name}: {condition}"
            if re.search(r"\bcancelled\(", condition):
                assert condition.count("cancelled(") == condition.count("!cancelled()"), (
                    f"{name}: {condition}"
                )
                assert "needs.apply.result == 'success'" in condition, f"{name}: {condition}"
    assert job(RELEASE, "image")["if"] == RELEASED
    assert job(RELEASE, "release-please")["if"] == "github.event_name == 'push'"


def _requires(workflow: str, name: str) -> set[str]:
    """Every job `name` needs, directly or through the jobs it needs."""
    found: set[str] = set()
    for need in _needs(job(workflow, name)):
        found |= {need, *_requires(workflow, need)}
    return found


def test_no_two_jobs_of_a_release_compete_for_the_group() -> None:
    """GitHub runs one job of a group at a time and keeps one pending: two of one release's
    jobs ready together would wait on each other, and a third could cancel one. So each pair
    of the release's jobs in the group is ordered by its needs."""
    holding = [name for name, spec in _jobs(RELEASE).items() if spec.get("concurrency") == GROUP]
    assert holding == CHANGING
    for first, second in itertools.combinations(holding, 2):
        assert first in _requires(RELEASE, second), f"{second} doesn't wait for {first}"


def test_monitoring_is_applied_after_the_moves_whatever_they_did() -> None:
    """current and live never wait for monitoring (ruling 7). Monitoring runs after them, once
    the foundation's apply has succeeded, even when a move failed: a failed move doesn't hold
    it back, and a failed monitoring apply holds back nothing."""
    monitoring = job(RELEASE, "monitoring-apply")
    assert _needs(monitoring) == ["image", "apply", "live"]
    assert monitoring["if"] == AFTER_THE_MOVES
    assert "monitoring-apply" not in _requires(RELEASE, "live")
    assert "monitoring-apply" not in _requires(RELEASE, "current")


def test_current_moves_only_after_the_foundation_s_apply() -> None:
    """Not after monitoring's (ruling 7): a failed monitoring apply holds nothing back. And
    current first, then live."""
    current, live = job(RELEASE, "current"), job(RELEASE, "live")
    assert set(_needs(current)) == {"image", "apply"}
    assert "needs.apply.result == 'success'" in str(current["if"])
    assert _needs(live) == ["image", "current"]
    assert _environment(current) == "prod"

    role = _one(RELEASE, "current", ROLE)
    assert role["with"] == {**IDENTITY, "role": "apply", "project": "infra"}
    credentials = _one(RELEASE, "current", CREDENTIALS)
    assert credentials["with"]["role-to-assume"] == "${{ steps.role.outputs.arn }}"
    assert credentials["with"]["aws-region"] == "us-east-1"
    move = _one(RELEASE, "current", MOVE)
    assert move["with"] == {
        "move": "current",
        "repository": "${{ inputs.platform-image }}",
        "digest": BUILD_DIGEST,
        "commit": BUILD_COMMIT,
    }
    order = [_position(RELEASE, "current", s) for s in (role, credentials, move)]
    assert order == sorted(order), "the role, its credentials, then the move"


def test_the_release_s_jobs_are_named_for_its_tag_and_hold_only_their_grants() -> None:
    workflow = _workflow(RELEASE)
    assert workflow["permissions"] == {}
    jobs = workflow["jobs"]
    assert {name: spec["name"] for name, spec in jobs.items()} == NAMES
    assert list(jobs) == ["release-please", *CHANGING]
    assert job(RELEASE, "image")["outputs"]["tag"] == "${{ needs.release-please.outputs.tag_name }}"
    for name in ("image", "apply", "monitoring-apply", "current"):
        assert jobs[name]["permissions"] == {"contents": "read", "id-token": "write"}, name
        assert _environment(jobs[name]) == "prod", name
    assert jobs["live"]["permissions"] == {"contents": "read"}, "live takes no AWS role"
    assert _environment(jobs["live"]) is None
    assert _environment(jobs["release-please"]) is None


@pytest.mark.parametrize("workflow", [RELEASE, ROLLBACK])
def test_both_workflows_require_the_movers_input_and_secret(workflow: str) -> None:
    call = _workflow(workflow)[True]["workflow_call"]
    client_id = call["inputs"]["live-app-client-id"]
    assert client_id["type"] == "string"
    assert client_id["required"] is True
    assert call["secrets"]["live-app-private-key"]["required"] is True


def test_each_workflow_takes_the_identity_and_only_the_secrets_it_uses() -> None:
    """`jaws platform check` holds the identity literals of each caller of these two to the
    configuration (IDENTITY_WORKFLOWS)."""
    for workflow in (RELEASE, ROLLBACK):
        inputs = _workflow(workflow)[True]["workflow_call"]["inputs"]
        for key in IDENTITY:
            assert inputs[key]["required"] is True, f"{workflow}: {key}"
            assert inputs[key]["type"] == "string", f"{workflow}: {key}"
    release = _workflow(RELEASE)[True]["workflow_call"]
    assert set(release["inputs"]) == {*IDENTITY, "live-app-client-id"}
    assert {name: spec["required"] for name, spec in release["secrets"].items()} == {
        "RELEASE_BOT_CLIENT_ID": True,
        "RELEASE_BOT_PRIVATE_KEY": True,
        "live-app-private-key": True,
    }
    rollback = _workflow(ROLLBACK)[True]["workflow_call"]
    assert set(rollback["inputs"]) == {*IDENTITY, "commit", "live-app-client-id"}
    assert rollback["inputs"]["commit"]["required"] is True
    assert rollback["inputs"]["commit"]["type"] == "string"
    assert set(rollback["secrets"]) == {"live-app-private-key"}, "no release App secret"


#: The job of each workflow that moves live.
LIVE_MOVERS = [(RELEASE, "live"), (ROLLBACK, "rollback")]


def _all_uses() -> set[str]:
    return {
        str(step.get("uses", ""))
        for path in WORKFLOWS.glob("*.yml")
        for spec in yaml.safe_load(path.read_text())["jobs"].values()
        for step in spec.get("steps", [])
    }


@pytest.mark.parametrize(("workflow", "name"), LIVE_MOVERS)
def test_the_live_move_mints_its_token_from_exactly_those(workflow: str, name: str) -> None:
    token = _by_id(workflow, name, "live-token")
    pinned = {uses for uses in _all_uses() if uses.startswith(f"{APP_TOKEN}@")}
    assert pinned == {f"{APP_TOKEN}@v3"}, "the version every workflow pins"
    assert token["uses"] == f"{APP_TOKEN}@v3"
    assert token["with"] == MINTED
    assert "continue-on-error" not in token, "without the mover's token, live doesn't move"
    assert "if" not in token
    (move,) = [s for s in _using(workflow, name, MOVE) if s["with"]["move"] == "live"]
    assert move["with"]["token"] == LIVE_TOKEN
    assert _position(workflow, name, token) < _position(workflow, name, move)


def test_no_step_that_moves_live_uses_the_release_app() -> None:
    for workflow in (RELEASE, ROLLBACK):
        moving = [
            (name, step)
            for name, spec in _jobs(workflow).items()
            for step in spec["steps"]
            if step.get("uses") == MOVE and step["with"]["move"] == "live"
        ]
        assert [name for name, _ in moving] == [n for w, n in LIVE_MOVERS if w == workflow]
        for name, step in moving:
            for checked in (step, _by_id(workflow, name, "live-token")):
                text = json.dumps(checked)
                assert "RELEASE_BOT_CLIENT_ID" not in text, f"{workflow}: {name}"
                assert "RELEASE_BOT_PRIVATE_KEY" not in text, f"{workflow}: {name}"
    rollback = (WORKFLOWS / ROLLBACK).read_text()
    assert "RELEASE_BOT_CLIENT_ID" not in rollback
    assert "RELEASE_BOT_PRIVATE_KEY" not in rollback
    holders = [name for name, spec in _jobs(RELEASE).items() if "RELEASE_BOT_" in json.dumps(spec)]
    assert holders == ["release-please"], "the release App only releases"

    # The move reads its token from its input only: never the job's own, nor a secret.
    assert action_step("platform-move", "live")["env"]["GH_TOKEN"] == "${{ inputs.token }}"
    action = (ACTIONS / "platform-move" / "action.yml").read_text()
    assert "github.token" not in action
    assert "secrets." not in action


def test_every_job_needs_the_jobs_whose_outputs_it_reads() -> None:
    """A job sees `needs.<job>` only for the jobs it needs: any other reads as empty, so a
    condition on it never holds, and an empty digest would run whatever current names."""
    files = sorted(WORKFLOWS.glob("platform-*.yml"))
    assert {RELEASE, ROLLBACK} <= {path.name for path in files}
    for path in files:
        for name, spec in yaml.safe_load(path.read_text())["jobs"].items():
            read = set(re.findall(r"\bneeds\.([A-Za-z0-9_-]+)", json.dumps(spec)))
            missing = sorted(read - set(_needs(spec)))
            assert not missing, f"{path.name}: {name} reads needs.{missing} without needing it"


@pytest.mark.parametrize(
    ("workflow", "name"), [(RELEASE, name) for name in CHANGING] + [(ROLLBACK, "rollback")]
)
def test_every_job_runs_the_tool_from_its_own_commit(workflow: str, name: str) -> None:
    """`tests/test_tool_checkout.py` checks each checkout and its verify step; here, that
    every job has them before it uses any of the tool's actions."""
    steps = _steps(workflow, name)
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
    }
    assert steps[tool[0] + 1]["name"] == "Check jaws is at this workflow's own commit"
    local = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("./")]
    assert local and min(local) > tool[0] + 1, name


# -- the build ------------------------------------------------------------------------


def test_the_build_is_tagged_with_the_release_commit(tmp_path: Path) -> None:
    image = job(RELEASE, "image")
    assert _environment(image) == "prod"
    checkout = _steps(RELEASE, "image")[0]
    assert str(checkout["uses"]).startswith("actions/checkout@")
    assert checkout["with"] == {"ref": "refs/tags/${{ needs.release-please.outputs.tag_name }}"}
    commit = _by_id(RELEASE, "image", "commit")
    role = _one(RELEASE, "image", ROLE)
    assert role["with"] == {**IDENTITY, "role": "apply", "project": "infra"}
    credentials = _one(RELEASE, "image", CREDENTIALS)
    assert credentials["with"]["role-to-assume"] == "${{ steps.role.outputs.arn }}"
    assert credentials["with"]["aws-region"] == "us-east-1"
    login = _one(RELEASE, "image", ECR_LOGIN)
    assert login["id"] == "ecr"
    base = _one(RELEASE, "image", BASE)
    assert base["id"] == "base"
    assert "with" not in base, "the release checks its Jaws base is still published"
    build = _one(RELEASE, "image", BUILD)
    assert build["id"] == "build"
    assert build["with"] == {
        "load": "true",
        "push": "true",
        "tags": (
            "${{ steps.ecr.outputs.registry }}/${{ inputs.platform-image }}"
            ":sha-${{ steps.commit.outputs.commit }}"
        ),
        "revision": "${{ steps.commit.outputs.commit }}",
        "base-name": "${{ steps.base.outputs.base-name }}",
        "base-tag": "${{ steps.base.outputs.base-tag }}",
        "base-digest": "${{ steps.base.outputs.base-digest }}",
    }
    order = [
        _position(RELEASE, "image", s)
        for s in (checkout, commit, role, credentials, login, base, build)
    ]
    assert order == sorted(order)
    builders = [name for name in _jobs(RELEASE) if _using(RELEASE, name, BUILD)]
    assert builders == ["image"], "one build per release"
    assert image["outputs"]["commit"] == "${{ steps.commit.outputs.commit }}"

    # The commit is the checked-out tag's.
    ran = _step(tmp_path, RELEASE, "image", "commit", FAKE_HEAD=COMMIT)
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert ran.output.splitlines() == [f"commit={COMMIT}"]
    assert ran.calls == ["git rev-parse HEAD"]


@needs_yq
def test_a_re_run_reuses_the_release_s_build(tmp_path: Path) -> None:
    """`sha-<commit>` never moves, so a re-run that pushed again would fail on its own tag:
    it finds the build its first attempt pushed, and pulls it in place of a build."""
    built = _by_id(RELEASE, "image", "built")
    assert built["env"] == {
        "REPOSITORY": "${{ inputs.platform-image }}",
        "COMMIT": "${{ steps.commit.outputs.commit }}",
    }
    ran = _step(tmp_path, RELEASE, "image", "built", KEPT, REPOSITORY=REPOSITORY, COMMIT=COMMIT)
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert ran.output.splitlines() == [f"digest={DIGEST}"]
    (call,) = ran.calls
    assert call.startswith("aws ecr batch-get-image ")
    assert f"--repository-name {REPOSITORY} " in call
    assert f"--image-ids imageTag=sha-{COMMIT} " in call

    pull = _one(RELEASE, "image", IMAGE)
    assert pull["id"] == "image"
    assert pull["if"] == "steps.built.outputs.digest != ''"
    assert pull["with"] == {
        "account-id": "${{ inputs.account-id }}",
        "repository": "${{ inputs.platform-image }}",
        "digest": "${{ steps.built.outputs.digest }}",
    }
    for action in (BASE, BUILD):
        assert _one(RELEASE, "image", action)["if"] == "steps.built.outputs.digest == ''", action
    steps = [_one(RELEASE, "image", action) for action in (IMAGE, BASE, BUILD)]
    assert all(_position(RELEASE, "image", built) < _position(RELEASE, "image", s) for s in steps)
    outputs = job(RELEASE, "image")["outputs"]
    assert outputs["digest"] == "${{ steps.built.outputs.digest || steps.pushed.outputs.digest }}"


@needs_yq
def test_a_first_attempt_builds_and_pushes(tmp_path: Path) -> None:
    ran = _step(
        tmp_path, RELEASE, "image", "built", NOT_FOUND, REPOSITORY=REPOSITORY, COMMIT=COMMIT
    )
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert ran.output == "", "no digest: the build and the push run"
    assert _errors(ran) == []


#: batch-get-image's answer when ECR has the release's tag but can't read it.
UNREADABLE: Mapping[str, Any] = {
    "images": [],
    "failures": [
        {
            "imageId": {"imageTag": f"sha-{COMMIT}"},
            "failureCode": "KmsError",
            "failureReason": "the repository's key is disabled",
        }
    ],
}


@needs_yq
def test_a_build_the_registry_can_t_read_stops_the_release(tmp_path: Path) -> None:
    """Only a build that isn't there is built: one ECR can't read is never pushed over."""
    ran = _step(
        tmp_path, RELEASE, "image", "built", UNREADABLE, REPOSITORY=REPOSITORY, COMMIT=COMMIT
    )
    assert ran.result.returncode != 0
    assert _errors(ran) == [
        f"::error::{REPOSITORY}:sha-{COMMIT} could not be read: KmsError "
        "(the repository's key is disabled)"
    ]
    assert ran.output == ""


#: The digest buildx may report for a build it both loads and pushes: the loaded manifest's,
#: which need not be the pushed one's.
LOADED_DIGEST = "sha256:" + "d" * 64


def test_the_release_s_digest_is_ecr_s_never_buildx_s_report() -> None:
    """The job outputs the digest ECR has for `sha-<commit>`: the kept build's, or the push's
    read back. buildx's own report of the push only feeds a warning."""
    outputs = job(RELEASE, "image")["outputs"]
    assert outputs["digest"] == "${{ steps.built.outputs.digest || steps.pushed.outputs.digest }}"
    assert "steps.build.outputs.digest" not in json.dumps(outputs)
    pushed = _by_id(RELEASE, "image", "pushed")
    assert pushed["if"] == "steps.built.outputs.digest == ''"
    assert pushed["env"] == {
        "REPOSITORY": "${{ inputs.platform-image }}",
        "COMMIT": "${{ steps.commit.outputs.commit }}",
        "BUILDX_DIGEST": "${{ steps.build.outputs.digest }}",
    }
    build = _one(RELEASE, "image", BUILD)
    assert _position(RELEASE, "image", build) < _position(RELEASE, "image", pushed)
    reading = [
        s.get("id")
        for s in _steps(RELEASE, "image")
        if "steps.build.outputs.digest" in json.dumps(s)
    ]
    assert reading == ["pushed"], "buildx's report reaches the warning only"

    # It asks ECR for the tag as `built` does.
    lookup = re.compile(r"found=\$\(aws ecr batch-get-image .*?--output json\)", re.S)
    (asked,) = lookup.findall(pushed["run"])
    assert lookup.findall(_by_id(RELEASE, "image", "built")["run"]) == [asked]


@needs_yq
@pytest.mark.parametrize(
    "reported", ["", DIGEST, LOADED_DIGEST], ids=["no-report", "the-same", "another"]
)
def test_the_pushed_build_s_digest_is_read_back_from_ecr(tmp_path: Path, reported: str) -> None:
    ran = _step(
        tmp_path,
        RELEASE,
        "image",
        "pushed",
        KEPT,
        REPOSITORY=REPOSITORY,
        COMMIT=COMMIT,
        BUILDX_DIGEST=reported,
    )
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert ran.output.splitlines() == [f"digest={DIGEST}"], "ECR's, whatever buildx reported"
    (call,) = ran.calls
    assert call.startswith("aws ecr batch-get-image ")
    assert f"--repository-name {REPOSITORY} " in call
    assert f"--image-ids imageTag=sha-{COMMIT} " in call
    assert DIGEST in ran.result.stdout and reported in ran.result.stdout, "the log names both"
    warnings = [line for line in ran.result.stdout.splitlines() if line.startswith("::warning::")]
    if reported == LOADED_DIGEST:
        (warning,) = warnings
        assert LOADED_DIGEST in warning and DIGEST in warning, warning
    else:
        assert warnings == []
    assert _errors(ran) == []


@needs_yq
@pytest.mark.parametrize("images", [NOT_FOUND, UNREADABLE], ids=["not-found", "unreadable"])
def test_a_push_ecr_does_not_have_stops_the_release(
    tmp_path: Path, images: Mapping[str, Any]
) -> None:
    ran = _step(
        tmp_path,
        RELEASE,
        "image",
        "pushed",
        images,
        REPOSITORY=REPOSITORY,
        COMMIT=COMMIT,
        BUILDX_DIGEST=DIGEST,
    )
    assert ran.result.returncode != 0
    (error,) = _errors(ran)
    assert error.startswith(f"::error::{REPOSITORY}:sha-{COMMIT} "), error
    assert ran.output == "", "no digest: no later job runs"


def test_monitoring_is_applied_once_the_build_s_configuration_has_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate comes from the release's own build, offline: what the CLI prints for the
    fixture's configuration, which has a monitoring section."""
    env = _by_id(RELEASE, "image", "env")
    assert env["env"] == {
        "IMAGE_ID": "${{ steps.image.outputs.image-id || steps.build.outputs.image-id }}"
    }
    printed = tmp_path / "env.txt"
    printed.write_text(_printed(tmp_path, monkeypatch, "config", "env", "--monitoring"))
    ran = _step(tmp_path, RELEASE, "image", "env", IMAGE_ID=CONFIG_DIGEST, FAKE_ENV=str(printed))
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert ran.calls == [
        f"docker run --rm --network none --pull never {CONFIG_DIGEST} config env --monitoring"
    ]
    written = dict(line.split("=", 1) for line in ran.output.splitlines())
    assert written["monitoring"] == "configured"
    assert job(RELEASE, "image")["outputs"]["monitoring"] == "${{ steps.env.outputs.monitoring }}"
    condition = job(RELEASE, "monitoring-apply")["if"]
    assert "needs.image.outputs.monitoring == 'configured'" in condition
    assert "image" in _needs(job(RELEASE, "monitoring-apply"))


# -- the applies ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "project", "command"),
    [
        ("apply", "infra", "platform apply foundation"),
        ("monitoring-apply", "monitoring", "platform apply monitoring"),
    ],
)
def test_the_applies_run_the_release_s_build_by_digest(
    name: str, project: str, command: str
) -> None:
    """Never `current`, which still names the last release's build until this one's
    foundation apply succeeds."""
    assert _environment(job(RELEASE, name)) == "prod"
    role = _one(RELEASE, name, ROLE)
    assert role["with"] == {**IDENTITY, "role": "apply", "project": project}
    credentials = _one(RELEASE, name, CREDENTIALS)
    assert credentials["with"]["role-to-assume"] == "${{ steps.role.outputs.arn }}"
    assert credentials["with"]["aws-region"] == "us-east-1"
    image = _one(RELEASE, name, IMAGE)
    assert image["id"] == "image"
    assert image["with"] == {
        "account-id": "${{ inputs.account-id }}",
        "repository": "${{ inputs.platform-image }}",
        "digest": BUILD_DIGEST,
    }, "the build by its digest, with no tag"
    run = _one(RELEASE, name, JAWS)
    assert run["with"] == {
        "command": command,
        "image": "${{ steps.image.outputs.image-id }}",
        "platform-commit": "${{ steps.image.outputs.platform-commit }}",
        "platform-source": "${{ steps.image.outputs.platform-source }}",
    }
    order = [_position(RELEASE, name, s) for s in (role, credentials, image, run)]
    assert order == sorted(order), "the role, its credentials, the build, then the apply"


#: The jobs that run or move the image job's build, and the outputs each checks first.
CHECKED = {
    "apply": {"DIGEST": BUILD_DIGEST},
    "monitoring-apply": {"DIGEST": BUILD_DIGEST},
    "current": {"DIGEST": BUILD_DIGEST, "COMMIT": BUILD_COMMIT},
    "live": {"DIGEST": BUILD_DIGEST, "COMMIT": BUILD_COMMIT},
}
#: What the image job outputs for a release's build.
BUILT = {"DIGEST": DIGEST, "COMMIT": COMMIT}


@pytest.mark.parametrize("name", list(CHECKED))
def test_an_empty_build_output_stops_the_job(tmp_path: Path, name: str) -> None:
    """platform-image takes `current` when no digest is given, so an output that came out
    empty, an output name's typo for one, would run or move whatever current names now, not
    the release's build."""
    guard = _by_id(RELEASE, name, "release-build")
    assert guard["env"] == CHECKED[name]
    steps = _steps(RELEASE, name)
    users = _using(RELEASE, name, IMAGE) + _using(RELEASE, name, MOVE)
    assert users, name
    reading = [
        i
        for i, s in enumerate(steps)
        if s.get("id") != "release-build"
        and (BUILD_DIGEST in json.dumps(s) or BUILD_COMMIT in json.dumps(s))
    ]
    assert steps.index(guard) < min(reading), f"{name}: checked before its first use"
    assert all(steps.index(guard) < steps.index(s) for s in users), name

    whole = {key: BUILT[key] for key in guard["env"]}
    ran = _step(tmp_path, RELEASE, name, "release-build", **whole)
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    for key in guard["env"]:
        ran = _step(tmp_path, RELEASE, name, "release-build", **{**whole, key: ""})
        assert ran.result.returncode != 0, f"{name}: {key}"
        (error,) = _errors(ran)
        assert error.startswith(f"::error::needs.image.outputs.{key.lower()} is empty"), error


def test_release_please_writes_with_the_app_s_token_only() -> None:
    """release-please.yml's job, but with contents: read: the App's token does the writes,
    and a called job can't ask for more than its caller grants."""
    ours = job(RELEASE, "release-please")
    assert ours["permissions"] == {"contents": "read"}
    theirs = job("release-please.yml", "release-please")
    assert ours == {**theirs, "permissions": {"contents": "read"}}


def test_a_release_or_rollback_is_never_cancelled() -> None:
    """GitHub keeps one pending run per group: a group at a workflow's top would let each
    push to main, which runs the release for Release Please, cancel a pending release."""
    for name in CHANGING:
        assert job(RELEASE, name)["concurrency"] == GROUP, name
    assert job(ROLLBACK, "rollback")["concurrency"] == GROUP
    assert "concurrency" not in job(RELEASE, "release-please"), "a push takes no turn"
    for workflow in (RELEASE, ROLLBACK):
        assert "concurrency" not in _workflow(workflow), workflow


# -- a stale re-run -------------------------------------------------------------------

#: The jobs that apply or move the release's build. Each first checks that no newer release is
#: live, so a re-run of an older release's failed job stops before it changes anything.
GUARDED = ["apply", "current", "monitoring-apply"]
#: The check's environment: the release commit, and the job's own token, which reads live.
NEWEST = {"COMMIT": BUILD_COMMIT, "GH_TOKEN": "${{ github.token }}"}
#: The check's one call: GitHub's comparison of the release commit with live.
COMPARE = f"gh api repos/{HUB_NAME}/compare/{COMMIT}...live --jq .status"


def _newest(tmp_path: Path, name: str, **env: str) -> Ran:
    """Run job `name`'s check for COMMIT, with the job's own token; `env` sets what GitHub's
    comparison of COMMIT with live answers."""
    return _step(
        tmp_path,
        RELEASE,
        name,
        "newest",
        **{"COMMIT": COMMIT, "GH_TOKEN": JOB_TOKEN, "FAKE_TOKEN": JOB_TOKEN, **env},
    )


def test_each_job_that_applies_or_moves_first_checks_no_newer_release_is_live() -> None:
    """Once a newer release is live, a re-run of an older release's failed job would apply the
    older configuration, or move current back to the older build while live keeps the newer
    workflow files: the pair ruling 7 rules out. So the check comes before anything the job
    changes. A rollback moves back on purpose, and doesn't check."""
    guards = {
        name: step
        for name in _jobs(RELEASE)
        for step in _steps(RELEASE, name)
        if step.get("id") == "newest"
    }
    assert list(guards) == GUARDED
    for name in GUARDED:
        guard = guards[name]
        assert guard == guards["apply"], f"{name}: every job checks alike"
        assert guard["env"] == NEWEST, name
        steps = _steps(RELEASE, name)
        assert steps.index(_by_id(RELEASE, name, "release-build")) < steps.index(guard), name
        changing = [
            *_using(RELEASE, name, CREDENTIALS),
            *_using(RELEASE, name, IMAGE),
            *_using(RELEASE, name, MOVE),
            *_using(RELEASE, name, JAWS),
        ]
        assert changing, name
        assert all(steps.index(guard) < steps.index(s) for s in changing), name
    assert "...live" not in (WORKFLOWS / ROLLBACK).read_text(), "a rollback moves back"


@pytest.mark.parametrize("name", GUARDED)
@pytest.mark.parametrize(
    "env",
    [{"FAKE_STATUS": "behind"}, {"FAKE_STATUS": "identical"}, {"FAKE_COMPARE_ERROR": "Not Found"}],
    ids=["live-is-older", "live-is-this-release", "no-live-yet"],
)
def test_a_release_no_older_than_live_goes_on(
    tmp_path: Path, name: str, env: dict[str, str]
) -> None:
    """live is behind the release commit; or at it, as on a re-run once this release has moved
    it; or doesn't exist yet, before the hub's first release, and GitHub can't find it."""
    ran = _newest(tmp_path, name, **env)
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert ran.calls == [COMPARE]
    assert _errors(ran) == []
    assert ran.output == ""


@pytest.mark.parametrize("name", GUARDED)
def test_a_re_run_once_a_newer_release_is_live_stops(tmp_path: Path, name: str) -> None:
    """live holds commits the release lacks: a newer release is live. The way back to this
    release is the rollback, which moves live and current together."""
    ran = _newest(tmp_path, name, FAKE_STATUS="ahead")
    assert ran.result.returncode != 0
    (error,) = _errors(ran)
    assert error.startswith("::error::a newer release is live"), error
    assert COMMIT in error and "rollback" in error, error
    assert ran.calls == [COMPARE]


@pytest.mark.parametrize("name", GUARDED)
@pytest.mark.parametrize(
    ("env", "named"),
    [
        ({"FAKE_STATUS": "diverged"}, "'diverged'"),
        (
            {"FAKE_COMPARE_ERROR": "Server Error", "FAKE_COMPARE_CODE": "500"},
            "Server Error (HTTP 500)",
        ),
        ({"GH_TOKEN": "another-token"}, "Bad credentials (HTTP 401)"),
    ],
    ids=["diverged", "a-server-error", "a-refused-token"],
)
def test_any_other_answer_stops_the_job_naming_it(
    tmp_path: Path, name: str, env: dict[str, str], named: str
) -> None:
    ran = _newest(tmp_path, name, **env)
    assert ran.result.returncode != 0
    (error,) = _errors(ran)
    assert named in error and COMMIT in error, error
    assert ran.calls == [COMPARE]


@pytest.mark.parametrize("name", GUARDED)
@pytest.mark.parametrize(
    "commit", ["", COMMIT.upper(), "main"], ids=["empty", "not-lowercase", "a-branch"]
)
def test_the_check_compares_the_release_commit_only(tmp_path: Path, name: str, commit: str) -> None:
    """An empty commit would compare `...live`, which GitHub can't find: a 404 that must never
    pass for a first release."""
    ran = _newest(tmp_path, name, FAKE_STATUS="behind", COMMIT=commit)
    assert ran.result.returncode != 0
    (error,) = _errors(ran)
    assert error.startswith("::error::needs.image.outputs.commit "), error
    assert ran.calls == [], "nothing reaches GitHub"


# -- platform-move --------------------------------------------------------------------


def test_platform_move_takes_what_both_moves_need() -> None:
    inputs = _action("platform-move")["inputs"]
    assert {name for name, spec in inputs.items() if spec.get("required")} == {"move"}
    assert {name: spec.get("default") for name, spec in inputs.items()} == {
        "move": None,
        "repository": "",
        "digest": "",
        "commit": "",
        "token": "",
        "force": "false",
    }
    steps = _action("platform-move")["runs"]["steps"]
    assert [step["id"] for step in steps] == ["check", "current", "live"]
    assert "if" not in steps[0]
    assert steps[1]["if"] == "inputs.move == 'current'"
    assert steps[2]["if"] == "inputs.move == 'live'"
    assert action_step("platform-move", "check")["env"] == {"MOVE": "${{ inputs.move }}"}


@pytest.mark.parametrize("move", ["current", "live", "Current", "tag", ""])
def test_platform_move_moves_current_or_live_only(tmp_path: Path, move: str) -> None:
    """A move it doesn't know would otherwise skip both moves, and pass."""
    ran = _move(tmp_path, "check", MOVE=move)
    if move in ("current", "live"):
        assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    else:
        assert ran.result.returncode != 0
        assert _errors(ran) == [f"::error::move must be current or live, got '{move}'"]
    assert ran.calls == []


@needs_yq
def test_moving_current_retags_the_build(tmp_path: Path) -> None:
    assert action_step("platform-move", "current")["env"] == {
        "REPOSITORY": "${{ inputs.repository }}",
        "DIGEST": "${{ inputs.digest }}",
        "COMMIT": "${{ inputs.commit }}",
    }
    ran = _move(tmp_path, "current", FOUND, **CURRENT)
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    read, put = ran.calls
    assert read.startswith("aws ecr batch-get-image ")
    assert f"--repository-name {REPOSITORY} " in read
    assert f"--image-ids imageDigest={DIGEST} " in read
    assert put.startswith("aws ecr put-image ")
    given = f"{put} "
    assert f" --repository-name {REPOSITORY} " in given
    assert " --image-tag current " in given
    assert f" --image-digest {DIGEST} " in given
    assert f" --image-manifest-media-type {MEDIA_TYPE} " in given
    assert (tmp_path / "manifest.json").read_text() == MANIFEST, "the build's manifest, as read"
    assert ran.summary.splitlines() == [MOVED]

    # current already names the build, as on a re-run: nothing moves, and the job passes.
    ran = _move(tmp_path, "current", FOUND, **CURRENT, FAKE_PUT_ERROR="ImageAlreadyExistsException")
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert _errors(ran) == []
    assert "ImageAlreadyExistsException" not in ran.result.stderr
    assert ran.summary.splitlines() == [MOVED]


@needs_yq
@pytest.mark.parametrize(
    "exception",
    [
        "ImageTagAlreadyExistsException",
        "ImageDigestDoesNotMatchException",
        "LayersNotFoundException",
    ],
    ids=["current-is-immutable", "another-manifest", "layers-gone"],
)
def test_a_move_of_current_that_ecr_refuses_stops_the_job(tmp_path: Path, exception: str) -> None:
    ran = _move(tmp_path, "current", FOUND, **CURRENT, FAKE_PUT_ERROR=exception)
    assert ran.result.returncode != 0
    (error,) = _errors(ran)
    assert error.startswith("::error::current ") and DIGEST in error and COMMIT in error, error
    assert exception in ran.result.stderr, "ECR's answer is in the log"
    assert ran.summary == ""


@needs_yq
def test_current_never_moves_to_a_build_the_registry_does_not_have(tmp_path: Path) -> None:
    ran = _move(tmp_path, "current", NOT_FOUND, **CURRENT)
    assert ran.result.returncode != 0
    assert _errors(ran) == [f"::error::{REPOSITORY}@{DIGEST} does not exist"]
    assert [call.split()[2] for call in ran.calls] == ["batch-get-image"], "no put-image"
    assert ran.summary == ""


@pytest.mark.parametrize(
    ("name", "env"),
    [
        pytest.param("repository", {"REPOSITORY": ""}, id="no-repository"),
        pytest.param("digest", {"DIGEST": ""}, id="no-digest"),
        pytest.param("digest", {"DIGEST": "sha256:bbb"}, id="not-a-digest"),
        pytest.param("commit", {"COMMIT": ""}, id="no-commit"),
        pytest.param("commit", {"COMMIT": COMMIT.upper()}, id="not-lowercase"),
    ],
)
def test_current_moves_only_to_a_named_build(
    tmp_path: Path, name: str, env: dict[str, str]
) -> None:
    ran = _move(tmp_path, "current", FOUND, **{**CURRENT, **env})
    assert ran.result.returncode != 0
    (error,) = _errors(ran)
    assert error.startswith(f"::error::{name} "), error
    assert ran.calls == [], "nothing reaches AWS"


def test_live_is_fast_forwarded_by_the_mover_app_and_created_once(tmp_path: Path) -> None:
    live = action_step("platform-move", "live")
    assert live["env"] == {
        "COMMIT": "${{ inputs.commit }}",
        "FORCE": "${{ inputs.force }}",
        "GH_TOKEN": "${{ inputs.token }}",
    }
    move = _one(RELEASE, "live", MOVE)
    assert move["with"] == {"move": "live", "commit": BUILD_COMMIT, "token": LIVE_TOKEN}
    assert "force" not in move["with"], "a release only fast-forwards live"

    ran = _move(tmp_path, "live", **LIVE)
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert ran.calls == [f"{PATCH}false"]
    assert ran.summary.splitlines() == [f"`live` is at `{COMMIT}`"]

    # The first release creates live.
    ran = _move(tmp_path, "live", **LIVE, FAKE_PATCH_ERROR="Reference does not exist")
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert ran.calls == [f"{PATCH}false", POST]
    assert _errors(ran) == []
    assert ran.summary.splitlines() == [f"`live` is at `{COMMIT}`"]


@pytest.mark.parametrize(
    "env",
    [
        {"FAKE_PATCH_ERROR": "Update is not a fast forward"},
        {"FAKE_PATCH_ERROR": "Repository rule violations found"},
        {
            "FAKE_PATCH_ERROR": "Reference does not exist",
            "FAKE_POST_ERROR": "Reference already exists",
        },
        {"GH_TOKEN": "the-release-app-s-token"},
    ],
    ids=["not-a-fast-forward", "a-ruleset-refuses", "created-meanwhile", "another-app-s-token"],
)
def test_a_move_of_live_github_refuses_stops_the_job(tmp_path: Path, env: dict[str, str]) -> None:
    ran = _move(tmp_path, "live", **{**LIVE, **env})
    assert ran.result.returncode != 0
    (error,) = _errors(ran)
    assert "live" in error and COMMIT in error, error
    assert ran.summary == ""


@pytest.mark.parametrize(
    ("name", "env"),
    [
        pytest.param("token", {"GH_TOKEN": ""}, id="no-token"),
        pytest.param("commit", {"COMMIT": ""}, id="no-commit"),
        pytest.param("commit", {"COMMIT": "main"}, id="a-branch"),
        pytest.param("force", {"FORCE": "yes"}, id="force-not-a-boolean"),
    ],
)
def test_live_moves_only_to_a_commit_with_the_mover_app_s_token(
    tmp_path: Path, name: str, env: dict[str, str]
) -> None:
    ran = _move(tmp_path, "live", **{**LIVE, **env})
    assert ran.result.returncode != 0
    (error,) = _errors(ran)
    assert error.startswith(f"::error::{name} "), error
    assert ran.calls == [], "nothing reaches GitHub"


# -- the rollback ---------------------------------------------------------------------


def _check(tmp_path: Path, images: Mapping[str, Any], status: str, **env: str) -> Ran:
    """Run the rollback's `check` for COMMIT, where main's compare answers `status`."""
    return _step(
        tmp_path,
        ROLLBACK,
        "rollback",
        "check",
        images,
        **{
            "COMMIT": COMMIT,
            "REPOSITORY": REPOSITORY,
            "GH_TOKEN": JOB_TOKEN,
            "FAKE_TOKEN": JOB_TOKEN,
            "FAKE_STATUS": status,
            **env,
        },
    )


@needs_yq
@pytest.mark.parametrize("status", ["ahead", "identical"])
def test_a_rollback_moves_current_and_live_to_a_kept_build(tmp_path: Path, status: str) -> None:
    rollback = job(ROLLBACK, "rollback")
    assert rollback["name"] == "Roll back to ${{ inputs.commit }}"
    assert _environment(rollback) == "prod"
    assert _workflow(ROLLBACK)["permissions"] == {}
    assert rollback["permissions"] == {"contents": "read", "id-token": "write"}
    role = _one(ROLLBACK, "rollback", ROLE)
    assert role["with"] == {**IDENTITY, "role": "apply", "project": "infra"}
    credentials = _one(ROLLBACK, "rollback", CREDENTIALS)
    assert credentials["with"]["role-to-assume"] == "${{ steps.role.outputs.arn }}"
    check = _by_id(ROLLBACK, "rollback", "check")
    assert check["env"] == {
        "COMMIT": "${{ inputs.commit }}",
        "REPOSITORY": "${{ inputs.platform-image }}",
        "GH_TOKEN": "${{ github.token }}",
    }
    live, current = _using(ROLLBACK, "rollback", MOVE)
    assert live["with"] == {
        "move": "live",
        "commit": "${{ inputs.commit }}",
        "token": LIVE_TOKEN,
        "force": "true",
    }
    assert current["with"] == {
        "move": "current",
        "repository": "${{ inputs.platform-image }}",
        "digest": "${{ steps.check.outputs.digest }}",
        "commit": "${{ inputs.commit }}",
    }
    # live back first, then current (ruling 7's invariant, moving backward): in between, a
    # project runs the newer build with the older workflow files, never the reverse. And the
    # mover App's token comes before either move, so a token that can't be minted moves
    # nothing.
    token = _by_id(ROLLBACK, "rollback", "live-token")
    assert _position(ROLLBACK, "rollback", token) < min(
        _position(ROLLBACK, "rollback", move) for move in (live, current)
    ), "the token before either move"
    order = [
        _position(ROLLBACK, "rollback", s) for s in (role, credentials, check, token, live, current)
    ]
    assert order == sorted(order), "the check, the token, live, then current"
    for action in (IMAGE, BUILD, JAWS):
        assert not _using(ROLLBACK, "rollback", action), f"a rollback applies nothing: {action}"

    ran = _check(tmp_path, KEPT, status)
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert ran.output.splitlines() == [f"digest={DIGEST}"]
    compare, read = ran.calls
    assert compare == f"gh api repos/{HUB_NAME}/compare/{COMMIT}...main --jq .status"
    assert read.startswith("aws ecr batch-get-image ")
    assert f"--repository-name {REPOSITORY} " in read
    assert f"--image-ids imageTag=sha-{COMMIT} " in read

    # live is moved by force: a rollback moves it back, never forward.
    ran = _move(tmp_path, "live", **{**LIVE, "FORCE": "true"})
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert ran.calls == [f"{PATCH}true"]


@needs_yq
def test_a_rollback_to_a_build_no_longer_kept_stops(tmp_path: Path) -> None:
    ran = _check(tmp_path, NOT_FOUND, "ahead")
    assert ran.result.returncode != 0
    assert _errors(ran) == [
        f"::error::no build of {COMMIT} is kept: the newest ten are; "
        "roll back to one of them, or release a fix"
    ]
    assert ran.output == ""


@needs_yq
@pytest.mark.parametrize("status", ["behind", "diverged"])
def test_a_rollback_to_a_commit_not_on_main_stops(tmp_path: Path, status: str) -> None:
    ran = _check(tmp_path, KEPT, status)
    assert ran.result.returncode != 0
    assert _errors(ran) == [f"::error::{COMMIT} is not on main"]
    assert [call.split()[0] for call in ran.calls] == ["gh"], "no build is looked up"
    assert ran.output == ""


@needs_yq
def test_a_rollback_to_a_commit_github_does_not_know_stops(tmp_path: Path) -> None:
    ran = _check(tmp_path, KEPT, "", FAKE_COMPARE_ERROR="Not Found")
    assert ran.result.returncode != 0
    (error,) = _errors(ran)
    assert COMMIT in error and "main" in error, error
    assert [call.split()[0] for call in ran.calls] == ["gh"], "no build is looked up"
    assert ran.output == ""


@pytest.mark.parametrize(
    "commit", ["", "0123abc", COMMIT.upper(), f"{COMMIT}0", "main"], ids=lambda c: c or "empty"
)
def test_a_rollback_takes_only_a_full_commit_sha(tmp_path: Path, commit: str) -> None:
    ran = _check(tmp_path, KEPT, "ahead", COMMIT=commit)
    assert ran.result.returncode != 0
    (error,) = _errors(ran)
    assert error.startswith("::error::commit "), error
    assert ran.calls == [], "nothing reaches GitHub or AWS"
