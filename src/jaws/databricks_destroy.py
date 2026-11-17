"""What `destroy` deletes from a Databricks project, and emptying its catalog bucket.

Destroy order (ruling R7): empty the catalog bucket while its bucket policy still
grants the apply role list and delete, then destroy the workspace stack (which
removes the empty bucket and the catalog), then the account stack. Every step is
idempotent, so a re-run continues where a failed one stopped.

Before Terraform destroys the workspace stack, some of its resources are released
from state instead of deleted (`released_addresses`), and a securable that lost
its workspace binding to an earlier, failed destroy is bound again
(`unbound_securables`, `restore_bindings`).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from logging import Logger
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from .databricks_names import derived_names
from .errors import RunError
from .project import Project
from .site import ENVIRONMENT

#: The most keys one DeleteObjects request takes.
DELETE_BATCH = 1000

KEPT = "Kept: the metastore, the event log and the client secret in SSM."

#: Resource types the workspace stack's destroy releases from Terraform state
#: instead of deleting. Each goes with something destroy deletes anyway, and
#: deleting it first fails:
#:
#: - the legacy settings: Databricks refuses to delete them ("This setting cannot
#:   be modified or deleted for this workspace"); they go with the workspace.
#: - grants and workspace bindings: they go with their catalog, external location
#:   or storage credential. Terraform orders nothing between a securable's grants
#:   and its binding, and once the binding is gone the isolated securable is "not
#:   accessible in current workspace", so its grants can no longer be deleted.
RELEASED_TYPES = frozenset(
    {
        "databricks_disable_legacy_access_setting",
        "databricks_disable_legacy_dbfs_setting",
        "databricks_grants",
        "databricks_workspace_binding",
    }
)

_INDEX = re.compile(r"\[[^\]]*\]$")


def _resource(address: str) -> tuple[str, str]:
    """The (type, name) of a state address, without its module path or index."""
    parts = _INDEX.sub("", address).split(".")
    return (parts[-2], parts[-1]) if len(parts) >= 2 else ("", "")


def released_addresses(state: Sequence[str]) -> list[str]:
    """The addresses in `state` to release (`terraform state rm`) before destroy."""
    return [address for address in state if _resource(address)[0] in RELEASED_TYPES]


def unbound_securables(state: Sequence[str], project: Project) -> list[tuple[str, str]]:
    """The catalog module's securables still in `state` whose workspace binding is
    not: an earlier destroy deleted the binding and then failed. Returns
    (securable type, name) pairs, as the workspace bindings API takes them."""
    names = derived_names(project)
    securables = {
        "databricks_catalog": ("catalog", project.project.replace("-", "_")),
        "databricks_external_location": ("external_location", names.catalog_bucket),
        # The catalog module names the storage credential after its role.
        "databricks_storage_credential": ("storage_credential", names.uc_role),
    }
    resources = {_resource(address) for address in state}
    present = {kind for kind, _ in resources}
    bound = {name for kind, name in resources if kind == "databricks_workspace_binding"}
    return [
        securable
        for kind, securable in securables.items()
        if kind in present and securable[0] not in bound
    ]


def restore_bindings(
    workspace: Any, workspace_id: int, securables: Sequence[tuple[str, str]], logger: Logger
) -> list[str]:
    """Bind each securable to the workspace again, so destroy can reach it.

    `workspace` is the SDK's WorkspaceClient. A refusal is logged and destroy goes
    on: Terraform's own error then names what is left. Returns the names bound.
    """
    from databricks.sdk.errors.base import DatabricksError
    from databricks.sdk.service.catalog import WorkspaceBinding, WorkspaceBindingBindingType

    bound: list[str] = []
    for kind, name in securables:
        binding = WorkspaceBinding(
            workspace_id=workspace_id,
            binding_type=WorkspaceBindingBindingType.BINDING_TYPE_READ_WRITE,
        )
        try:
            workspace.workspace_bindings.update_bindings(kind, name, add=[binding])
        except (DatabricksError, OSError) as exc:
            logger.warning(
                "cannot bind the %s %s to workspace %s again (%s: %s); destroy goes on. If it "
                "fails on this object, delete it by hand in Catalog Explorer as a metastore "
                "admin, then re-run destroy",
                kind.replace("_", " "),
                name,
                workspace_id,
                type(exc).__name__,
                exc,
            )
            continue
        logger.info(
            "bound the %s %s to workspace %s again: an earlier destroy removed the binding",
            kind.replace("_", " "),
            name,
            workspace_id,
        )
        bound.append(name)
    return bound


def deletion_list(project: Project) -> list[str]:
    """Everything `destroy` deletes, for the confirmation before it acts."""
    names = derived_names(project)
    catalog = project.project.replace("-", "_")
    return [
        f"the workspace {project.project}-{ENVIRONMENT} and everything in it: clusters, "
        "notebooks, jobs, its compute policies and settings",
        f"the catalog {catalog} with its schemas, tables and grants, its storage credential "
        "and external location",
        f"the catalog bucket s3://{names.catalog_bucket} and every object version in it",
        f"the root bucket s3://{names.root_bucket} and its contents",
        f"the VPC {project.vpc_name} with its subnets, endpoints and security group, "
        "and its NAT instance",
        f"the roles {names.cross_account_role} and {names.uc_role}, the workspace's account "
        "groups and its metastore assignment",
    ]


def render_deletion_list(project: Project) -> str:
    lines = [f"destroy {project.project} deletes:"]
    lines += [f"  - {item}" for item in deletion_list(project)]
    lines.append(KEPT)
    return "\n".join(lines)


def _delete_batch(s3: Any, bucket: str, batch: list[dict[str, str]]) -> int:
    response = s3.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})
    errors = response.get("Errors") or []
    if errors:
        first = errors[0]
        raise RunError(
            f"cannot delete {len(errors)} object version(s) from s3://{bucket}: "
            f"{first.get('Code', 'unknown')} on {first.get('Key', '?')}; re-run destroy, or "
            "check the bucket policy still grants the apply role s3:DeleteObjectVersion"
        )
    return len(batch)


def empty_bucket(s3: Any, bucket: str, logger: Logger) -> int | None:
    """Delete every object version and delete marker in `bucket`, in batches of 1000.

    Returns how many were deleted, or None when the bucket no longer exists (a
    previous destroy already removed it). `s3` is a boto3 S3 client.
    """
    deleted = 0
    batch: list[dict[str, str]] = []
    try:
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
            for item in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]:
                batch.append({"Key": item["Key"], "VersionId": item["VersionId"]})
                if len(batch) == DELETE_BATCH:
                    deleted += _delete_batch(s3, bucket, batch)
                    batch = []
        if batch:
            deleted += _delete_batch(s3, bucket, batch)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "unknown")
        if code == "NoSuchBucket":
            logger.info("s3://%s does not exist; nothing to empty", bucket)
            return None
        raise RunError(f"cannot empty s3://{bucket}: {code}") from None
    except BotoCoreError as exc:
        raise RunError(f"cannot empty s3://{bucket}: {type(exc).__name__}") from None
    logger.info("deleted %d object versions from s3://%s", deleted, bucket)
    return deleted
