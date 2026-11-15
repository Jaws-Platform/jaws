"""The container image of a bot project: build context, build, smoke test, push.

`build` needs only Docker: the image is tagged locally as
`<image_repository>:<tag>`. `push` logs in to ECR, retags it with the
registry and pushes. Tags are immutable in the repository; callers check
`tag_exists` first so an existing tag is refused with a clear message.

The tag is the engine release (`v0.54.0`) for a bot that follows every
release. A `track: pinned` bot owns its config, which changes without a new
engine release, so its tag also carries the first 8 hex digits of the
config's SHA-256 (`v0.54.0-3f9c2a1b`): a new config is a new image, and the
same pin and config are the same tag, so a re-run changes nothing.
"""

from __future__ import annotations

import base64
import hashlib
import re
import shutil
import subprocess
from importlib import resources
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from .errors import PreflightError, RunError
from .project import Project

if TYPE_CHECKING:
    from mypy_boto3_ecr import ECRClient

PLACEHOLDER = "LICHESS_TOKEN_PLACEHOLDER"
KIND_PACKAGE = "jwall_engineering_sites.kinds.lichess_bot"
PLATFORMS = {"x86_64": "linux/amd64", "arm64": "linux/arm64"}
_NODES = re.compile(r"^Nodes searched\s*:?\s*(\d+)", re.MULTILINE)
#: Hex digits of the config digest in a pinned bot's tag.
CONFIG_DIGEST_LENGTH = 8


def config_digest(project: Project, consumer_root: Path) -> str:
    """SHA-256 of what a pinned bot's image takes from its repository: the
    lichess-bot config, and a replacement Dockerfile when the file names one."""
    digest = hashlib.sha256()
    paths = [project.bot.config, *([project.image.dockerfile] if project.image.dockerfile else [])]
    for relative in paths:
        path = consumer_root / relative
        if not path.is_file():
            raise PreflightError(f"{relative} not found in the repository")
        digest.update(relative.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def image_tag(project: Project, version: str, consumer_root: Path) -> str:
    """The image tag for engine release `version`: the version itself, or for a
    pinned bot the version and its config digest."""
    if project.pinned_version is None:
        return version
    return f"{version}-{config_digest(project, consumer_root)[:CONFIG_DIGEST_LENGTH]}"


def local_tag(project: Project, tag: str) -> str:
    return f"{project.image_repository}:{tag}"


def remote_tag(project: Project, registry: str, tag: str) -> str:
    return f"{registry}/{project.image_repository}:{tag}"


def _docker(args: list[str], logger: Logger, docker: str, stdin: str | None = None) -> str:
    logger.debug("$ %s %s", docker, " ".join(args))
    try:
        completed = subprocess.run(
            [docker, *args], input=stdin, capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:
        raise RunError(f"{docker} not found on PATH") from exc
    if completed.returncode != 0:
        raise RunError(
            f"docker {args[0]} failed with exit code {completed.returncode}: "
            f"{(completed.stderr or completed.stdout).strip()[-2000:]}"
        )
    return completed.stdout


def prepare_context(
    project: Project, tag: str, binary: Path, workdir: Path, consumer_root: Path
) -> Path:
    """Copy the Dockerfile, the entrypoint, the engine and the consumer's config
    into a fresh build context."""
    config = consumer_root / project.bot.config
    if not config.is_file():
        raise PreflightError(f"lichess-bot config {project.bot.config} not found in the repository")
    if PLACEHOLDER not in config.read_text():
        raise PreflightError(
            f"{project.bot.config} must hold the token as {PLACEHOLDER}; "
            "the real token is injected at container start and never committed"
        )
    if workdir.exists():
        shutil.rmtree(workdir)
    (workdir / "engine").mkdir(parents=True)
    kind = resources.files(KIND_PACKAGE)
    if project.image.dockerfile:
        dockerfile = consumer_root / project.image.dockerfile
        if not dockerfile.is_file():
            raise PreflightError(f"dockerfile {project.image.dockerfile} not found")
        shutil.copyfile(dockerfile, workdir / "Dockerfile")
    else:
        (workdir / "Dockerfile").write_text(kind.joinpath("Dockerfile").read_text())
    (workdir / "entrypoint.py").write_text(kind.joinpath("entrypoint.py").read_text())
    engine = workdir / "engine" / project.image.artifact.binary
    shutil.copyfile(binary, engine)
    engine.chmod(0o755)
    shutil.copyfile(config, workdir / "config.yml")
    return workdir


def build(
    context: Path,
    project: Project,
    tag: str,
    logger: Logger,
    docker: str = "docker",
    engine_version: str | None = None,
) -> str:
    """`engine_version` is the engine release inside the image; it defaults to
    `tag`, which is the release itself unless the bot is pinned."""
    name = local_tag(project, tag)
    _docker(
        [
            "build",
            "--platform",
            PLATFORMS[project.image.architecture],
            "--build-arg",
            f"ENGINE_BINARY={project.image.artifact.binary}",
            "--build-arg",
            f"VERSION={tag}",
            "--build-arg",
            f"ENGINE_VERSION={engine_version or tag}",
            "--build-arg",
            f"ENGINE_REPOSITORY=https://github.com/{project.release_repository}",
            "--build-arg",
            f"SOURCE_REPOSITORY=https://github.com/{project.config.repository}",
            "--tag",
            name,
            str(context),
        ],
        logger,
        docker,
    )
    logger.info("built %s", name)
    return name


def smoke_test(name: str, project: Project, logger: Logger, docker: str = "docker") -> str:
    """Run the engine's bench inside the image, offline; return the node count."""
    binary = project.image.artifact.binary
    try:
        output = _docker(
            [
                "run",
                "--rm",
                "--network",
                "none",
                "--platform",
                PLATFORMS[project.image.architecture],
                "--entrypoint",
                f"/opt/engine/{binary}",
                name,
                "bench",
                "--depth",
                "6",
            ],
            logger,
            docker,
        )
    except RunError as exc:
        raise RunError(f"smoke test of {name} failed: {exc}") from exc
    match = _NODES.search(output)
    if not match:
        raise RunError(f"smoke test of {name}: `bench --depth 6` printed no 'Nodes searched' line")
    logger.info("smoke test: %s searched %s nodes at depth 6", name, match.group(1))
    return match.group(1)


def tag_exists(ecr: ECRClient, repository: str, tag: str) -> bool:
    try:
        ecr.describe_images(repositoryName=repository, imageIds=[{"imageTag": tag}])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ImageNotFoundException":
            return False
        raise RunError(f"cannot check {repository}:{tag}: {exc}") from exc
    return True


def present_tags(ecr: ECRClient, repository: str) -> set[str]:
    """Every tag in the repository (ECR API only; no docker login). Uses
    DescribeImages, which the release role holds; it has no ListImages."""
    tags: set[str] = set()
    try:
        for page in ecr.get_paginator("describe_images").paginate(
            repositoryName=repository, filter={"tagStatus": "TAGGED"}
        ):
            for detail in page.get("imageDetails", []):
                tags.update(detail.get("imageTags", []))
    except ClientError as exc:
        raise RunError(f"cannot list the tags of {repository}: {exc}") from exc
    return tags


def login(ecr: ECRClient, logger: Logger, docker: str = "docker") -> str:
    """docker login to the account's registry; returns the registry host."""
    data = ecr.get_authorization_token()["authorizationData"][0]
    user, password = base64.b64decode(data["authorizationToken"]).decode().split(":", 1)
    registry = data["proxyEndpoint"].removeprefix("https://")
    _docker(["login", "--username", user, "--password-stdin", registry], logger, docker, password)
    logger.info("logged in to %s", registry)
    return registry


def push(project: Project, registry: str, tag: str, logger: Logger, docker: str = "docker") -> str:
    remote = remote_tag(project, registry, tag)
    _docker(["tag", local_tag(project, tag), remote], logger, docker)
    _docker(["push", remote], logger, docker)
    logger.info("pushed %s", remote)
    return remote
