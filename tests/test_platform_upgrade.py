"""`platform-upgrade.yml`: one pull request bumps every Jaws pin of a hub.

A hub's workflow files and its `Dockerfile` name one Jaws release (spec 6.4, ruling 11), so an
upgrade is one pull request that bumps them all: the `FROM` line, to the release's tag and
digest, and every call of a Jaws workflow. Dependabot would split the image and workflow bumps
into separate pull requests. The newest release is read from ECR Public's tags, anonymously and
by semver, so a GitHub release whose image isn't published yet is never picked (ruling 12). The
pull request stays on one branch, `jaws-upgrade`, and is left alone while it is open for the
newest release, so the hub's CI runs once per release rather than every hour. Only the hub's
own pull request from that branch counts, never a fork's from a branch of the same name.

The upgrade App's token does every write: `GITHUB_TOKEN` can't change `.github/workflows/`, and
its pull requests run no CI. The steps' scripts run here as Actions runs them: `newest` with a
stand-in for curl, `rewrite` in a real repository, and `pull-request` in one too, with
stand-ins for gh and for git's push.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import yaml

from tests.workflow_steps import ACTIONS, WORKFLOWS, job, run_step

UPGRADE = "platform-upgrade.yml"
JOB = "upgrade"
BASE = "./.jaws-tool/.github/actions/platform-base"
APP_TOKEN = "actions/create-github-app-token"
CHECKOUT = "actions/checkout"
#: The upgrade App's token, as the steps after it read it.
TOKEN = "${{ steps.app-token.outputs.token }}"
#: Only a newer release is bumped to.
NEWER_ONLY = "steps.newest.outputs.newer == 'true'"

#: The Jaws base the hub's Dockerfile pins, and the newer release the upgrade finds.
NAME = "public.ecr.aws/example-alias/jaws"
PIN = "v0.9.0"
PINNED_DIGEST = "sha256:" + "a" * 64
TAG = "v0.10.0"
DIGEST = "sha256:" + "b" * 64
#: A release after TAG, published while the upgrade to TAG is open.
LATER = "v0.11.0"
LATER_DIGEST = "sha256:" + "c" * 64
REGISTRY = "https://public.ecr.aws/v2/example-alias/jaws"
ANONYMOUS = (
    "https://public.ecr.aws/token/?service=public.ecr.aws&scope=repository:example-alias/jaws:pull"
)
MESSAGE = f"chore(deps): upgrade jaws to {TAG}"
#: How the step lists the open pull requests from jaws-upgrade: the hub's own only, never a
#: fork's from a branch of the same name.
LISTED = (
    "gh pr list --head jaws-upgrade --state open --json number,title,isCrossRepository "
    "--jq map(select(.isCrossRepository == false))"
)

#: The upgrade App, as create-github-app-token names it, and its bot, the commit's author.
APP_SLUG = "example-upgrades"
BOT = "example-upgrades[bot]"
BOT_EMAIL = "12345+example-upgrades[bot]@users.noreply.github.com"
APP_TOKEN_VALUE = "the-upgrade-app-s-token"
HUB_NAME = "Example-Hub/platform"

DOCKERFILE = "Dockerfile"
SITE_PLAN = ".github/workflows/site-plan.yml"
UPGRADE_CALLER = ".github/workflows/upgrade.yaml"
LINT = ".github/workflows/lint.yml"
#: The files a bump changes, in the order git lists them.
BUMPED = sorted([DOCKERFILE, SITE_PLAN, UPGRADE_CALLER])
#: A hub's checkout of its main, pinned at PIN: its Dockerfile, two callers of Jaws's workflows
#: (one of them a .yaml), and a call of another repository's workflow at the same version.
HUB = {
    DOCKERFILE: (
        "# The hub's image: Jaws, and this platform's configuration. FROM pins it.\n"
        f"FROM {NAME}:{PIN}@{PINNED_DIGEST}\n"
        "COPY config/ /etc/jaws/config/\n"
        "COPY datasets/ /etc/jaws/datasets/\n"
    ),
    SITE_PLAN: (
        "name: Site plan\n"
        "on:\n"
        "  workflow_call:\n"
        "jobs:\n"
        "  plan:\n"
        f"    uses: Jaws-Platform/jaws/.github/workflows/site-plan.yml@{PIN}\n"
        "    with:\n"
        "      platform-image: jaws-platform\n"
        '      account-id: "123456789012"\n'
        "      name-root: jaws\n"
        "      check-prefix: jaws\n"
    ),
    UPGRADE_CALLER: (
        "name: Upgrade Jaws\n"
        "on:\n"
        "  schedule:\n"
        '    - cron: "23 * * * *"\n'
        "jobs:\n"
        "  upgrade:\n"
        "    permissions:\n"
        "      contents: read\n"
        f"    uses: Jaws-Platform/jaws/.github/workflows/platform-upgrade.yml@{PIN}\n"
        "    with:\n"
        "      app-client-id: Iv23liEXAMPLE0000002\n"
        "    secrets:\n"
        "      app-private-key: ${{ secrets.UPGRADES_APP_PRIVATE_KEY }}\n"
    ),
    LINT: (
        "name: Lint\n"
        "on: [pull_request]\n"
        "jobs:\n"
        "  lint:\n"
        f"    uses: Example-Org/tools/.github/workflows/lint.yml@{PIN}\n"
    ),
}

#: The real git: the stand-in for it runs every call but a push.
REAL_GIT = shutil.which("git") or "git"
#: Git without the developer's own configuration (signing, hooks), as test_public_image.py
#: runs it.
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
#: Neutral authors for the hub's own commits, as tests/test_tool_checkout.py's.
AUTHOR = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}

needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is on runners")

#: Stands in for curl: logs each call and answers as ECR Public does. The token request gets an
#: anonymous token, the tag list FAKE_TAGS (separated by spaces), and a manifest's HEAD the
#: header `docker-content-digest: FAKE_DIGEST`. The request whose URL holds FAKE_FAIL gets an
#: HTTP error: with -f, curl exits 22; without it, curl prints the error's body and exits 0.
FAKE_CURL = r"""#!/usr/bin/env bash
echo "curl $*" >> "$FAKE_LOG"
if [[ -n "${FAKE_FAIL:-}" && "$*" == *"$FAKE_FAIL"* ]]; then
  for arg in "$@"; do
    if [[ "$arg" == --fail || ( "$arg" == -[!-]* && "$arg" == *f* ) ]]; then
      echo "curl: (22) The requested URL returned error: 503" >&2
      exit 22
    fi
  done
  echo '{"errors": [{"code": "UNAVAILABLE", "message": "unavailable"}]}'
  exit 0
fi
case "$*" in
  *" https://public.ecr.aws/token/"*) echo '{"token": "anonymous"}' ;;
  *"/tags/list?n=1000")
    jq -cn --arg tags "$FAKE_TAGS" '{name: "example-alias/jaws", tags: ($tags | split(" "))}'
    ;;
  *" -I "*"/manifests/"*)
    printf 'HTTP/2 200\r\ncontent-type: application/vnd.oci.image.index.v1+json\r\n'
    printf 'docker-content-digest: %s\r\n\r\n' "$FAKE_DIGEST"
    ;;
  *) echo "unexpected: curl $*" >&2; exit 2 ;;
esac
"""
#: Stands in for git: logs each call and runs it, but a push, which reaches no remote. The
#: hub's repository is real, so what the step commits can be read back.
FAKE_GIT = """#!/usr/bin/env bash
echo "git $*" >> "$FAKE_LOG"
if [[ "$1" == push ]]; then
  exit 0
fi
exec "$REAL_GIT" "$@"
"""
#: Stands in for gh: logs each call, and answers only the upgrade App's token, FAKE_TOKEN, as
#: GitHub answers only a valid one. It knows the App's bot, and keeps the body a pull request is
#: created or edited with in FAKE_BODY. It lists the open pull requests in the JSON file
#: FAKE_PRS as GitHub lists those from a branch named jaws-upgrade, a fork's among them: with
#: only the fields --json names, then filtered by --jq, as gh filters them.
FAKE_GH = """#!/usr/bin/env bash
echo "gh $*" >> "$FAKE_LOG"
fail() {
  echo "{\\"message\\": \\"$1\\"}"
  echo "gh: $1 (HTTP $2)" >&2
  exit 1
}
[[ "${GH_TOKEN:-}" == "$FAKE_TOKEN" ]] || fail "Bad credentials" 401
case "$1 $2" in
  "api users/example-upgrades[bot]") echo '{"login": "example-upgrades[bot]", "id": 12345}' ;;
  "api "*) fail "Not Found" 404 ;;
  "pr list")
    shift 2
    head="" state="" fields="" filter="."
    while [[ $# -gt 0 ]]; do
      [[ $# -ge 2 ]] || { echo "unexpected: gh pr list ... $1" >&2; exit 2; }
      case "$1" in
        --head) head=$2 ;;
        --state) state=$2 ;;
        --json) fields=$2 ;;
        --jq) filter=$2 ;;
        *) echo "unexpected: gh pr list ... $1" >&2; exit 2 ;;
      esac
      shift 2
    done
    if [[ "$head" != jaws-upgrade || "$state" != open || -z "$fields" ]]; then
      echo "unexpected: gh pr list --head $head --state $state --json $fields" >&2
      exit 2
    fi
    jq -c --arg fields "$fields" \\
      '[.[] | with_entries(select(.key as $k | $fields | split(",") | index($k)))]' "$FAKE_PRS" \\
      | jq -c "$filter"
    ;;
  "pr create" | "pr edit")
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == --body-file ]]; then cp "$2" "$FAKE_BODY"; fi
      shift
    done
    ;;
  *) echo "unexpected: gh $*" >&2; exit 2 ;;
esac
"""


class Ran(NamedTuple):
    """A step's run: its result, GITHUB_OUTPUT, the stand-ins' calls, and the body it gave a
    pull request ("" when it gave none)."""

    result: subprocess.CompletedProcess[str]
    output: str
    calls: list[str]
    body: str = ""


def _workflow() -> dict[Any, Any]:
    parsed: dict[Any, Any] = yaml.safe_load((WORKFLOWS / UPGRADE).read_text())
    return parsed


def _steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = job(UPGRADE, JOB)["steps"]
    return steps


def _by_id(step_id: str) -> dict[str, Any]:
    (found,) = [s for s in _steps() if s.get("id") == step_id]
    return found


def _using(action: str) -> list[dict[str, Any]]:
    """The job's steps that use `action`, at any version, in order."""
    return [s for s in _steps() if str(s.get("uses", "")).split("@")[0] == action]


def _header() -> str:
    """The workflow's opening comment, as one line."""
    lines = (WORKFLOWS / UPGRADE).read_text().splitlines()
    opening = itertools.takewhile(lambda line: not line.startswith("on:"), lines)
    words = " ".join(line.lstrip("#") for line in opening if line.startswith("#"))
    return " ".join(words.split())


def _errors(ran: Ran) -> list[str]:
    return [line for line in ran.result.stdout.splitlines() if line.startswith("::error::")]


def _notices(ran: Ran) -> list[str]:
    return [line for line in ran.result.stdout.splitlines() if line.startswith("::notice::")]


def _writes(ran: Ran) -> list[str]:
    """What the run pushed, and the pull requests it created or edited, each body `<body>`."""
    return [
        re.sub(r"--body-file \S+$", "--body-file <body>", call)
        for call in ran.calls
        if call.startswith(("git push", "gh pr create", "gh pr edit"))
    ]


def _git(repo: Path, *args: str) -> str:
    """Run git in `repo` as the hub's own author; what it prints."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**os.environ, **GIT_ENV, **AUTHOR},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _git_init(path: Path) -> None:
    """Make `path` a repository with one commit, of the files in it, on main."""
    _git(path, "init", "-q", "-b", "main")
    _git(path, "add", "--all")
    _git(path, "commit", "-q", "-m", "chore: the hub")


def _state(repo: Path) -> Path:
    """Where the stand-ins keep their logs and answers, and the steps their temporary files:
    beside the hub's repository, never in it."""
    state = repo.parent / "state"
    state.mkdir(exist_ok=True)
    return state


def _hub(tmp_path: Path, files: Mapping[str, str] = HUB) -> Path:
    """The hub's checkout of its main: `files`, committed."""
    repo = tmp_path / "hub"
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git_init(repo)
    return repo


def _newest(
    tmp_path: Path,
    tags: list[str],
    *,
    name: str = NAME,
    fail: str = "",
    digest: str = DIGEST,
) -> Ran:
    """Run `newest` for the base `name`, pinned at PIN, with ECR Public listing `tags` and naming
    `digest` for a manifest. The request whose URL holds `fail` fails."""
    log = tmp_path / "calls.log"
    log.write_text("")
    result, output = run_step(
        UPGRADE,
        JOB,
        "newest",
        cwd=tmp_path,
        env={
            "NAME": name,
            "PIN": PIN,
            "MANIFEST_TYPES": _by_id("newest")["env"]["MANIFEST_TYPES"],
            "FAKE_LOG": str(log),
            "FAKE_TAGS": " ".join(tags),
            "FAKE_DIGEST": digest,
            "FAKE_FAIL": fail,
        },
        fakes={"curl": FAKE_CURL},
    )
    return Ran(result, output, log.read_text().splitlines())


def _rewrite(
    repo: Path, *, pin: str = PIN, tag: str = TAG, digest: str = DIGEST
) -> subprocess.CompletedProcess[str]:
    """Run `rewrite` in the hub `repo`, from `pin` to `tag` at `digest`."""
    result, _ = run_step(
        UPGRADE,
        JOB,
        "rewrite",
        cwd=repo,
        env={**GIT_ENV, "PIN": pin, "TAG": tag, "DIGEST": digest, "TMPDIR": str(_state(repo))},
    )
    return result


def _bumped(tmp_path: Path) -> Path:
    """The hub's checkout, as `rewrite` leaves it: bumped from PIN to TAG."""
    repo = _hub(tmp_path)
    result = _rewrite(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    return repo


def _open(number: int, title: str, *, fork: bool = False) -> dict[str, Any]:
    """An open pull request from a branch named jaws-upgrade, as gh lists it: the hub's own, or
    a fork's, which any GitHub user can open."""
    return {"number": number, "title": title, "isCrossRepository": fork}


def _pull_request(repo: Path, prs: list[dict[str, Any]], *, tag: str = TAG) -> Ran:
    """Run `pull-request` in the hub `repo`, bumped from PIN to `tag`, while `prs` are the open
    pull requests from a branch named jaws-upgrade, newest first: the hub's own, and forks'."""
    state = _state(repo)
    log, listed, body = state / "calls.log", state / "prs.json", state / "body.md"
    log.write_text("")
    listed.write_text(json.dumps(prs))
    body.unlink(missing_ok=True)
    result, output = run_step(
        UPGRADE,
        JOB,
        "pull-request",
        cwd=repo,
        env={
            **GIT_ENV,
            "GH_TOKEN": APP_TOKEN_VALUE,
            "GH_REPO": HUB_NAME,
            "APP_SLUG": APP_SLUG,
            "PIN": PIN,
            "TAG": tag,
            "REAL_GIT": REAL_GIT,
            "FAKE_LOG": str(log),
            "FAKE_TOKEN": APP_TOKEN_VALUE,
            "FAKE_PRS": str(listed),
            "FAKE_BODY": str(body),
            "TMPDIR": str(state),
        },
        fakes={"git": FAKE_GIT, "gh": FAKE_GH},
    )
    # run_step leaves its stand-ins in the checkout's .bin/: a later step runs the real git.
    for name in ("git", "gh"):
        (repo / ".bin" / name).unlink()
    shown = body.read_text() if body.exists() else ""
    return Ran(result, output, log.read_text().splitlines(), shown)


def _landed(repo: Path) -> None:
    """The run's push lands: origin/jaws-upgrade is its commit. Back on main, the hub's
    checkout is as the next run's checkout finds it."""
    _git(repo, "update-ref", "refs/remotes/origin/jaws-upgrade", "jaws-upgrade")
    _git(repo, "switch", "-q", "main")


def _main_moves_on(repo: Path) -> None:
    """A merge to main after the upgrade's push: the next run's bump holds another tree than
    jaws-upgrade's."""
    (repo / "docs").mkdir()
    (repo / "docs" / "hub.md").write_text("The platform's hub.\n")
    _git(repo, "add", "docs/hub.md")
    _git(repo, "commit", "-q", "-m", "docs: describe the hub")


# -- the newest release ------------------------------------------------------------------


@needs_jq
def test_a_newer_release_is_found_by_semver_not_text(tmp_path: Path) -> None:
    tags = ["v0.8.0", PIN, TAG, "latest", "v0.10.1-rc1"]
    releases = [tag for tag in tags if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag)]
    assert max(releases) == PIN, "as text, v0.10.0 sorts before v0.9.0"
    ran = _newest(tmp_path, tags)
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert ran.output.splitlines() == [
        "newer=true",
        f"tag={TAG}",
        f"pin={PIN}",
        f"digest={DIGEST}",
    ]
    token, listed, head = ran.calls
    assert token.endswith(f" {ANONYMOUS}"), "an anonymous token, for the base's repository"
    assert listed.endswith(f" {REGISTRY}/tags/list?n=1000")
    assert " -I " in head and head.endswith(f" {REGISTRY}/manifests/{TAG}"), "a HEAD of the tag"
    for call in (listed, head):
        assert "Authorization: Bearer anonymous" in call
    assert f"Accept: {_by_id('newest')['env']['MANIFEST_TYPES']}" in head


@needs_jq
def test_nothing_happens_when_the_pin_is_the_newest(tmp_path: Path) -> None:
    ran = _newest(tmp_path, ["v0.8.0", PIN, "latest", "v0.10.0-rc1"])
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert ran.output.splitlines() == ["newer=false"]
    assert _notices(ran) == [f"::notice::Jaws {PIN} is the newest release"]
    assert len(ran.calls) == 2, "no manifest is read"
    for step_id in ("rewrite", "pull-request"):
        assert _by_id(step_id)["if"] == NEWER_ONLY


@needs_jq
@pytest.mark.parametrize("fail", ["/token/", "/tags/list", "/manifests/"])
def test_a_registry_error_stops_the_upgrade(tmp_path: Path, fail: str) -> None:
    ran = _newest(tmp_path, [PIN, TAG], fail=fail)
    assert ran.result.returncode != 0
    assert ran.output == "", "no tag, nor anything else"
    assert fail in ran.calls[-1], "it stops at the request that failed"
    (error,) = _errors(ran)
    assert "public.ecr.aws" in error


@needs_jq
def test_a_manifest_without_its_digest_stops_the_upgrade(tmp_path: Path) -> None:
    ran = _newest(tmp_path, [PIN, TAG], digest="")
    assert ran.result.returncode != 0
    assert ran.output == ""
    (error,) = _errors(ran)
    assert f"{NAME}:{TAG}" in error


def test_the_upgrade_reads_ecr_public_only(tmp_path: Path) -> None:
    mirror = "registry.example.com/mirror/jaws"
    ran = _newest(tmp_path, [TAG], name=mirror)
    assert ran.result.returncode != 0
    assert ran.result.stdout.splitlines() == [
        f"::error::the upgrade reads ECR Public; this Dockerfile builds FROM {mirror}"
    ]
    assert ran.calls == []
    assert ran.output == ""


def test_the_digest_is_read_with_the_public_image_check_s_types() -> None:
    """Plan 04's Accept types, as `platform-base` holds them too: an index or a manifest."""
    decide = next(
        s
        for s in job("release-please.yml", "public-image-check")["steps"]
        if s.get("id") == "decide"
    )
    assert _by_id("newest")["env"]["MANIFEST_TYPES"] == decide["env"]["MANIFEST_TYPES"]


# -- the bump ----------------------------------------------------------------------------


@needs_jq
def test_one_commit_bumps_the_dockerfile_and_every_jaws_pin(tmp_path: Path) -> None:
    repo = _hub(tmp_path)
    lint = (repo / LINT).read_bytes()
    rewrite = _rewrite(repo)
    assert rewrite.returncode == 0, rewrite.stdout + rewrite.stderr
    script = _by_id("rewrite")["run"].splitlines()
    commands = [line for line in script if not line.lstrip().startswith("#")]
    assert not [line for line in commands if "sed -i" in line], "BSD's sed -i is not GNU's"
    dockerfile = (repo / DOCKERFILE).read_text()
    assert f"FROM {NAME}:{TAG}@{DIGEST}" in dockerfile.splitlines()
    assert dockerfile == HUB[DOCKERFILE].replace(f":{PIN}@{PINNED_DIGEST}", f":{TAG}@{DIGEST}")
    for caller in (SITE_PLAN, UPGRADE_CALLER):
        assert (repo / caller).read_text() == HUB[caller].replace(f".yml@{PIN}", f".yml@{TAG}")
    site_plan = (repo / SITE_PLAN).read_text()
    assert f"uses: Jaws-Platform/jaws/.github/workflows/site-plan.yml@{TAG}" in site_plan
    assert (repo / LINT).read_bytes() == lint, "another repository's workflow, at the same version"
    assert _git(repo, "diff", "--name-only").splitlines() == BUMPED

    opened = _pull_request(repo, [])
    assert opened.result.returncode == 0, opened.result.stdout + opened.result.stderr
    assert _git(repo, "rev-list", "--count", "main..jaws-upgrade") == "1"
    assert _git(repo, "diff", "--name-only", "main", "jaws-upgrade").splitlines() == BUMPED
    made = _git(repo, "log", "-1", "--format=%an <%ae>%n%cn <%ce>%n%s", "jaws-upgrade")
    assert made.splitlines() == [f"{BOT} <{BOT_EMAIL}>", f"{BOT} <{BOT_EMAIL}>", MESSAGE]


@pytest.mark.parametrize(
    ("files", "pin", "named"),
    [
        pytest.param({DOCKERFILE: HUB[DOCKERFILE], LINT: HUB[LINT]}, PIN, "workflow", id="no-call"),
        pytest.param(HUB, "v0.8.0", "Dockerfile", id="another-pin"),
    ],
)
def test_the_rewrite_fails_unless_it_bumps_the_dockerfile_and_a_workflow(
    tmp_path: Path, files: Mapping[str, str], pin: str, named: str
) -> None:
    repo = _hub(tmp_path, files)
    result = _rewrite(repo, pin=pin)
    assert result.returncode != 0
    (error,) = [line for line in result.stdout.splitlines() if line.startswith("::error::")]
    assert named in error and TAG in error


@needs_jq
def test_the_upgrade_commits_only_what_it_bumped(tmp_path: Path) -> None:
    """P5-R31: the tool's checkout is in the hub's workspace, at .jaws-tool/, and a hub's
    .gitignore may not list it. The commit holds the files `rewrite` bumped, never what
    `git add -A` would add."""
    repo = _bumped(tmp_path)
    untracked = [".jaws-tool/.github/actions/platform-base/action.yml", ".github/workflows/x.yml"]
    for name in untracked:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("name: untracked\n")
    opened = _pull_request(repo, [])
    assert opened.result.returncode == 0, opened.result.stdout + opened.result.stderr
    assert _git(repo, "diff", "--name-only", "main", "jaws-upgrade").splitlines() == BUMPED
    status = _git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()
    for name in untracked:
        assert f"?? {name}" in status


# -- the pull request --------------------------------------------------------------------


@needs_jq
def test_the_pull_request_is_opened_once_and_updated_after(tmp_path: Path) -> None:
    repo = _bumped(tmp_path)
    opened = _pull_request(repo, [])
    assert opened.result.returncode == 0, opened.result.stdout + opened.result.stderr
    assert f"gh api users/{BOT}" in opened.calls, "the commit's author, the App's bot"
    assert LISTED in opened.calls
    assert _writes(opened) == [
        "git push --force origin jaws-upgrade",
        f"gh pr create --base main --head jaws-upgrade --title {MESSAGE} --body-file <body>",
    ]
    for named in (PIN, TAG, f"https://github.com/Jaws-Platform/jaws/compare/{PIN}...{TAG}"):
        assert named in opened.body
    said = " ".join(opened.body.split())
    for part in ("one pull request", "the image", "every workflow pin", "the candidate"):
        assert part in said
    assert "every stack and project" in said

    # A later release, while that pull request is open: main still pins PIN.
    _landed(repo)
    assert _rewrite(repo, tag=LATER, digest=LATER_DIGEST).returncode == 0
    updated = _pull_request(repo, [_open(7, MESSAGE)], tag=LATER)
    assert updated.result.returncode == 0, updated.result.stdout + updated.result.stderr
    assert _writes(updated) == [
        "git push --force origin jaws-upgrade",
        f"gh pr edit 7 --title chore(deps): upgrade jaws to {LATER} --body-file <body>",
    ]
    assert f"https://github.com/Jaws-Platform/jaws/compare/{PIN}...{LATER}" in updated.body


@needs_jq
@pytest.mark.parametrize("left", ["named", "same-tree"])
def test_an_open_upgrade_to_the_same_release_is_left_alone(tmp_path: Path, left: str) -> None:
    """A push would run the hub's whole CI again every hour, and drop a fix pushed onto the
    branch. Left alone while the open pull request's title names the release, though main has
    moved on since; or while the branch holds the same tree, though a reviewer retitled it."""
    repo = _bumped(tmp_path)
    assert _pull_request(repo, []).result.returncode == 0
    _landed(repo)
    title = MESSAGE
    if left == "named":
        _main_moves_on(repo)
    else:
        title = "Upgrade Jaws, after reading its plans"
    assert _rewrite(repo).returncode == 0
    again = _pull_request(repo, [_open(7, title)])
    assert again.result.returncode == 0, again.result.stdout + again.result.stderr
    assert _writes(again) == [], "it pushes nothing and edits nothing"
    assert _notices(again) == [f"::notice::the upgrade to {TAG} is open"]
    branches = ("jaws-upgrade", "origin/jaws-upgrade")
    trees = {_git(repo, "rev-parse", f"{branch}^{{tree}}") for branch in branches}
    assert (len(trees) == 1) is (left == "same-tree")


@needs_jq
def test_the_pull_request_is_opened_for_a_branch_already_pushed(tmp_path: Path) -> None:
    """P5-R32: one pull request, on one branch (ruling 12). An earlier run's push landed, but no
    pull request is open, as when its `gh pr create` failed: the pull request is opened now,
    with no push."""
    repo = _bumped(tmp_path)
    assert _pull_request(repo, []).result.returncode == 0
    _landed(repo)
    assert _rewrite(repo).returncode == 0
    again = _pull_request(repo, [])
    assert again.result.returncode == 0, again.result.stdout + again.result.stderr
    assert _writes(again) == [
        f"gh pr create --base main --head jaws-upgrade --title {MESSAGE} --body-file <body>"
    ], "no push: the branch holds the same tree already"
    assert _notices(again) == [
        f"::notice::opened the pull request for the upgrade to {TAG}, already pushed to "
        "jaws-upgrade"
    ]
    assert f"https://github.com/Jaws-Platform/jaws/compare/{PIN}...{TAG}" in again.body
    branches = ("jaws-upgrade", "origin/jaws-upgrade")
    assert len({_git(repo, "rev-parse", f"{branch}^{{tree}}") for branch in branches}) == 1


@needs_jq
@pytest.mark.parametrize("title", [MESSAGE, "Add a feature"], ids=["names-the-release", "other"])
def test_a_fork_s_pull_request_from_a_branch_of_that_name_is_never_the_upgrade(
    tmp_path: Path, title: str
) -> None:
    """gh lists every open pull request whose branch is named jaws-upgrade, a fork's too, and
    any GitHub user can open one. A fork's never holds the upgrade back, and is never retitled
    as the upgrade: the hub's own pull request is opened."""
    repo = _bumped(tmp_path)
    ran = _pull_request(repo, [_open(9, title, fork=True)])
    assert ran.result.returncode == 0, ran.result.stdout + ran.result.stderr
    assert _writes(ran) == [
        "git push --force origin jaws-upgrade",
        f"gh pr create --base main --head jaws-upgrade --title {MESSAGE} --body-file <body>",
    ], "the fork's pull request is never edited"
    assert _notices(ran) == []
    assert LISTED in ran.calls


@needs_jq
def test_the_hub_s_own_pull_request_is_updated_beside_a_fork_s(tmp_path: Path) -> None:
    """The fork's pull request is the newest, so gh lists it first, and its title names the
    later release: the later release still updates the hub's own."""
    repo = _bumped(tmp_path)
    assert _pull_request(repo, []).result.returncode == 0
    _landed(repo)
    assert _rewrite(repo, tag=LATER, digest=LATER_DIGEST).returncode == 0
    later = f"chore(deps): upgrade jaws to {LATER}"
    updated = _pull_request(repo, [_open(9, later, fork=True), _open(7, MESSAGE)], tag=LATER)
    assert updated.result.returncode == 0, updated.result.stdout + updated.result.stderr
    assert _writes(updated) == [
        "git push --force origin jaws-upgrade",
        f"gh pr edit 7 --title {later} --body-file <body>",
    ]


@needs_jq
@pytest.mark.parametrize(
    ("title", "named"),
    [
        (f"{MESSAGE}, fix sites", True),
        (f"Upgrade Jaws ({TAG})", True),
        (f"Upgrade Jaws to {TAG}.", True),
        (f"chore(deps): upgrade jaws to {TAG}1", False),
        (f"chore(deps): upgrade jaws to {TAG}.1", False),
    ],
    ids=["then-a-comma", "in-brackets", "then-a-full-stop", "a-longer-patch", "a-fourth-part"],
)
def test_a_title_names_the_release_only_as_a_whole_version(
    tmp_path: Path, title: str, named: bool
) -> None:
    """A maintainer who retitles the pull request while fixing it keeps the release's tag in
    the title, and the run leaves the branch, with the fix, alone. "v0.10.0, fix sites" and
    "(v0.10.0)" name v0.10.0; v0.10.01 and v0.10.0.1 are other versions, and don't."""
    repo = _bumped(tmp_path)
    assert _pull_request(repo, []).result.returncode == 0
    _landed(repo)
    _main_moves_on(repo)
    assert _rewrite(repo).returncode == 0
    again = _pull_request(repo, [_open(7, title)])
    assert again.result.returncode == 0, again.result.stdout + again.result.stderr
    if named:
        assert _writes(again) == [], "it pushes nothing and edits nothing"
        assert _notices(again) == [f"::notice::the upgrade to {TAG} is open"]
    else:
        assert _writes(again) == [
            "git push --force origin jaws-upgrade",
            f"gh pr edit 7 --title {MESSAGE} --body-file <body>",
        ]
        assert _notices(again) == []


# -- the job -----------------------------------------------------------------------------


def test_the_upgrade_needs_an_app_that_may_change_workflows() -> None:
    call = _workflow()[True]["workflow_call"]
    assert set(call["inputs"]) == {"app-client-id"}
    client = call["inputs"]["app-client-id"]
    assert client["required"] is True
    assert client["type"] == "string"
    assert "vars." in client["description"], "P5-R4: a literal or a vars. value, never a secret"
    assert set(call["secrets"]) == {"app-private-key"}
    assert call["secrets"]["app-private-key"]["required"] is True
    token = _by_id("app-token")
    assert _steps().index(token) == 0
    assert token["uses"] == f"{APP_TOKEN}@v3", "the version every workflow pins"
    assert token["with"] == {
        "client-id": "${{ inputs.app-client-id }}",
        "private-key": "${{ secrets.app-private-key }}",
    }
    assert "continue-on-error" not in token, "GITHUB_TOKEN can't do this job: no fallback"
    assert "if" not in token
    header = _header()
    for permission in ("Contents", "Pull requests", "Workflows"):
        assert f"{permission}: read and write" in header


def test_the_app_s_token_does_every_write() -> None:
    assert _workflow()["permissions"] == {}
    upgrade = job(UPGRADE, JOB)
    assert upgrade["name"] == "Upgrade Jaws"
    assert upgrade["permissions"] == {"contents": "read"}, "the App's token does the writes"
    (hub,) = [s for s in _using(CHECKOUT) if "repository" not in s.get("with", {})]
    assert hub["with"] == {"ref": "main", "fetch-depth": 0, "token": TOKEN}
    assert _by_id("pull-request")["env"]["GH_TOKEN"] == TOKEN
    assert "github.token" not in (WORKFLOWS / UPGRADE).read_text()


def test_the_upgrade_reads_the_from_line_with_platform_base() -> None:
    steps = _steps()
    hub, tool = _using(CHECKOUT)
    assert "repository" not in hub.get("with", {}), "the hub's own checkout comes first"
    assert tool["with"]["path"] == ".jaws-tool"
    base = _by_id("base")
    assert base["uses"] == BASE
    assert base["with"] == {"require-published": "false"}, "P5-R20: it replaces a pruned pin"
    action = yaml.safe_load((ACTIONS / "platform-base" / "action.yml").read_text())
    assert "require-published" in action["inputs"]
    newest = _by_id("newest")
    assert steps.index(hub) < steps.index(tool) < steps.index(base) < steps.index(newest)
    assert newest["env"]["NAME"] == "${{ steps.base.outputs.base-name }}"
    assert newest["env"]["PIN"] == "${{ steps.base.outputs.base-tag }}"


def test_a_bump_takes_the_release_the_newest_step_found() -> None:
    assert [s.get("id") for s in _steps()][-3:] == ["newest", "rewrite", "pull-request"]
    found = {
        "PIN": "${{ steps.newest.outputs.pin }}",
        "TAG": "${{ steps.newest.outputs.tag }}",
    }
    assert _by_id("rewrite")["env"] == {**found, "DIGEST": "${{ steps.newest.outputs.digest }}"}
    assert _by_id("pull-request")["env"] == {
        "GH_TOKEN": TOKEN,
        "GH_REPO": "${{ github.repository }}",
        "APP_SLUG": "${{ steps.app-token.outputs.app-slug }}",
        **found,
    }
    for step_id in ("rewrite", "pull-request"):
        assert _by_id(step_id)["if"] == NEWER_ONLY


def test_every_expression_reaches_a_script_through_env() -> None:
    for step in _steps():
        assert "${{" not in str(step.get("run", "")), step.get("id", step.get("name"))
