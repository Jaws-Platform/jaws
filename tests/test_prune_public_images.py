"""What each publish deletes from the public repository (ruling 14), fed `describe-images`
JSON as the step feeds it, with no AWS.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest

from tests.conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "prune_public_images.py"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"
INDEX = "application/vnd.oci.image.index.v1+json"
LIST = "application/vnd.docker.distribution.manifest.list.v2+json"
UNTAGGED = "sha256:" + "0" * 64


def _image(*tags: str, digest: str = "", media_type: str = MANIFEST) -> dict[str, Any]:
    """One `imageDetails` entry. With no tags it has no `imageTags`, as AWS answers;
    the digest defaults to one made from the tags."""
    image: dict[str, Any] = {
        "imageDigest": digest or "sha256:" + "-".join(tags).encode().hex().ljust(64, "f"),
        "imageManifestMediaType": media_type,
    }
    if tags:
        image["imageTags"] = list(tags)
    return image


def _versions(count: int) -> list[dict[str, Any]]:
    """v0.1.0 to v0.<count>.0: from v0.10.0 on, text order and semver order differ."""
    return [_image(f"v0.{minor}.0") for minor in range(1, count + 1)]


def _prune(
    images: list[dict[str, Any]], keep: str, published: str
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, str]]]:
    """Run the script as the step does: the result, and every image ID it would delete."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), f"--keep={keep}", "--published", published],
        input=json.dumps({"imageDetails": images}),
        capture_output=True,
        text=True,
        check=False,
    )
    deleted = [id_ for line in result.stdout.splitlines() for id_ in json.loads(line)]
    return result, deleted


def test_it_keeps_the_newest_n_release_versions_by_semver() -> None:
    result, deleted = _prune(_versions(12), keep="10", published="v0.12.0")
    assert result.returncode == 0, result.stderr
    assert deleted == [{"imageTag": "v0.1.0"}, {"imageTag": "v0.2.0"}]


def test_it_never_deletes_the_tag_just_published() -> None:
    """A re-published older tag stays until a later publish prunes it."""
    _, deleted = _prune(_versions(12), keep="1", published="v0.3.0")
    tags = [d["imageTag"] for d in deleted]
    assert "v0.3.0" not in tags and "v0.12.0" not in tags and len(tags) == 10


def test_it_removes_untagged_images_and_leaves_other_tags_alone() -> None:
    images = [*_versions(2), _image(digest=UNTAGGED), _image("latest")]
    _, deleted = _prune(images, keep="1", published="v0.2.0")
    assert deleted == [{"imageTag": "v0.1.0"}, {"imageDigest": UNTAGGED}]


def test_an_empty_image_tags_list_is_untagged_too() -> None:
    untagged = {"imageDigest": UNTAGGED, "imageTags": [], "imageManifestMediaType": MANIFEST}
    images = [*_versions(1), untagged]
    _, deleted = _prune(images, keep="10", published="v0.1.0")
    assert deleted == [{"imageDigest": UNTAGGED}]


def test_a_version_whose_image_also_carries_a_kept_tag_loses_only_its_tag() -> None:
    """Deleting by tag removes the tag (ruling 14, P4-R12): ECR keeps the image while a
    kept tag still names it, so v0.4.0 stays."""
    images = [_image("v0.2.0"), _image("v0.3.0"), _image("v0.1.0", "v0.4.0")]
    _, deleted = _prune(images, keep="2", published="v0.3.0")
    assert deleted == [{"imageTag": "v0.1.0"}, {"imageTag": "v0.2.0"}]


@pytest.mark.parametrize("media_type", [INDEX, LIST])
def test_untagged_images_stay_while_an_index_could_refer_to_them(media_type: str) -> None:
    images = [*_versions(2), _image("v0.3.0", media_type=media_type), _image(digest=UNTAGGED)]
    result, deleted = _prune(images, keep="10", published="v0.3.0")
    assert deleted == [] and "index" in result.stderr


def test_all_keeps_every_version() -> None:
    result, deleted = _prune(_versions(12), keep="all", published="v0.12.0")
    assert result.returncode == 0 and deleted == []


@pytest.mark.parametrize("keep", ["ten", "0", "-1", "1.5", " 10", "", "ALL", "10\n"])
def test_it_refuses_a_keep_that_is_neither_a_whole_number_nor_all(keep: str) -> None:
    result, deleted = _prune(_versions(12), keep=keep, published="v0.12.0")
    assert result.returncode == 2 and "JAWS_PUBLIC_IMAGE_KEEP" in result.stderr
    assert result.stdout == "" and deleted == []


def test_it_deletes_in_batches_the_api_accepts() -> None:
    images = [_image(f"v1.0.{patch}") for patch in range(250)]
    result, _ = _prune(images, keep="10", published="v1.0.249")
    assert [len(json.loads(line)) for line in result.stdout.splitlines()] == [100, 100, 40]
