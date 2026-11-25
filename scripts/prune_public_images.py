"""Select what to delete from the public ECR repository after a publish.

ECR Public has no lifecycle policies, so each publish prunes. Reads the JSON of
`aws ecr-public describe-images` on stdin and prints the image IDs to delete, in batches
of at most 100 (BatchDeleteImage's limit), one JSON array per line. Why it selects what it
selects goes to stderr.

    python3 scripts/prune_public_images.py --keep <N|all> --published <tag> < images.json

The release runs this file from its workflow's own commit (`github.workflow_sha`, checked
out at .release-tools/), never from the tag being published, since it runs with the
publishing role. So the file and the workflow that calls it are always of one commit. It
runs with the runner's system python3 (3.12 on ubuntu-latest): Python 3.12 syntax and the
standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

BATCH = 100
VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
KEEP = re.compile(r"[1-9][0-9]*|all")
INDEXES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}


def _semver(tag: str) -> tuple[int, int, int] | None:
    match = VERSION.fullmatch(tag)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def select(
    images: list[dict[str, Any]], keep: str, published: str, log: list[str]
) -> list[dict[str, str]]:
    """The image IDs to delete, oldest version first, untagged images last."""
    if keep == "all":
        log.append("keeping every image (keep is all)")
        return []
    versions = sorted(
        {t for i in images for t in i.get("imageTags") or [] if _semver(t)},
        key=lambda t: _semver(t) or (0, 0, 0),
        reverse=True,
    )
    kept = {*versions[: int(keep)], published}
    doomed = [t for t in reversed(versions) if t not in kept]
    ids: list[dict[str, str]] = []
    for tag in doomed:
        carrier = next(i for i in images if tag in (i.get("imageTags") or []))
        if kept & set(carrier["imageTags"]):
            log.append(f"keeping {tag}: its image also carries a kept tag")
            continue
        log.append(f"deleting {tag}: older than the newest {keep} release versions")
        ids.append({"imageTag": tag})
    untagged = [i for i in images if not i.get("imageTags")]
    if any(i.get("imageManifestMediaType") in INDEXES for i in images):
        log.append("keeping untagged images: the repository holds an index that may refer to them")
    else:
        for image in untagged:
            log.append(f"deleting untagged {image['imageDigest']}")
            ids.append({"imageDigest": image["imageDigest"]})
    if not ids:
        log.append("nothing to delete")
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--keep", required=True)
    parser.add_argument("--published", required=True)
    args = parser.parse_args()
    if not KEEP.fullmatch(args.keep):
        print(
            "JAWS_PUBLIC_IMAGE_KEEP is neither a whole number of at least 1 nor all: "
            f"{args.keep!r}",
            file=sys.stderr,
        )
        return 2
    images = json.load(sys.stdin)["imageDetails"]
    log: list[str] = []
    ids = select(images, args.keep, args.published, log)
    for line in log:
        print(line, file=sys.stderr)
    for start in range(0, len(ids), BATCH):
        print(json.dumps(ids[start : start + BATCH]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
