"""The composite actions a hub's run is built on: `platform-role` and `platform-image`.

`platform-role` builds the role a hub's job assumes from the platform's identity, with no
AWS call, and stops half an identity before the job has any credentials. `platform-image`
resolves the hub image's `current` tag, or a digest another job of the run resolved, to one
build at the job's start, and every later step runs that build by the image ID the runner
reports (spec 6.3). It keeps the build in the Actions cache, so a repository pulls each
build once, and loads a pull request's candidate from this run's artifact without reaching
ECR. Their steps' scripts are run here as Actions runs them, with stand-ins for `aws` and
`docker`.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import FIXTURES, REPO_ROOT
from tests.test_databricks_workflows import needs_yq
from tests.test_github import HUB_COMMIT, HUB_SOURCE
from tests.test_jaws_action import run_command
from tests.workflow_steps import ACTIONS, WORKFLOWS, action_step, run_action_step

ACCOUNT = "123456789012"
OTHER_ACCOUNT = "111122223333"
REGISTRY = f"{ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com"
REPOSITORY = "jaws-platform"
#: The build's manifest digest, its config digest, and an image ID that is neither.
DIGEST = "sha256:" + "b" * 64
CONFIG_DIGEST = "sha256:" + "c" * 64
OTHER_ID = "sha256:" + "d" * 64
REFERENCE = f"{REGISTRY}/{REPOSITORY}@{DIGEST}"
#: Where the build's `docker save` is cached, and where this run's artifact lands.
TARBALL = "${{ runner.temp }}/platform-image/platform-image.tar"
#: The ID every step after `load` runs the build by.
IMAGE_ID = "${{ steps.load.outputs.image-id || inputs.image-id }}"

#: Stands in for aws: logs each call, answers `sts get-caller-identity` with FAKE_ACCOUNT,
#: and `ecr batch-get-image` with the file FAKE_IMAGES.
FAKE_AWS = """#!/usr/bin/env bash
echo "aws $*" >> "$FAKE_LOG"
case "$1 $2" in
  "sts get-caller-identity") echo "$FAKE_ACCOUNT" ;;
  "ecr batch-get-image") cat "$FAKE_IMAGES" ;;
  *) echo "unexpected: aws $*" >&2; exit 2 ;;
esac
"""
#: Stands in for docker: logs each call. `load` reports FAKE_LOADED, by ID or by name, or
#: nothing when it is empty, and fails with FAKE_LOAD_ERROR when that is set.
#: `image inspect` answers an image ID with itself, a name with FAKE_ID (the ID the
#: runner's image store gives the build), no name with an error, as Docker does, and the
#: labels with FAKE_LABELS.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
case "$*" in
  "load "*)
    if [[ -n "${FAKE_LOAD_ERROR:-}" ]]; then echo "$FAKE_LOAD_ERROR" >&2; exit 1; fi
    case "$FAKE_LOADED" in
      "") ;;
      sha256:*) echo "Loaded image ID: $FAKE_LOADED" ;;
      *) echo "Loaded image: $FAKE_LOADED" ;;
    esac ;;
  "image inspect --format {{.Id}} ") echo "Error: No such image: " >&2; exit 1 ;;
  "image inspect --format {{.Id}} sha256:"*) echo "$5" ;;
  "image inspect --format {{.Id}} "*) echo "$FAKE_ID" ;;
  "image inspect --format {{json .Config.Labels}} "*) echo "$FAKE_LABELS" ;;
  "create "*) echo fake-container ;;
  "pull "* | "save "* | "cp "* | "rm "*) ;;
  *) echo "unexpected: docker $*" >&2; exit 2 ;;
esac
"""

#: batch-get-image's answer for a build: its manifest digest, and the manifest itself,
#: which names the build's config digest.
FOUND: Mapping[str, Any] = {
    "images": [
        {
            "registryId": ACCOUNT,
            "repositoryName": REPOSITORY,
            "imageId": {"imageDigest": DIGEST, "imageTag": "current"},
            "imageManifestMediaType": "application/vnd.oci.image.manifest.v1+json",
            "imageManifest": json.dumps(
                {
                    "schemaVersion": 2,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "config": {
                        "mediaType": "application/vnd.oci.image.config.v1+json",
                        "digest": CONFIG_DIGEST,
                        "size": 7023,
                    },
                    "layers": [],
                }
            ),
        }
    ],
    "failures": [],
}
#: Its answer when no build has the tag: no image, and a failure rather than an error.
NOT_FOUND: Mapping[str, Any] = {
    "images": [],
    "failures": [
        {
            "imageId": {"imageTag": "current"},
            "failureCode": "ImageNotFound",
            "failureReason": "Requested image not found",
        }
    ],
}
#: The labels a hub's build carries: the hub commit and repository, and its Jaws base.
LABELS = {
    "org.opencontainers.image.revision": HUB_COMMIT,
    "org.opencontainers.image.source": HUB_SOURCE,
    "org.opencontainers.image.base.name": "public.ecr.aws/example-alias/jaws:v0.81.0",
    "org.opencontainers.image.base.digest": "sha256:" + "a" * 64,
}
#: The resolve step's environment: a build tagged `current`.
RESOLVE = {"REGISTRY": REGISTRY, "REPOSITORY": REPOSITORY, "TAG": "current", "DIGEST": ""}


def _action(name: str) -> dict[str, Any]:
    action: dict[str, Any] = yaml.safe_load((ACTIONS / name / "action.yml").read_text())
    return action


# -- platform-role --------------------------------------------------------------------

#: The platform's identity as a hub's caller spells it, for a plan role whose project
#: comes from the project file.
IDENTITY = {
    "PLATFORM_IMAGE": REPOSITORY,
    "ACCOUNT_ID": ACCOUNT,
    "NAME_ROOT": "jaws",
    "ROLE": "plan",
    "PROJECT": "",
    "PROJECT_FILE": "jaws.yaml",
    "ROLE_ARN": "",
}


#: A project file naming guitar-knowledge-base.
GUITAR_KNOWLEDGE_BASE = (FIXTURES / "sites" / "guitar-knowledge-base.yaml").read_text()


def _role(
    tmp_path: Path, jaws_yaml: str | None = GUITAR_KNOWLEDGE_BASE, /, **env: str
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    """Run platform-role's `arn` beside a jaws.yaml holding `jaws_yaml`, or none; the
    result, GITHUB_OUTPUT and the aws calls it made."""
    if jaws_yaml is not None:
        (tmp_path / "jaws.yaml").write_text(jaws_yaml)
    log = tmp_path / "aws.log"
    log.write_text("")
    result, output = run_action_step(
        "platform-role",
        "arn",
        cwd=tmp_path,
        env={**IDENTITY, **env, "FAKE_LOG": str(log), "FAKE_ACCOUNT": ACCOUNT},
        fakes={"aws": FAKE_AWS},
    )
    return result, output, log.read_text()


@needs_yq
def test_the_role_comes_from_the_identity_and_the_project_file(tmp_path: Path) -> None:
    action = _action("platform-role")
    inputs = action["inputs"]
    assert {name for name, spec in inputs.items() if spec.get("required")} == {
        "platform-image",
        "account-id",
        "name-root",
        "role",
    }
    assert {name: inputs[name]["default"] for name in ("project", "project-file", "role-arn")} == {
        "project": "",
        "project-file": "jaws.yaml",
        "role-arn": "",
    }
    assert [step["id"] for step in action["runs"]["steps"]] == ["arn"], "one step, no AWS"
    assert action_step("platform-role", "arn")["env"] == {
        "PLATFORM_IMAGE": "${{ inputs.platform-image }}",
        "ACCOUNT_ID": "${{ inputs.account-id }}",
        "NAME_ROOT": "${{ inputs.name-root }}",
        "ROLE": "${{ inputs.role }}",
        "PROJECT": "${{ inputs.project }}",
        "PROJECT_FILE": "${{ inputs.project-file }}",
        "ROLE_ARN": "${{ inputs.role-arn }}",
    }
    assert action["outputs"]["arn"]["value"] == "${{ steps.arn.outputs.arn }}"

    result, output, aws = _role(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == [
        "arn=arn:aws:iam::123456789012:role/jaws-guitar-knowledge-base-ci-plan"
    ]
    assert aws == "", "the role is built, never looked up"


@pytest.mark.parametrize(
    ("env", "arn"),
    [
        ({"PROJECT": "site"}, "arn:aws:iam::123456789012:role/jaws-site-ci-plan"),
        (
            {"ROLE": "release", "PROJECT": "braveheart"},
            "arn:aws:iam::123456789012:role/jaws-braveheart-ci-release",
        ),
        (
            {"ROLE_ARN": "arn:aws:iam::123456789012:role/jaws-site-ci-plan"},
            "arn:aws:iam::123456789012:role/jaws-site-ci-plan",
        ),
    ],
    ids=["a-given-project", "another-role", "an-override-in-the-account"],
)
def test_a_given_project_or_an_override_in_the_account_names_the_role(
    tmp_path: Path, env: dict[str, str], arn: str
) -> None:
    """A given project, or an override in `account-id`, names the role, and the project file
    is never read: there is none here."""
    result, output, aws = _role(tmp_path, None, **env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == [f"arn={arn}"]
    assert aws == ""


@pytest.mark.parametrize(
    ("name", "env"),
    [
        pytest.param("platform-image", {"PLATFORM_IMAGE": ""}, id="no-platform-image"),
        pytest.param("account-id", {"ACCOUNT_ID": ""}, id="no-account"),
        pytest.param("account-id", {"ACCOUNT_ID": "12345678901"}, id="eleven-digits"),
        pytest.param("name-root", {"NAME_ROOT": "Jaws"}, id="a-name-root-in-capitals"),
        pytest.param("role", {"ROLE": "admin"}, id="an-unknown-role"),
        pytest.param("project", {"PROJECT": "Not_Kebab"}, id="a-project-not-kebab-case"),
        pytest.param(
            "project",
            {
                "PROJECT": "Not_Kebab",
                "ROLE_ARN": "arn:aws:iam::123456789012:role/jaws-site-ci-plan",
            },
            id="a-project-not-kebab-case-beside-an-override",
        ),
        pytest.param(
            "role-arn",
            {"ROLE_ARN": "arn:aws:iam::111122223333:role/jaws-site-ci-plan"},
            id="an-override-in-another-account",
        ),
    ],
)
def test_half_an_identity_stops_the_job_before_aws(
    tmp_path: Path, name: str, env: dict[str, str]
) -> None:
    result, output, aws = _role(tmp_path, **env)
    assert result.returncode != 0
    assert f"::error::{name} " in result.stdout, result.stdout
    assert output == ""
    assert aws == ""


@needs_yq
@pytest.mark.parametrize(
    ("jaws_yaml", "message"),
    [
        pytest.param(
            None,
            "::error::project-file jaws.yaml does not exist, and no project is given",
            id="no-project-file",
        ),
        pytest.param(
            "version: 1\nproject: Not_Kebab\n",
            "::error::project-file jaws.yaml names a project that is not lowercase kebab-case",
            id="a-project-not-kebab-case",
        ),
        pytest.param(
            "version: 1\ndomain: guitar.example.com\n",
            "::error::project-file jaws.yaml names no project",
            id="no-project-key",
        ),
    ],
)
def test_a_project_file_that_names_no_valid_project_stops_the_job_before_aws(
    tmp_path: Path, jaws_yaml: str | None, message: str
) -> None:
    """The project from the workspace's jaws.yaml, which a pull request can change, becomes
    part of the role ARN. The refusal names the file, never the value it holds."""
    result, output, aws = _role(tmp_path, jaws_yaml)
    assert result.returncode != 0
    assert result.stdout.splitlines() == [message]
    assert output == ""
    assert aws == ""


# -- platform-image -------------------------------------------------------------------


def _image_step(
    tmp_path: Path, step_id: str, images: Mapping[str, Any] = FOUND, /, **env: str
) -> tuple[subprocess.CompletedProcess[str], str, list[str]]:
    """Run platform-image's step `step_id` with stand-ins for aws and docker; the result,
    GITHUB_OUTPUT and the calls they logged. `env` is the step's environment, over a role
    in the account, a registry that answers `images`, and a runner that reports the config
    digest."""
    log = tmp_path / "calls.log"
    log.write_text("")
    answer = tmp_path / "images.json"
    answer.write_text(json.dumps(images))
    result, output = run_action_step(
        "platform-image",
        step_id,
        cwd=tmp_path,
        env={
            "FAKE_LOG": str(log),
            "FAKE_IMAGES": str(answer),
            "FAKE_ACCOUNT": ACCOUNT,
            "FAKE_LOADED": CONFIG_DIGEST,
            "FAKE_ID": CONFIG_DIGEST,
            "FAKE_LABELS": json.dumps(LABELS),
            **env,
        },
        fakes={"aws": FAKE_AWS, "docker": FAKE_DOCKER},
    )
    return result, output, log.read_text().splitlines()


def _tarball(tmp_path: Path) -> Path:
    """A build's `docker save`, as the cache restores it or the artifact downloads it."""
    tarball = tmp_path / "temp" / "platform-image" / "platform-image.tar"
    tarball.parent.mkdir(parents=True)
    tarball.write_text("a saved build")
    return tarball


def _load(tarball: Path) -> dict[str, str]:
    """The load step's environment: the resolved build, and where its cached copy is."""
    return {
        "TARBALL": str(tarball),
        "REFERENCE": REFERENCE,
        "DIGEST": DIGEST,
        "CONFIG_DIGEST": CONFIG_DIGEST,
        "CACHE_KEY": f"platform-image-{CONFIG_DIGEST}",
    }


@needs_yq
def test_current_is_resolved_to_one_build(tmp_path: Path) -> None:
    inputs = _action("platform-image")["inputs"]
    assert {name: spec.get("default") for name, spec in inputs.items()} == {
        "account-id": "",
        "repository": "",
        "tag": "current",
        "digest": "",
        "artifact": "",
        "image-id": "",
        "extract": "",
    }
    assert action_step("platform-image", "resolve")["env"] == {
        "REGISTRY": "${{ steps.ecr.outputs.registry }}",
        "REPOSITORY": "${{ inputs.repository }}",
        "TAG": "${{ inputs.tag }}",
        "DIGEST": "${{ inputs.digest }}",
    }
    result, output, calls = _image_step(tmp_path, "resolve", **RESOLVE)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == [
        f"digest={DIGEST}",
        f"config-digest={CONFIG_DIGEST}",
        f"reference={REFERENCE}",
    ]
    assert len(calls) == 1, calls
    assert calls[0].startswith("aws ecr batch-get-image ")
    assert f"--repository-name {REPOSITORY} " in calls[0]
    assert "--image-ids imageTag=current" in calls[0]


@needs_yq
def test_a_digest_another_job_resolved_is_used_as_given(tmp_path: Path) -> None:
    result, output, calls = _image_step(tmp_path, "resolve", **{**RESOLVE, "DIGEST": DIGEST})
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(calls) == 1, calls
    assert f"--image-ids imageDigest={DIGEST}" in calls[0]
    assert "imageTag" not in calls[0]
    assert output.splitlines() == [
        f"digest={DIGEST}",
        f"config-digest={CONFIG_DIGEST}",
        f"reference={REFERENCE}",
    ]


@pytest.mark.parametrize(
    ("name", "env"),
    [
        pytest.param("repository", {"REPOSITORY": ""}, id="no-repository"),
        pytest.param("digest", {"DIGEST": "sha256:bbb"}, id="a-digest-that-is-not-one"),
        pytest.param("tag", {"TAG": ""}, id="no-tag"),
    ],
)
def test_a_build_is_resolved_only_by_a_tag_or_a_digest(
    tmp_path: Path, name: str, env: dict[str, str]
) -> None:
    result, output, calls = _image_step(tmp_path, "resolve", **{**RESOLVE, **env})
    assert result.returncode != 0
    assert f"::error::{name} " in result.stdout, result.stdout
    assert output == ""
    assert calls == [], "nothing reaches AWS"


@pytest.mark.parametrize("account_id", ["", "12345678901"], ids=["no-account", "eleven-digits"])
def test_an_account_id_that_is_not_an_account_stops_the_job_before_aws(
    tmp_path: Path, account_id: str
) -> None:
    result, output, calls = _image_step(tmp_path, "account", ACCOUNT_ID=account_id)
    assert result.returncode != 0
    assert "::error::account-id " in result.stdout, result.stdout
    assert output == ""
    assert calls == [], "nothing reaches AWS"


@needs_yq
@pytest.mark.parametrize(
    ("tag", "message"),
    [
        (
            "current",
            "jaws-platform:current does not exist: the hub's first release tags its build current",
        ),
        (f"sha-{HUB_COMMIT}", f"jaws-platform:sha-{HUB_COMMIT} does not exist"),
    ],
    ids=["current", "a-release-s-tag"],
)
def test_no_build_tagged_current_stops_the_job(tmp_path: Path, tag: str, message: str) -> None:
    result, output, _ = _image_step(tmp_path, "resolve", NOT_FOUND, **{**RESOLVE, "TAG": tag})
    assert result.returncode != 0
    assert f"::error::{message}" in result.stdout.splitlines(), result.stdout
    assert output == ""


@needs_yq
def test_a_build_the_registry_can_t_read_is_not_said_to_be_missing(tmp_path: Path) -> None:
    unreadable = {
        "images": [],
        "failures": [
            {
                "imageId": {"imageTag": "current"},
                "failureCode": "KmsError",
                "failureReason": "the repository's key is disabled",
            }
        ],
    }
    result, output, _ = _image_step(tmp_path, "resolve", unreadable, **RESOLVE)
    assert result.returncode != 0
    assert (
        "::error::jaws-platform:current could not be read: KmsError "
        "(the repository's key is disabled)"
    ) in result.stdout.splitlines(), result.stdout
    assert "does not exist" not in result.stdout
    assert output == ""


def test_a_role_in_another_account_stops_the_pull(tmp_path: Path) -> None:
    steps = _action("platform-image")["runs"]["steps"]
    ids = [step["id"] for step in steps]
    assert str(steps[ids.index("ecr")]["uses"]).startswith("aws-actions/amazon-ecr-login@")
    assert ids.index("account") < min(ids.index(i) for i in ("resolve", "cache", "load", "save"))
    assert action_step("platform-image", "account")["env"] == {
        "ACCOUNT_ID": "${{ inputs.account-id }}"
    }
    # A failed step skips every later one, unless a later one asks to run anyway.
    for step in steps[ids.index("account") + 1 :]:
        condition = str(step.get("if", ""))
        assert "always()" not in condition and "failure()" not in condition, step["id"]

    result, output, calls = _image_step(
        tmp_path, "account", ACCOUNT_ID=ACCOUNT, FAKE_ACCOUNT=OTHER_ACCOUNT
    )
    assert result.returncode != 0
    assert "::error::" in result.stdout and OTHER_ACCOUNT in result.stdout, result.stdout
    assert calls == ["aws sts get-caller-identity --query Account --output text"]
    assert output == ""

    result, _, _ = _image_step(tmp_path, "account", ACCOUNT_ID=ACCOUNT)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("loaded", "store_id", "store"),
    [
        (CONFIG_DIGEST, CONFIG_DIGEST, "Docker's classic image store"),
        (REFERENCE, DIGEST, "the containerd image store"),
    ],
    ids=["classic", "containerd"],
)
def test_a_cached_build_is_loaded_in_either_image_store(
    tmp_path: Path, loaded: str, store_id: str, store: str
) -> None:
    """Docker's classic image store reports a build's config digest as its ID, and the
    containerd store its manifest digest. The cache is saved under the ID the runner
    reports, and restored under either."""
    cache = action_step("platform-image", "cache")
    save = action_step("platform-image", "save")
    assert str(cache["uses"]).startswith("actions/cache/restore@v")
    assert str(save["uses"]).startswith("actions/cache/save@v")
    assert cache["uses"].split("@")[1] == save["uses"].split("@")[1], "one actions/cache"
    assert cache["with"] == {
        "path": TARBALL,
        "key": "platform-image-${{ steps.resolve.outputs.config-digest }}",
        "restore-keys": "platform-image-${{ steps.resolve.outputs.digest }}",
    }
    assert save["with"] == {
        "path": TARBALL,
        "key": "platform-image-${{ steps.load.outputs.image-id }}",
    }
    assert save["if"] == "inputs.artifact == '' && steps.load.outputs.pulled == 'true'"
    assert action_step("platform-image", "load")["env"] == {
        "TARBALL": TARBALL,
        "REFERENCE": "${{ steps.resolve.outputs.reference }}",
        "DIGEST": "${{ steps.resolve.outputs.digest }}",
        "CONFIG_DIGEST": "${{ steps.resolve.outputs.config-digest }}",
        "CACHE_KEY": "${{ steps.cache.outputs.cache-matched-key }}",
    }

    tarball = _tarball(tmp_path)
    result, output, calls = _image_step(
        tmp_path, "load", **_load(tarball), FAKE_LOADED=loaded, FAKE_ID=store_id
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == [f"image-id={store_id}"]
    assert calls[0] == f"docker load --quiet --input {tarball}"
    assert not any(call.startswith(("docker pull", "docker save")) for call in calls), calls
    log = result.stdout
    assert store_id in log and DIGEST in log and CONFIG_DIGEST in log, "the ID, with both digests"
    assert store in log, "the log names the runner's image store"


def test_a_cached_build_with_another_id_is_pulled_again(tmp_path: Path) -> None:
    tarball = _tarball(tmp_path)
    result, output, calls = _image_step(tmp_path, "load", **_load(tarball), FAKE_LOADED=OTHER_ID)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls[0] == f"docker load --quiet --input {tarball}"
    pulls = [call for call in calls if call.startswith("docker pull ")]
    saves = [call for call in calls if call.startswith("docker save ")]
    assert pulls == [f"docker pull --quiet {REFERENCE}"]
    assert saves == [f"docker save --output {tarball} {CONFIG_DIGEST}"]
    assert calls.index(pulls[0]) < calls.index(saves[0])
    assert output.splitlines() == ["pulled=true", f"image-id={CONFIG_DIGEST}"]
    warnings = [line for line in result.stdout.splitlines() if line.startswith("::warning::")]
    assert warnings == [
        f"::warning::the cache entry platform-image-{CONFIG_DIGEST} holds {OTHER_ID}, "
        "not this build: pulling it"
    ]


@pytest.mark.parametrize(
    "fault",
    [
        {"FAKE_LOAD_ERROR": "archive/tar: invalid tar header in a saved build"},
        {"FAKE_LOADED": ""},
    ],
    ids=["docker-load-fails", "it-loads-no-image"],
)
def test_a_cache_entry_that_won_t_load_is_pulled_again(
    tmp_path: Path, fault: dict[str, str]
) -> None:
    """A bad cache entry is an entry to replace, not a run to fail: it would fail every run
    of the build until the next release, the sweep's included. The warning names the key,
    and nothing from the entry or from Docker's answer about it."""
    tarball = _tarball(tmp_path)
    result, output, calls = _image_step(tmp_path, "load", **_load(tarball), **fault)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls[0] == f"docker load --quiet --input {tarball}"
    assert f"docker pull --quiet {REFERENCE}" in calls
    assert f"docker save --output {tarball} {CONFIG_DIGEST}" in calls
    assert output.splitlines() == ["pulled=true", f"image-id={CONFIG_DIGEST}"]
    warnings = [line for line in result.stdout.splitlines() if line.startswith("::warning::")]
    assert warnings == [
        f"::warning::the cache entry platform-image-{CONFIG_DIGEST} did not load: pulling the build"
    ]
    printed = result.stdout + result.stderr
    assert "a saved build" not in printed and "No such image" not in printed


def test_a_build_the_cache_does_not_hold_is_pulled_and_saved(tmp_path: Path) -> None:
    tarball = tmp_path / "temp" / "platform-image" / "platform-image.tar"
    result, output, calls = _image_step(tmp_path, "load", **_load(tarball))
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [
        f"docker pull --quiet {REFERENCE}",
        f"docker image inspect --format {{{{.Id}}}} {REFERENCE}",
        f"docker save --output {tarball} {CONFIG_DIGEST}",
    ]
    assert tarball.parent.is_dir(), "the save has a directory to write to"
    assert output.splitlines() == ["pulled=true", f"image-id={CONFIG_DIGEST}"]


def test_a_runner_that_reports_neither_digest_is_warned_of(tmp_path: Path) -> None:
    """The pull is by digest, so the build is this one, but the cache, looked up under the
    two digests, would never restore it: every run would pull."""
    tarball = tmp_path / "temp" / "platform-image" / "platform-image.tar"
    result, output, _ = _image_step(tmp_path, "load", **_load(tarball), FAKE_ID=OTHER_ID)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == ["pulled=true", f"image-id={OTHER_ID}"]
    warnings = [line for line in result.stdout.splitlines() if line.startswith("::warning::")]
    assert len(warnings) == 1 and OTHER_ID in warnings[0], result.stdout


@pytest.mark.parametrize("loaded", [CONFIG_DIGEST, OTHER_ID], ids=["the-candidate", "another"])
def test_the_candidate_is_loaded_from_this_run_s_artifact(tmp_path: Path, loaded: str) -> None:
    steps = _action("platform-image")["runs"]["steps"]
    ids = [step["id"] for step in steps]
    download = steps[ids.index("artifact") - 1]
    assert str(download["uses"]).startswith("actions/download-artifact@v")
    assert download["if"] == "inputs.artifact != ''"
    assert download["with"] == {
        "name": "${{ inputs.artifact }}",
        "path": "${{ runner.temp }}/platform-image",
    }
    assert action_step("platform-image", "artifact")["env"] == {
        "ARTIFACT": "${{ inputs.artifact }}",
        "IMAGE_ID": "${{ inputs.image-id }}",
        "TARBALL": TARBALL,
    }

    tarball = _tarball(tmp_path)
    result, output, calls = _image_step(
        tmp_path,
        "artifact",
        ARTIFACT="platform-image",
        IMAGE_ID=CONFIG_DIGEST,
        TARBALL=str(tarball),
        FAKE_LOADED=loaded,
    )
    assert calls[0] == f"docker load --quiet --input {tarball}"
    assert not any(call.startswith("docker pull") for call in calls), calls
    if loaded == CONFIG_DIGEST:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert (
            f"::error::the platform-image artifact holds {OTHER_ID}, not the candidate "
            f"{CONFIG_DIGEST}"
        ) in result.stdout.splitlines(), result.stdout
    assert output == ""


def test_an_artifact_without_the_candidate_s_id_is_refused(tmp_path: Path) -> None:
    tarball = _tarball(tmp_path)
    result, output, calls = _image_step(
        tmp_path, "artifact", ARTIFACT="platform-image", IMAGE_ID="", TARBALL=str(tarball)
    )
    assert result.returncode != 0
    assert "::error::image-id " in result.stdout, result.stdout
    assert calls == []
    assert output == ""


def test_the_configuration_is_copied_out_of_the_build(tmp_path: Path) -> None:
    outputs = _action("platform-image")["outputs"]
    assert outputs["config"]["value"] == "${{ steps.extract.outputs.config }}"
    assert outputs["infra-root"]["value"] == "${{ steps.extract.outputs.infra-root }}"
    extract = action_step("platform-image", "extract")
    assert extract["if"] == "inputs.extract != ''"
    assert extract["env"] == {"IMAGE_ID": IMAGE_ID, "EXTRACT": "${{ inputs.extract }}"}

    result, output, calls = _image_step(
        tmp_path, "extract", IMAGE_ID=CONFIG_DIGEST, EXTRACT=".jaws-platform"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [
        f"docker create {CONFIG_DIGEST}",
        "docker cp fake-container:/etc/jaws/config .jaws-platform/config",
        "docker cp fake-container:/etc/jaws/datasets .jaws-platform/datasets",
        "docker rm fake-container",
    ]
    assert output.splitlines() == ["config=.jaws-platform/config", "infra-root=.jaws-platform"]


def test_the_configuration_is_never_copied_into_a_directory_that_holds_one(
    tmp_path: Path,
) -> None:
    """`docker cp` copies a directory into a destination that exists, so the CLI would read
    what was there before, with the build's copy nested inside it."""
    (tmp_path / ".jaws-platform" / "config").mkdir(parents=True)
    result, output, calls = _image_step(
        tmp_path, "extract", IMAGE_ID=CONFIG_DIGEST, EXTRACT=".jaws-platform"
    )
    assert result.returncode != 0
    assert "::error::extract " in result.stdout, result.stdout
    assert calls == []
    assert output == ""


@needs_yq
@pytest.mark.parametrize(
    ("labels", "commit", "source"),
    [(LABELS, HUB_COMMIT, HUB_SOURCE), (None, "", "")],
    ids=["labelled", "unlabelled"],
)
def test_the_labels_name_the_platform_s_commit(
    tmp_path: Path, labels: dict[str, str] | None, commit: str, source: str
) -> None:
    outputs = _action("platform-image")["outputs"]
    assert outputs["platform-commit"]["value"] == "${{ steps.labels.outputs.platform-commit }}"
    assert outputs["platform-source"]["value"] == "${{ steps.labels.outputs.platform-source }}"
    assert action_step("platform-image", "labels")["env"] == {"IMAGE_ID": IMAGE_ID}

    result, output, calls = _image_step(
        tmp_path, "labels", IMAGE_ID=CONFIG_DIGEST, FAKE_LABELS=json.dumps(labels)
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [f"docker image inspect --format {{{{json .Config.Labels}}}} {CONFIG_DIGEST}"]
    assert output.splitlines() == [f"platform-commit={commit}", f"platform-source={source}"]


#: The steps that run for a build from the registry, for this run's candidate, and for both.
REGISTRY_STEPS = {"ecr", "account", "resolve", "cache", "load", "save"}
ARTIFACT_STEPS = {"download", "artifact"}
BOTH = {"extract", "labels"}


@pytest.mark.parametrize(
    ("mode", "skipped", "runs"),
    [
        ("inputs.artifact == ''", "inputs.artifact != ''", REGISTRY_STEPS),
        ("inputs.artifact != ''", "inputs.artifact == ''", ARTIFACT_STEPS),
    ],
    ids=["registry", "artifact"],
)
def test_the_build_is_resolved_once_and_run_by_its_id(
    tmp_path: Path, mode: str, skipped: str, runs: set[str]
) -> None:
    """The artifact's steps are its download and `artifact`, which loads it."""
    action = _action("platform-image")
    outputs = {name: spec["value"] for name, spec in action["outputs"].items()}
    assert outputs["image-id"] == IMAGE_ID
    assert outputs["digest"] == "${{ steps.resolve.outputs.digest }}"
    assert outputs["reference"] == "${{ steps.resolve.outputs.reference }}"

    steps = action["runs"]["steps"]
    assert {step["id"] for step in steps} == REGISTRY_STEPS | ARTIFACT_STEPS | BOTH
    for step in steps:
        condition = str(step.get("if", ""))
        if step["id"] in BOTH:
            assert "inputs.artifact" not in condition, step["id"]
        elif step["id"] in runs:
            assert condition == mode or condition.startswith(f"{mode} && "), step["id"]
        else:
            assert condition == skipped or condition.startswith(f"{skipped} && "), step["id"]

    # One step reads the registry, and every step after it runs the build by its ID.
    assert sum("batch-get-image" in str(step.get("run", "")) for step in steps) == 1
    for step_id in ("extract", "labels"):
        assert action_step("platform-image", step_id)["env"]["IMAGE_ID"] == IMAGE_ID

    # The jaws action, given that ID, runs it and pulls nothing, not even implicitly.
    result, calls = run_command(tmp_path, IMAGE=CONFIG_DIGEST, REGISTRY="", REPOSITORY="")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(calls) == 1 and calls[0].startswith("docker run "), calls
    assert " --pull never " in calls[0]
    assert calls[0].endswith(f" {CONFIG_DIGEST} plan")


#: Names the name root derives. A hub's workflow reads each from the configuration in the
#: image, or builds it from the identity inputs; the image's own paths, /etc/jaws and
#: /opt/jaws, are Jaws's (spec 6.7).
DERIVED_NAMES = (
    ".context.name_root",
    "/jaws/databricks/",
    "/jaws/monitoring/",
    "jaws-infra-ci-",
    "jaws-monitoring-ci-",
    "jaws-data-access-ci-",
)


def test_no_hub_workflow_or_action_spells_a_name_the_root_derives() -> None:
    files = sorted([*WORKFLOWS.glob("platform-*.yml"), *ACTIONS.glob("platform-*/action.yml")])
    actions = {path.parent.name for path in files if path.name == "action.yml"}
    assert {"platform-role", "platform-image"} <= actions
    for path in files:
        text = path.read_text()
        for name in DERIVED_NAMES:
            assert name not in text, f"{path.relative_to(REPO_ROOT)} spells {name}"
