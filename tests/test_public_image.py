"""The generic image goes to ECR Public with the publishing role, only from the `publish`
environment, never for a tag cut before it, never over a tag already published, and not at
all until the owner has set the two variables.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.conftest import REPO_ROOT
from tests.test_cli_image import DOCKERFILE, OLD_DOCKERFILE
from tests.test_databricks_workflows import needs_yq
from tests.workflow_steps import WORKFLOWS, job, run_step, uses

NEUTRAL = {
    "ROLE_ARN": "arn:aws:iam::123456789012:role/release-infra-publish",
    "IMAGE": "public.ecr.aws/example-alias/jaws",
    "KEEP": "",
    "TAG": "v0.81.0",
}
#: Stands in for curl: logs each call, answers the token request, and prints
#: FAKE_HTTP_CODE for the manifest request.
FAKE_CURL = """#!/usr/bin/env bash
echo "curl $*" >> "$FAKE_LOG"
case "$*" in
  */token/*) echo '{"token": "anonymous"}' ;;
  *) printf '%s' "$FAKE_HTTP_CODE" ;;
esac
"""
RELEASE = "release-please.yml"
CHECK = "public-image-check"
PUBLIC = "public-image"


def _decide(
    tmp_path: Path, dockerfile: str, code: str = "404", **env: str
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    """Run the check job's decide step in a checkout holding `dockerfile`; the result,
    what it wrote to GITHUB_OUTPUT, and the curl calls it made."""
    (tmp_path / "Dockerfile").write_text(dockerfile)
    log = tmp_path / "curl.log"
    log.write_text("")
    result, output = run_step(
        RELEASE,
        CHECK,
        "decide",
        cwd=tmp_path,
        env={**NEUTRAL, **env, "FAKE_LOG": str(log), "FAKE_HTTP_CODE": code},
        fakes={"curl": FAKE_CURL},
    )
    return result, output, log.read_text()


@needs_yq
def test_a_new_tag_is_published(tmp_path: Path) -> None:
    result, output, calls = _decide(tmp_path, DOCKERFILE.read_text())
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == ["publish=true"]
    assert "scope=repository:example-alias/jaws:pull" in calls
    assert "https://public.ecr.aws/v2/example-alias/jaws/manifests/v0.81.0" in calls


@needs_yq
def test_without_the_variables_publishing_is_skipped_with_a_notice(tmp_path: Path) -> None:
    result, output, calls = _decide(tmp_path, DOCKERFILE.read_text(), ROLE_ARN="", IMAGE="")
    assert result.returncode == 0
    assert "::notice::" in result.stdout and "JAWS_PUBLISH_ROLE_ARN" in result.stdout
    assert output.splitlines() == ["publish=false"] and calls == ""


@needs_yq
@pytest.mark.parametrize(
    ("overrides", "named"),
    [
        ({"IMAGE": ""}, "JAWS_PUBLIC_IMAGE"),
        ({"ROLE_ARN": ""}, "JAWS_PUBLISH_ROLE_ARN"),
        ({"ROLE_ARN": "release-infra-publish"}, "JAWS_PUBLISH_ROLE_ARN"),
        ({"IMAGE": "public.ecr.aws/example-alias/jaws-cli"}, "JAWS_PUBLIC_IMAGE"),
        ({"KEEP": "ten"}, "JAWS_PUBLIC_IMAGE_KEEP"),
    ],
)
def test_a_half_set_or_malformed_variable_fails_the_check(
    tmp_path: Path, overrides: dict[str, str], named: str
) -> None:
    result, output, _ = _decide(tmp_path, DOCKERFILE.read_text(), **overrides)
    assert result.returncode != 0 and f"::error::{named} " in result.stdout and output == ""


@needs_yq
def test_a_tag_without_the_generic_image_is_never_published(tmp_path: Path) -> None:
    result, output, calls = _decide(tmp_path, OLD_DOCKERFILE)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::notice::" in result.stdout and "predates the generic image" in result.stdout
    assert output.splitlines() == ["publish=false"] and calls == ""


@needs_yq
def test_a_published_tag_is_never_replaced(tmp_path: Path) -> None:
    result, output, _ = _decide(tmp_path, DOCKERFILE.read_text(), code="200")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::notice::" in result.stdout and "never replaced" in result.stdout
    assert output.splitlines() == ["publish=false"]


@needs_yq
def test_a_registry_error_stops_the_publish(tmp_path: Path) -> None:
    result, output, _ = _decide(tmp_path, DOCKERFILE.read_text(), code="503")
    assert result.returncode != 0 and "::error::" in result.stdout and output == ""


def test_the_public_image_is_the_generic_target_pushed_under_the_tag() -> None:
    step = uses(job(RELEASE, PUBLIC), "docker/build-push-action")["with"]
    assert step["target"] == "generic"
    assert step["push"] is True
    assert step["platforms"] == "linux/amd64"
    assert step["provenance"] is False
    assert step["tags"] == "${{ env.IMAGE }}:${{ env.TAG }}"


def test_it_is_pushed_with_the_publishing_role_alone() -> None:
    public = job(RELEASE, PUBLIC)
    assert public["environment"]["name"] == "publish"
    assert public["permissions"] == {"contents": "read", "id-token": "write"}
    creds = uses(public, "aws-actions/configure-aws-credentials")["with"]
    assert creds["role-to-assume"] == "${{ vars.JAWS_PUBLISH_ROLE_ARN }}"
    assert creds["aws-region"] == "us-east-1"
    assert uses(public, "aws-actions/amazon-ecr-login")["with"]["registry-type"] == "public"
    assert public["env"]["IMAGE"] == "${{ vars.JAWS_PUBLIC_IMAGE }}"


def test_it_needs_no_configuration_and_no_apply() -> None:
    assert job(RELEASE, PUBLIC)["needs"] == ["release-please", CHECK]
    assert job(RELEASE, CHECK)["needs"] == "release-please"


def test_the_public_job_runs_only_when_the_check_says_so() -> None:
    assert job(RELEASE, PUBLIC)["if"] == (
        "!cancelled() && needs.public-image-check.outputs.publish == 'true'"
    )
    check = job(RELEASE, CHECK)
    assert "environment" not in check
    assert check["permissions"] == {"contents": "read"}
    assert " ".join(check["if"].split()) == " ".join(job(RELEASE, "account")["if"].split())
    assert check["env"] == {
        "TAG": job(RELEASE, "image")["env"]["TAG"],
        "ROLE_ARN": "${{ vars.JAWS_PUBLISH_ROLE_ARN }}",
        "IMAGE": "${{ vars.JAWS_PUBLIC_IMAGE }}",
        "KEEP": "${{ vars.JAWS_PUBLIC_IMAGE_KEEP }}",
    }
    assert check["outputs"] == {"publish": "${{ steps.decide.outputs.publish }}"}


def test_only_the_public_image_job_enters_publish_or_takes_the_publishing_role() -> None:
    publishing: list[tuple[str, str]] = []
    role_users: set[str] = set()
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for name, body in (yaml.safe_load(path.read_text()).get("jobs") or {}).items():
            environment = body.get("environment")
            environment = environment.get("name") if isinstance(environment, dict) else environment
            if environment == "publish":
                publishing.append((path.name, name))
            if "vars.JAWS_PUBLISH_ROLE_ARN" in yaml.safe_dump(body):
                role_users.add(f"{path.name}:{name}")
    assert publishing == [(RELEASE, PUBLIC)]
    assert role_users == {f"{RELEASE}:{CHECK}", f"{RELEASE}:{PUBLIC}"}
    assert not re.search(
        r"JAWS_PUBLISH_ROLE_ARN",
        "".join(p.read_text() for p in WORKFLOWS.glob("*.yml") if p.name != RELEASE),
    )


#: Stands in for aws: logs each call, answers describe-images with FAKE_IMAGES, and
#: answers batch-delete-image with 200 and FAKE_FAILURES (a JSON list; AWS reports what it
#: could not delete there, not as an error).
FAKE_AWS = """#!/usr/bin/env bash
echo "aws $*" >> "$FAKE_LOG"
case "$2" in
  describe-images) cat "$FAKE_IMAGES" ;;
  batch-delete-image) echo "{\\"imageIds\\": [], \\"failures\\": ${FAKE_FAILURES:-[]}}" ;;
  *) echo "unexpected: aws $*" >&2; exit 2 ;;
esac
"""


def _prune_step(
    tmp_path: Path, keep: str = "10", failures: str = "[]", count: int = 12
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the prune step on a repository of `count` versions; the result and the aws calls."""
    shutil.copytree(REPO_ROOT / "scripts", tmp_path / "scripts")
    runner = tmp_path / "runner"
    runner.mkdir()
    fixture = tmp_path / "fixture.json"
    details = [
        {"imageDigest": f"sha256:{minor:064x}", "imageTags": [f"v0.{minor}.0"]}
        for minor in range(1, count + 1)
    ]
    fixture.write_text(json.dumps({"imageDetails": details}))
    log = tmp_path / "aws.log"
    log.write_text("")
    result, _ = run_step(
        RELEASE,
        PUBLIC,
        "prune",
        cwd=tmp_path,
        env={
            "KEEP": keep,
            "TAG": f"v0.{count}.0",
            "RUNNER_TEMP": str(runner),
            "FAKE_LOG": str(log),
            "FAKE_IMAGES": str(fixture),
            "FAKE_FAILURES": failures,
        },
        fakes={"aws": FAKE_AWS},
    )
    return result, log.read_text().splitlines()


def test_each_publish_prunes_the_repository_with_the_push_role() -> None:
    steps = job(RELEASE, PUBLIC)["steps"]
    ids = [step.get("id") for step in steps]
    prune = steps[ids.index("prune")]
    assert ids[-1] == "prune" and ids.index("build") < ids.index("prune")
    assert prune["if"] == "vars.JAWS_PUBLIC_IMAGE_KEEP != 'all'", "all skips the prune"
    assert prune["env"] == {"KEEP": "${{ vars.JAWS_PUBLIC_IMAGE_KEEP || '10' }}"}
    roles = [
        s for s in steps if s.get("uses", "").startswith("aws-actions/configure-aws-credentials")
    ]
    assert len(roles) == 1, "the push role, and no other"


def test_the_prune_step_deletes_what_the_script_selects(tmp_path: Path) -> None:
    result, calls = _prune_step(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    describe, *deletes = calls
    assert describe == (
        "aws ecr-public describe-images --region us-east-1 --repository-name jaws --output json"
    )
    assert len(deletes) == 1 and "--repository-name jaws" in deletes[0]
    assert '"v0.1.0"' in deletes[0] and '"v0.2.0"' in deletes[0] and "v0.3.0" not in deletes[0]


def test_the_prune_step_fails_when_a_delete_reports_a_failure(tmp_path: Path) -> None:
    """BatchDeleteImage answers 200 even when it deleted nothing."""
    failure = '[{"failureCode": "ImageNotFound", "failureReason": "gone"}]'
    result, _ = _prune_step(tmp_path, failures=failure)
    assert result.returncode != 0 and "::error::" in result.stdout + result.stderr


def test_the_prune_step_deletes_nothing_for_a_malformed_keep(tmp_path: Path) -> None:
    result, calls = _prune_step(tmp_path, keep="ten")
    assert result.returncode != 0
    assert not [c for c in calls if "batch-delete-image" in c]
