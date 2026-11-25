"""One Dockerfile builds two images.

`generic` is Jaws's image, with no configuration inside (spec 6.3). `jaws-cli` adds
`config/` and `datasets/` where the CLI and the platform stacks look. The release builds
`jaws-cli` for a tag that has the stage; a tag cut before it gets its only image.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jaws.settings import IMAGE_CONFIG_PATH
from jaws.stack import IMAGE_PLUGIN_DIR, IMAGE_STACKS_ROOT
from tests.conftest import REPO_ROOT
from tests.workflow_steps import job, run_step, uses

DOCKERFILE = REPO_ROOT / "Dockerfile"
#: A tag cut before the generic image: one stage, config/ baked in (v0.80.1 and earlier).
OLD_DOCKERFILE = 'FROM python:3.13-alpine\nCOPY config /etc/jaws/config\nENTRYPOINT ["jaws"]\n'


def _stages() -> list[tuple[str, list[str]]]:
    """Each stage's FROM line and its instructions, continuation lines joined,
    comments and blank lines dropped."""
    stages: list[tuple[str, list[str]]] = []
    pending = ""
    for raw in DOCKERFILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending = f"{pending} {line[:-1].strip()}".strip()
            continue
        instruction = f"{pending} {line}".strip()
        pending = ""
        if instruction.startswith("FROM "):
            stages.append((instruction, []))
        elif stages:
            stages[-1][1].append(instruction)
    return stages


def _stage(name: str) -> list[str]:
    """The instructions of the stage whose FROM line ends in `AS <name>`."""
    return next(body for line, body in _stages() if line.endswith(f" AS {name}"))


def test_the_default_target_is_the_generic_image() -> None:
    assert _stages()[-1] == ("FROM generic", [])


def test_the_generic_image_holds_no_configuration() -> None:
    assert not [
        i
        for i in _stage("generic")
        if "/etc/jaws" in i or i.split()[:2] in (["COPY", "config"], ["COPY", "datasets"])
    ]


def test_jaws_cli_adds_the_configuration_and_the_datasets_beside_it() -> None:
    """Where the CLI looks (IMAGE_CONFIG_PATH, and jaws.access.infra_root's datasets/)
    and where the foundation looks (local.datasets_path, beside its config_path)."""
    assert "FROM generic AS jaws-cli" in [line for line, _ in _stages()]
    assert _stage("jaws-cli") == [
        f"COPY config {IMAGE_CONFIG_PATH}",
        f"COPY datasets {IMAGE_CONFIG_PATH.parent / 'datasets'}",
    ]


@pytest.mark.parametrize(("dockerfile", "target"), [("current", "jaws-cli"), ("old", "")])
def test_the_jaws_cli_job_builds_jaws_cli_or_an_old_tag_s_only_image(
    tmp_path: Path, dockerfile: str, target: str
) -> None:
    text = DOCKERFILE.read_text() if dockerfile == "current" else OLD_DOCKERFILE
    (tmp_path / "Dockerfile").write_text(text)
    result, output = run_step(
        "release-please.yml", "image", "target", cwd=tmp_path, env={"TAG": "v0.76.0"}
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == [f"target={target}"]
    build = uses(job("release-please.yml", "image"), "docker/build-push-action")
    assert build["with"]["target"] == "${{ steps.target.outputs.target }}"


#: The platform's own stacks, at the repository root; the project stacks are stacks/*.
PLATFORM_STACKS = ("foundation", "monitoring", "data-access")


def test_the_image_ships_every_stack_where_the_cli_looks() -> None:
    build = _stage("build")
    assert f"COPY stacks {IMAGE_STACKS_ROOT}" in build
    assert all(f"COPY {s} {IMAGE_STACKS_ROOT}/{s}" in build for s in PLATFORM_STACKS)
    loops = [i for i in build if i.startswith("RUN for ")]
    assert len(loops) == 1
    assert f"{IMAGE_STACKS_ROOT}/*/" in loops[0]
    assert f"terraform providers mirror {IMAGE_PLUGIN_DIR}" in loops[0]
    project_stacks = {p.name for p in (REPO_ROOT / "stacks").iterdir()}
    assert not set(PLATFORM_STACKS) & project_stacks, (
        "a platform stack would shadow a project stack"
    )


def test_the_build_context_keeps_backends_lock_files_and_stack_tests_out() -> None:
    """backend/prod.hcl names the owner's state bucket, and the stacks' tests/ hold
    fixtures generated from the owner's configuration: neither may reach the public image."""
    ignored = set((REPO_ROOT / ".dockerignore").read_text().split())
    assert {
        "**/backend",
        "**/tests",
        "**/.terraform",
        "**/.terraform.lock.hcl",
        "owner-access",
    } <= ignored
    assert not ignored & {"stacks", *PLATFORM_STACKS, "config", "datasets", "src"}
