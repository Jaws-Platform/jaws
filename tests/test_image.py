"""Building, smoke-testing and pushing the lichess-bot image."""

from __future__ import annotations

import base64
import logging
import stat
from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

from jaws import image
from jaws.errors import PreflightError, RunError
from jaws.project import Project

REGISTRY = "123456789012.dkr.ecr.us-east-1.amazonaws.com"


@pytest.fixture
def binary(tmp_path: Path) -> Path:
    path = tmp_path / "dl" / "braveheart"
    path.parent.mkdir()
    path.write_bytes(b"\x7fELF")
    path.chmod(0o755)
    return path


def test_local_and_remote_tags(bot: Project) -> None:
    assert image.local_tag(bot, "v0.14.0") == "jwall-engineering-braveheart:v0.14.0"
    assert image.remote_tag(bot, REGISTRY, "v0.14.0") == (
        f"{REGISTRY}/jwall-engineering-braveheart:v0.14.0"
    )


def test_prepare_context_layout(bot: Project, binary: Path, bot_workspace: Path) -> None:
    context = image.prepare_context(bot, "v0.14.0", binary, bot_workspace / "ctx", bot_workspace)
    assert sorted(p.name for p in context.iterdir()) == [
        "Dockerfile",
        "config.yml",
        "engine",
        "entrypoint.py",
    ]
    engine = context / "engine" / "braveheart"
    assert engine.read_bytes() == b"\x7fELF"
    assert engine.stat().st_mode & stat.S_IXUSR
    assert "LICHESS_TOKEN_PLACEHOLDER" in (context / "config.yml").read_text()
    assert "afa430da25cb6d506c878d3ca2fa155be8da625d" in (context / "Dockerfile").read_text()


def test_prepare_context_uses_consumer_dockerfile(
    bot: Project, binary: Path, bot_workspace: Path
) -> None:
    (bot_workspace / "docker").mkdir()
    (bot_workspace / "docker" / "Dockerfile").write_text("FROM scratch\n")
    custom = bot.model_copy(
        update={
            "config": bot.config.model_copy(
                update={
                    "components": (
                        bot.image.model_copy(update={"dockerfile": "docker/Dockerfile"}),
                        bot.bot,
                    )
                }
            )
        }
    )
    context = image.prepare_context(custom, "v0.14.0", binary, bot_workspace / "ctx", bot_workspace)
    assert (context / "Dockerfile").read_text() == "FROM scratch\n"


def test_prepare_context_requires_the_config(
    bot: Project, binary: Path, bot_workspace: Path
) -> None:
    (bot_workspace / "lichess" / "config.yml").unlink()
    with pytest.raises(PreflightError, match=r"lichess/config\.yml"):
        image.prepare_context(bot, "v0.14.0", binary, bot_workspace / "ctx", bot_workspace)


def test_prepare_context_requires_placeholder(
    bot: Project, binary: Path, bot_workspace: Path
) -> None:
    (bot_workspace / "lichess" / "config.yml").write_text("token: lip_REALTOKEN\n")
    with pytest.raises(PreflightError, match="LICHESS_TOKEN_PLACEHOLDER"):
        image.prepare_context(bot, "v0.14.0", binary, bot_workspace / "ctx", bot_workspace)


def test_build_command_line(
    bot: Project, binary: Path, bot_workspace: Path, fake_docker: Path
) -> None:
    context = image.prepare_context(bot, "v0.14.0", binary, bot_workspace / "ctx", bot_workspace)
    tag = image.build(context, bot, "v0.14.0", logging.getLogger("t"))
    assert tag == "jwall-engineering-braveheart:v0.14.0"
    line = fake_docker.read_text().splitlines()[0]
    assert line.startswith("build ")
    for part in (
        "--platform linux/amd64",
        "--build-arg ENGINE_BINARY=braveheart",
        "--build-arg VERSION=v0.14.0",
        "--build-arg ENGINE_VERSION=v0.14.0",
        "--build-arg ENGINE_REPOSITORY=https://github.com/Braveheart-Chess/braveheart",
        "--build-arg SOURCE_REPOSITORY=https://github.com/Braveheart-Chess/braveheart",
        "--tag jwall-engineering-braveheart:v0.14.0",
    ):
        assert part in line, part
    assert line.endswith(str(context))


def test_smoke_test_parses_nodes(bot: Project, fake_docker: Path) -> None:
    nodes = image.smoke_test("jwall-engineering-braveheart:v0.14.0", bot, logging.getLogger("t"))
    assert nodes == "123456"
    line = fake_docker.read_text().splitlines()[0]
    assert "--entrypoint /opt/engine/braveheart" in line and line.endswith("bench --depth 6")
    assert "--network none" in line


def test_smoke_test_fails_without_nodes_line(
    bot: Project, fake_docker: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_DOCKER_BENCH_FAIL", "1")
    with pytest.raises(RunError, match="smoke test"):
        image.smoke_test("jwall-engineering-braveheart:v0.14.0", bot, logging.getLogger("t"))


def test_tag_exists() -> None:
    with mock_aws():
        ecr = boto3.client("ecr", region_name="us-east-1")
        ecr.create_repository(repositoryName="jwall-engineering-braveheart")
        ecr.put_image(
            repositoryName="jwall-engineering-braveheart",
            imageManifest='{"schemaVersion": 2, "mediaType": "application/vnd.docker.distribution.manifest.v2+json", "config": {"digest": "sha256:aa", "size": 1, "mediaType": "x"}, "layers": []}',  # noqa: E501
            imageTag="v0.14.0",
        )
        assert image.tag_exists(ecr, "jwall-engineering-braveheart", "v0.14.0") is True
        assert image.tag_exists(ecr, "jwall-engineering-braveheart", "v0.15.0") is False


def test_login_uses_password_stdin(fake_docker: Path) -> None:
    ecr = boto3.client("ecr", region_name="us-east-1")
    token = base64.b64encode(b"AWS:s3cret").decode()
    with Stubber(ecr) as stub:
        stub.add_response(
            "get_authorization_token",
            {
                "authorizationData": [
                    {"authorizationToken": token, "proxyEndpoint": f"https://{REGISTRY}"}
                ]
            },
        )
        registry = image.login(ecr, logging.getLogger("t"))
    assert registry == REGISTRY
    line = fake_docker.read_text().splitlines()[0]
    assert line == f"login --username AWS --password-stdin {REGISTRY}"
    assert "s3cret" not in fake_docker.read_text()


def test_push_tags_and_pushes(bot: Project, fake_docker: Path) -> None:
    remote = image.push(bot, REGISTRY, "v0.14.0", logging.getLogger("t"))
    assert remote == f"{REGISTRY}/jwall-engineering-braveheart:v0.14.0"
    assert fake_docker.read_text().splitlines() == [
        f"tag jwall-engineering-braveheart:v0.14.0 {remote}",
        f"push {remote}",
    ]


def test_present_tags_needs_only_describe_images() -> None:
    """The release role may DescribeImages but not ListImages."""
    ecr = boto3.client("ecr", region_name="us-east-1")
    with Stubber(ecr) as stub:
        stub.add_response(
            "describe_images",
            {
                "imageDetails": [
                    {"imageTags": ["v0.13.0"], "imageDigest": "sha256:a"},
                    {"imageDigest": "sha256:untagged"},
                ],
                "nextToken": "n",
            },
            {"repositoryName": "jwall-engineering-braveheart", "filter": {"tagStatus": "TAGGED"}},
        )
        stub.add_response(
            "describe_images",
            {"imageDetails": [{"imageTags": ["v0.14.0", "extra"], "imageDigest": "sha256:b"}]},
            {
                "repositoryName": "jwall-engineering-braveheart",
                "filter": {"tagStatus": "TAGGED"},
                "nextToken": "n",
            },
        )
        tags = image.present_tags(ecr, "jwall-engineering-braveheart")
    assert tags == {"v0.13.0", "v0.14.0", "extra"}


def _pinned_project(bot: Project) -> Project:
    image_component = bot.config.image.model_copy(
        update={
            "artifact": bot.config.image.artifact.model_copy(
                update={"repository": "Braveheart-Chess/braveheart", "version": "v0.13.0"}
            )
        }
    )
    bot_component = bot.config.bot.model_copy(update={"track": "pinned"})
    components = tuple(
        image_component if c is bot.config.image else bot_component if c is bot.config.bot else c
        for c in bot.config.components
    )
    return bot.model_copy(
        update={"config": bot.config.model_copy(update={"components": components})}
    )


def test_image_tag_is_the_release_for_a_bot_that_follows_releases(
    bot: Project, bot_workspace: Path
) -> None:
    assert image.image_tag(bot, "v0.14.0", bot_workspace) == "v0.14.0"


def test_image_tag_of_a_pinned_bot_names_its_config(bot: Project, bot_workspace: Path) -> None:
    pinned = _pinned_project(bot)
    first = image.image_tag(pinned, "v0.13.0", bot_workspace)
    assert first.startswith("v0.13.0-") and len(first) == len("v0.13.0-") + 8
    assert image.image_tag(pinned, "v0.13.0", bot_workspace) == first  # deterministic
    config = bot_workspace / "lichess" / "config.yml"
    config.write_text(config.read_text() + "# a change\n")
    assert image.image_tag(pinned, "v0.13.0", bot_workspace) != first


def test_image_tag_of_a_pinned_bot_needs_its_config(bot: Project, tmp_path: Path) -> None:
    with pytest.raises(PreflightError, match=r"lichess/config\.yml not found"):
        image.image_tag(_pinned_project(bot), "v0.13.0", tmp_path)


def test_build_passes_the_engine_version_separately(
    bot: Project, binary: Path, bot_workspace: Path, fake_docker: Path
) -> None:
    context = image.prepare_context(
        bot, "v0.13.0-abcd1234", binary, bot_workspace / "c", bot_workspace
    )
    image.build(context, bot, "v0.13.0-abcd1234", logging.getLogger("t"), engine_version="v0.13.0")
    line = fake_docker.read_text().splitlines()[0]
    assert "--build-arg VERSION=v0.13.0-abcd1234" in line
    assert "--build-arg ENGINE_VERSION=v0.13.0" in line
