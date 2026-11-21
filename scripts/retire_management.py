"""Retire what jaws left in the management account (docs/management-retirement.md).

Owner only, from a checkout of this repository, with admin sign-ins to both
accounts (`aws sso login --profile jwall-admin` and `--profile jaws-prod`):

    uv run python scripts/retire_management.py            # checks only; changes nothing
    uv run python scripts/retire_management.py --execute  # asks before each phase

Every run starts with the checks, and nothing changes unless all of them pass:

- config.yaml has `production.management_retired: true`, and each profile
  signs in to the account config.yaml names for it;
- no EC2 instance tagged by jaws exists in the management account;
- the registrar's name servers are production's zone's, not the old zone's;
- every object of every old data bucket is in its production home with the
  same key, size and ETag (all buckets use SSE-S3 and single-part uploads, so
  an equal ETag is an equal MD5 of the bytes), and no old bucket holds a key
  outside the prefixes that were copied.

`--execute` then retires, one confirmed phase at a time:

1. the management foundation's Terraform state (from the last release that
   managed it, LAST_MANAGEMENT_RELEASE): the state bucket, the old zone and the
   EC2 Spot service-linked role are removed from state; the site buckets and the
   image repository are emptied; everything else is destroyed;
2. the EC2 Spot service-linked role, the old zone's records and the zone, and
   the management account's copy of the Databricks client secret;
3. the old data, task and site buckets, every version;
4. the state objects of retired stacks in the state bucket, every version. The
   bucket itself and owner-access's state stay: owner-access lives here.

Every phase can be run again: what is already gone is skipped.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import yaml

REPO = Path(__file__).resolve().parent.parent
#: The last release whose CI planned and applied the management foundation.
LAST_MANAGEMENT_RELEASE = "v0.69.0"
REGION = "us-east-1"

#: Each old data bucket, and where each of its prefixes was copied in production.
#: A key under no listed prefix stops the run: it was never copied.
DATA_COPIES: dict[str, dict[str, str]] = {
    "jwall-engineering-braveheart-selfplay-positions": {
        "data/selfplay/": "jaws-braveheart-selfplay-positions"
    },
    "jwall-engineering-braveheart-trainer-nets": {"data/nets/": "jaws-braveheart-trainer-nets"},
    "jwall-engineering-braveheart-nnue": {
        "data/selfplay/": "jaws-braveheart-selfplay-positions",
        "data/nets/": "jaws-braveheart-trainer-nets",
    },
    "jwall-engineering-rusty-chess-nnue": {
        "data/selfplay/": "jaws-braveheart-selfplay-positions",
        "data/nets/": "jaws-braveheart-trainer-nets",
    },
    "jwall-engineering-braveheart-records": {"records/": "jaws-braveheart-bot-records"},
}
#: Buckets whose contents are not kept: task results (they expire on their own)
#: and the management workspace's Databricks audit logs.
DISCARDED_BUCKETS = (
    "jwall-engineering-braveheart-tasks",
    "jwall-engineering-braveheart-selfplay-tasks",
    "jwall-engineering-braveheart-trainer-tasks",
    "jwall-engineering-databricks-audit-logs",
)
#: The old site buckets: the sites have served from production since 2026-11-18.
SITE_BUCKETS = (
    "jwall-engineering-main-site",
    "jwall-engineering-cs-survival-guide",
    "jwall-engineering-guitar-knowledge-base",
)
#: Kept in AWS, removed from the foundation's state; phase 2 deletes the last two.
RELEASED_FROM_STATE = ("module.state_bucket", "module.zone", "module.spot_service_linked_role")
SPOT_ROLE = "AWSServiceRoleForEC2Spot"
DATABRICKS_SECRET = "/jwall-engineering/databricks/client-secret"
#: The state bucket keeps owner-access's state; every other prefix is a retired stack's.
KEPT_STATE_PREFIX = "project=owner-access/"


class RefusedError(Exception):
    """A check failed: nothing was changed."""


@dataclass(frozen=True)
class Obj:
    size: int
    etag: str


# -- reading -----------------------------------------------------------------------------


def listing(s3: Any, bucket: str, prefix: str = "") -> dict[str, Obj]:
    """Every current object under `prefix`: key to size and ETag."""
    objects: dict[str, Obj] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            objects[o["Key"]] = Obj(o["Size"], o["ETag"].strip('"'))
    return objects


def route(key: str, prefixes: dict[str, str]) -> str | None:
    """The production bucket a key of an old bucket was copied to, if any."""
    for prefix, destination in prefixes.items():
        if key.startswith(prefix):
            return destination
    return None


def compare(
    source: dict[str, Obj], prefixes: dict[str, str], destinations: dict[str, dict[str, Obj]]
) -> list[str]:
    """Every way `source` is not fully in its destinations; empty when it is."""
    problems = []
    for key, obj in sorted(source.items()):
        destination = route(key, prefixes)
        if destination is None:
            problems.append(f"{key}: under no copied prefix")
            continue
        copy = destinations[destination].get(key)
        if copy is None:
            problems.append(f"{key}: missing from {destination}")
        elif copy != obj:
            problems.append(f"{key}: {obj} here, {copy} in {destination}")
    return problems


def account_of(session: Any) -> str:
    return str(session.client("sts").get_caller_identity()["Account"])


def name_servers(zone: Any) -> set[str]:
    return {ns.rstrip(".").lower() for ns in zone["DelegationSet"]["NameServers"]}


def registrar_name_servers(domain: str) -> set[str]:
    out = subprocess.run(
        ["dig", "+short", "NS", domain, "@1.1.1.1"], check=True, capture_output=True, text=True
    ).stdout
    return {line.rstrip(".").lower() for line in out.split()}


# -- checks ------------------------------------------------------------------------------


@dataclass
class Context:
    management: Any
    production: Any
    management_account: str
    production_account: str
    old_zone_id: str
    production_zone_id: str
    domain: str


def load_context(management_profile: str, production_profile: str) -> Context:
    config = yaml.safe_load((REPO / "config.yaml").read_text())
    production = config["production"]
    if not production.get("management_retired"):
        raise RefusedError("config.yaml does not have production.management_retired: true")
    return Context(
        management=boto3.Session(profile_name=management_profile, region_name=REGION),
        production=boto3.Session(profile_name=production_profile, region_name=REGION),
        management_account=str(config["aws"]["account_id"]),
        production_account=str(production["overrides"]["aws"]["account_id"]),
        old_zone_id=config["dns"]["zone_id"],
        production_zone_id=production["overrides"]["dns"]["zone_id"],
        domain=config["dns"]["zone"],
    )


def check(ctx: Context) -> None:
    for session, want, name in (
        (ctx.management, ctx.management_account, "management"),
        (ctx.production, ctx.production_account, "production"),
    ):
        got = account_of(session)
        if got != want:
            raise RefusedError(f"the {name} profile signs in to {got}, not {want}")
    print(f"ok  profiles: management {ctx.management_account}, production {ctx.production_account}")

    ec2 = ctx.management.client("ec2")
    instances = [
        i["InstanceId"]
        for r in ec2.describe_instances(
            Filters=[
                {"Name": "tag-key", "Values": ["Organization"]},
                {
                    "Name": "instance-state-name",
                    "Values": ["pending", "running", "stopping", "stopped"],
                },
            ]
        )["Reservations"]
        for i in r["Instances"]
        if any(
            t["Key"] == "Organization" and t["Value"].startswith("jwall-engineering")
            for t in i.get("Tags", [])
        )
    ]
    if instances:
        raise RefusedError(f"jaws instances still exist in management: {', '.join(instances)}")
    print("ok  no jaws EC2 instance in management")

    old = ctx.management.client("route53").get_hosted_zone(Id=ctx.old_zone_id)
    new = ctx.production.client("route53").get_hosted_zone(Id=ctx.production_zone_id)
    registrar = registrar_name_servers(ctx.domain)
    if registrar != name_servers(new) or registrar & name_servers(old):
        raise RefusedError(
            f"{ctx.domain} is delegated to {sorted(registrar)}: not production's zone alone"
        )
    print(f"ok  {ctx.domain} is served by production's zone {ctx.production_zone_id} only")

    old_s3, new_s3 = ctx.management.client("s3"), ctx.production.client("s3")
    destinations: dict[str, dict[str, Obj]] = {}
    for prefixes in DATA_COPIES.values():
        for destination in prefixes.values():
            if destination not in destinations:
                destinations[destination] = listing(new_s3, destination)
    for bucket, prefixes in DATA_COPIES.items():
        source = listing(old_s3, bucket)
        problems = compare(source, prefixes, destinations)
        if problems:
            shown = "\n    ".join(problems[:10])
            raise RefusedError(
                f"{bucket}: {len(problems)} object(s) not in production:\n    {shown}"
            )
        size = sum(o.size for o in source.values())
        print(
            f"ok  {bucket}: all {len(source):,} objects ({size:,} bytes) in production, "
            "same size and ETag"
        )
        multipart = [k for k, o in source.items() if "-" in o.etag]
        if multipart:
            raise RefusedError(
                f"{bucket}: {len(multipart)} multipart ETag(s); compare those by checksum first"
            )


# -- changing ----------------------------------------------------------------------------


def confirm(phase: str) -> None:
    if input(f"\n{phase}\nType 'retire' to go ahead: ").strip() != "retire":
        raise RefusedError(f"not confirmed: {phase}")


def batches(items: Iterable[dict[str, str]], size: int = 1000) -> Iterator[list[dict[str, str]]]:
    batch: list[dict[str, str]] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def versions(s3: Any, bucket: str, prefix: str = "") -> Iterator[dict[str, str]]:
    """Every object version and delete marker under `prefix`."""
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefix):
        for v in page.get("Versions", []) + page.get("DeleteMarkers", []):
            yield {"Key": v["Key"], "VersionId": v["VersionId"]}


def empty(s3: Any, bucket: str, keep_prefix: str | None = None) -> int:
    """Delete every version in `bucket`, except under `keep_prefix`."""
    deleted = 0
    wanted = (
        v for v in versions(s3, bucket) if not (keep_prefix and v["Key"].startswith(keep_prefix))
    )
    for batch in batches(wanted):
        result = s3.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})
        if result.get("Errors"):
            raise RuntimeError(f"{bucket}: {result['Errors'][:3]}")
        deleted += len(batch)
    return deleted


def bucket_exists(s3: Any, bucket: str) -> bool:
    try:
        s3.head_bucket(Bucket=bucket)
    except s3.exceptions.ClientError as error:
        if error.response["Error"]["Code"] in ("404", "NoSuchBucket"):
            return False
        raise
    return True


def delete_bucket(s3: Any, bucket: str) -> None:
    if not bucket_exists(s3, bucket):
        print(f"--  {bucket}: already gone")
        return
    count = empty(s3, bucket)
    s3.delete_bucket(Bucket=bucket)
    print(f"del {bucket}: {count:,} versions, then the bucket")


def terraform(workdir: Path, env: dict[str, str], *args: str) -> str:
    result = subprocess.run(
        ["terraform", *args], cwd=workdir, env=env, check=True, capture_output=True, text=True
    )
    return result.stdout


def retire_foundation(ctx: Context, profile: str) -> None:
    confirm(
        f"Phase 1: the management foundation, from {LAST_MANAGEMENT_RELEASE}. Release "
        f"{', '.join(RELEASED_FROM_STATE)} from state, empty the site buckets and the image "
        "repository, then destroy the rest (the CI roles, the site buckets, the repository)."
    )
    s3, ecr = ctx.management.client("s3"), ctx.management.client("ecr")
    tree = Path(tempfile.mkdtemp(prefix="jaws-management-"))
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(tree), LAST_MANAGEMENT_RELEASE],
        cwd=REPO,
        check=True,
    )
    try:
        foundation = tree / "foundation"
        env = {**os.environ, "AWS_PROFILE": profile, "TF_IN_AUTOMATION": "1"}
        terraform(
            foundation,
            env,
            "init",
            "-input=false",
            "-reconfigure",
            "-backend-config=backend/management.hcl",
        )
        state = terraform(foundation, env, "state", "list").split()
        for address in RELEASED_FROM_STATE:
            if any(
                a == address or a.startswith(address + ".") or a.startswith(address + "[")
                for a in state
            ):
                terraform(foundation, env, "state", "rm", address)
                print(f"ok  released {address} from state")
        for bucket in SITE_BUCKETS:
            if bucket_exists(s3, bucket):
                print(f"ok  emptied {bucket}: {empty(s3, bucket):,} versions")
        repository = "jwall-engineering-sites"
        images = [
            {"imageDigest": i["imageDigest"]}
            for page in ecr.get_paginator("list_images").paginate(repositoryName=repository)
            for i in page["imageIds"]
        ]
        for batch in (images[i : i + 100] for i in range(0, len(images), 100)):
            ecr.batch_delete_image(repositoryName=repository, imageIds=batch)
        print(f"ok  deleted {len(images)} image(s) from {repository}")
        plan = terraform(
            foundation,
            env,
            "plan",
            "-destroy",
            "-input=false",
            "-no-color",
            "-var",
            "account=management",
            "-out=retire.tfplan",
        )
        print(next((line for line in plan.splitlines() if line.startswith("Plan:")), plan[-2000:]))
        confirm("Apply that destroy plan?")
        print(
            terraform(
                foundation, env, "apply", "-input=false", "-no-color", "retire.tfplan"
            ).splitlines()[-1]
        )
        left = terraform(foundation, env, "state", "list").split()
        if [a for a in left if not a.startswith("data.") and ".data." not in a]:
            raise RuntimeError(f"resources left in state: {left}")
        print("ok  the management foundation's state holds nothing")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=REPO, check=False)
        shutil.rmtree(tree, ignore_errors=True)


def retire_leftovers(ctx: Context) -> None:
    confirm(
        f"Phase 2: delete the EC2 Spot service-linked role, the old zone "
        f"{ctx.old_zone_id} (its records, then the zone) and {DATABRICKS_SECRET}."
    )
    iam = ctx.management.client("iam")
    try:
        task = iam.delete_service_linked_role(RoleName=SPOT_ROLE)["DeletionTaskId"]
        status = iam.get_service_linked_role_deletion_status(DeletionTaskId=task)
        print(f"del {SPOT_ROLE}: {status['Status']}")
    except iam.exceptions.NoSuchEntityException:
        print(f"--  {SPOT_ROLE}: already gone")

    route53 = ctx.management.client("route53")
    try:
        records = [
            r
            for page in route53.get_paginator("list_resource_record_sets").paginate(
                HostedZoneId=ctx.old_zone_id
            )
            for r in page["ResourceRecordSets"]
            if not (r["Type"] in ("NS", "SOA") and r["Name"].rstrip(".") == ctx.domain)
        ]
        if records:
            route53.change_resource_record_sets(
                HostedZoneId=ctx.old_zone_id,
                ChangeBatch={
                    "Changes": [{"Action": "DELETE", "ResourceRecordSet": r} for r in records]
                },
            )
        route53.delete_hosted_zone(Id=ctx.old_zone_id)
        print(f"del zone {ctx.old_zone_id}: {len(records)} record set(s), then the zone")
    except route53.exceptions.NoSuchHostedZone:
        print(f"--  zone {ctx.old_zone_id}: already gone")

    ssm = ctx.management.client("ssm")
    try:
        ssm.delete_parameter(Name=DATABRICKS_SECRET)
        print(f"del {DATABRICKS_SECRET}")
    except ssm.exceptions.ParameterNotFound:
        print(f"--  {DATABRICKS_SECRET}: already gone")


def retire_buckets(ctx: Context) -> None:
    buckets = (*DATA_COPIES, *DISCARDED_BUCKETS, *SITE_BUCKETS)
    confirm("Phase 3: delete these buckets, every version:\n  " + "\n  ".join(buckets))
    s3 = ctx.management.client("s3")
    for bucket in buckets:
        delete_bucket(s3, bucket)


def retire_state(ctx: Context, state_bucket: str) -> None:
    confirm(
        f"Phase 4: delete every version in {state_bucket} outside {KEPT_STATE_PREFIX} "
        "(the retired stacks' state); the bucket and owner-access's state stay."
    )
    count = empty(ctx.management.client("s3"), state_bucket, keep_prefix=KEPT_STATE_PREFIX)
    print(f"del {count:,} version(s) of retired stacks' state")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--execute", action="store_true", help="retire, asking before each phase")
    parser.add_argument("--management-profile", default="jwall-admin")
    parser.add_argument("--production-profile", default="jaws-prod")
    args = parser.parse_args(argv)
    try:
        ctx = load_context(args.management_profile, args.production_profile)
        check(ctx)
        if not args.execute:
            print("\nEvery check passed. Nothing was changed; --execute retires, phase by phase.")
            return 0
        config = yaml.safe_load((REPO / "config.yaml").read_text())
        retire_foundation(ctx, args.management_profile)
        retire_leftovers(ctx)
        retire_buckets(ctx)
        retire_state(ctx, config["state"]["bucket"])
    except RefusedError as refused:
        print(f"\nstopped: {refused}", file=sys.stderr)
        return 1
    print("\nThe management account's jaws footprint is retired.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
