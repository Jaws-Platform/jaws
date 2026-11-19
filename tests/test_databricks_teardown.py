"""scripts/databricks-teardown.sh: the one-time teardown of Databricks in management.

Fake `aws`, `terraform`, `uv` and `gh` on PATH record every call; nothing real is
touched. The script must refuse the wrong account and any step whose
predecessor is not done, change nothing on `plan`, destroy only after the
owner types `destroy`, release the bindings, grants and audit-log bucket from
state before destroying, destroy dependents first, and never print the secret.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml

from tests.conftest import REPO_ROOT, fixture_config

SCRIPT = REPO_ROOT / "scripts" / "databricks-teardown.sh"
SECRET = "s3cr3t-value-never-printed"

FAKE_AWS = r"""#!/usr/bin/env bash
echo "aws $*" >> "$FAKE_CALLS"
case "$1 $2" in
  "sts get-caller-identity")
    if [ "$AWS_PROFILE" = "$FAKE_PRODUCTION_PROFILE" ]; then echo 570327089884
    else echo "$FAKE_ACCOUNT"; fi ;;
  "s3 cp")
    key=${4#s3://*/}
    file="$FAKE_STATES/$(echo "$key" | tr '/=' '__')"
    [ -f "$file" ] && cat "$file" || exit 1 ;;
  "ssm get-parameter") echo "$FAKE_SECRET" ;;
  "ssm put-parameter") exit 0 ;;
  *) exit 0 ;;
esac
"""

# `state list` prints the fake state; `state rm` and `destroy -target` remove from it.
FAKE_TERRAFORM = r"""#!/usr/bin/env bash
echo "terraform $*" >> "$FAKE_CALLS"
drop() { # remove the lines matching (grep -F $1 $2) from the fake state
  grep -v $1 -F "$2" "$FAKE_STATE_LIST" > "$FAKE_STATE_LIST.t" || true
  mv "$FAKE_STATE_LIST.t" "$FAKE_STATE_LIST"
}
case "$1" in
  state)
    case "$2" in
      list) cat "$FAKE_STATE_LIST" ;;
      rm) shift 2; for a in "$@"; do case "$a" in -*) ;; *) drop -x "$a" ;; esac; done ;;
    esac ;;
  destroy)
    for a in "$@"; do case "$a" in -target=*) drop "" "${a#-target=}" ;; esac; done ;;
esac
exit 0
"""

FAKE_RECORDER = """#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$FAKE_CALLS"
[ "$1 $2" = "auth token" ] && echo fake-token
exit 0
"""

FOUNDATION_STATE = """\
module.databricks_audit_logs[0].aws_s3_bucket.this
module.databricks_audit_logs[0].aws_s3_bucket_policy.this
module.databricks_audit_logs[0].aws_s3_bucket_versioning.this
module.databricks_audit_logs[0].databricks_mws_log_delivery.audit
module.databricks_ci_plan["braveheart-databricks"].module.role.aws_iam_role.this
module.databricks_dataset["braveheart-selfplay-positions"].databricks_external_location.this
module.databricks_dataset["braveheart-selfplay-positions"].databricks_workspace_binding.location
module.databricks_metastore[0].databricks_metastore.this
module.databricks_shared_host[0].databricks_mws_workspaces.this
module.dataset_catalog_storage[0].databricks_grants.location
module.dataset_catalog_storage[0].databricks_workspace_binding.credential
module.producer_catalog["braveheart_selfplay"].databricks_catalog.this
module.producer_catalog["braveheart_selfplay"].databricks_workspace_binding.host
module.state_bucket.aws_s3_bucket.this
"""

STAGES = [
    "module.databricks_dataset",
    "module.producer_catalog",
    "module.dataset_catalog_storage",
    "module.databricks_shared_host",
    "module.databricks_audit_logs",
    "module.databricks_metastore",
]


def _root(tmp_path: Path, databricks_in_management: bool = True) -> Path:
    root = tmp_path / "checkout"
    for directory in ("scripts", "data-access", "foundation"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "scripts" / "databricks-credentials.sh", root / "scripts")
    config = fixture_config()
    databricks = config["databricks"]
    assert isinstance(databricks, dict)
    databricks["enabled"] = databricks_in_management
    (root / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    return root


def _state(tmp_path: Path, key: str, resources: int) -> None:
    states = tmp_path / "states"
    states.mkdir(exist_ok=True)
    managed = [{"mode": "managed", "type": "x", "name": str(i)} for i in range(resources)]
    (states / key.replace("/", "_").replace("=", "_")).write_text(
        json.dumps({"resources": managed})
    )


def _run(
    tmp_path: Path,
    *args: str,
    answer: str = "",
    account: str = "650503560686",
    root: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("aws", FAKE_AWS), ("terraform", FAKE_TERRAFORM)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    for name in ("uv", "gh"):
        (bin_dir / name).write_text(FAKE_RECORDER)
        (bin_dir / name).chmod(0o755)
    calls = tmp_path / "calls"
    calls.write_text("")
    state_list = tmp_path / "state-list"
    if not state_list.exists():
        state_list.write_text(FOUNDATION_STATE)
    (tmp_path / "states").mkdir(exist_ok=True)
    env = os.environ | {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "TEARDOWN_ROOT": str(root or _root(tmp_path)),
        "FAKE_CALLS": str(calls),
        "FAKE_ACCOUNT": account,
        "FAKE_PRODUCTION_PROFILE": "jaws-prod",
        "FAKE_STATES": str(tmp_path / "states"),
        "FAKE_STATE_LIST": str(state_list),
        "FAKE_SECRET": SECRET,
    }
    env.pop("GH_TOKEN", None)
    # The owner's shell, not a workflow step: CI itself runs with GITHUB_ACTIONS=true.
    env.pop("GITHUB_ACTIONS", None)
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        input=answer,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result, calls.read_text().splitlines()


def _terraform(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("terraform ")]


def test_it_refuses_another_account(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "foundation", "plan", account="570327089884")
    assert result.returncode != 0
    assert "not the management account" in result.stderr
    assert _terraform(calls) == []


def test_it_refuses_once_databricks_has_left_management(tmp_path: Path) -> None:
    root = _root(tmp_path, databricks_in_management=False)
    result, calls = _run(tmp_path, "access", "plan", root=root)
    assert result.returncode != 0
    assert "no longer enables Databricks" in result.stderr
    assert _terraform(calls) == []


def test_access_plan_changes_nothing(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "access", "plan")
    assert result.returncode == 0, result.stderr
    terraform = _terraform(calls)
    assert any(c.startswith("terraform plan -destroy") for c in terraform)
    assert not any(c.startswith("terraform apply") for c in terraform)


def test_access_go_destroys_only_after_the_owner_types_destroy(tmp_path: Path) -> None:
    refused, calls = _run(tmp_path, "access", "go", answer="yes\n")
    assert refused.returncode != 0
    assert not any(c.startswith("terraform apply") for c in _terraform(calls))
    done, calls = _run(tmp_path, "access", "go", answer="destroy\n")
    assert done.returncode == 0, done.stderr
    assert "terraform apply -input=false -lock-timeout=60s teardown.tfplan" in calls


def test_foundation_waits_for_the_data_access_stack(tmp_path: Path) -> None:
    _state(tmp_path, "project=data-access/env=prod/data-access-prod.tfstate", 3)
    result, calls = _run(tmp_path, "foundation", "plan")
    assert result.returncode != 0
    assert "data-access stack still holds resources" in result.stderr
    assert _terraform(calls) == []


def test_foundation_waits_for_every_workspace_project(tmp_path: Path) -> None:
    _state(
        tmp_path,
        "project=braveheart-databricks/env=prod/braveheart-databricks-prod-account.tfstate",
        5,
    )
    result, calls = _run(tmp_path, "foundation", "plan")
    assert result.returncode != 0
    assert "braveheart-databricks's account stack still holds resources" in result.stderr
    assert _terraform(calls) == []


def test_foundation_plan_changes_nothing(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "foundation", "plan")
    assert result.returncode == 0, result.stderr
    terraform = _terraform(calls)
    plan = next(c for c in terraform if c.startswith("terraform plan -destroy"))
    assert all(f"-target={stage}" in plan for stage in STAGES)
    assert "-var account=management" in plan
    assert not any(c.startswith(("terraform state rm", "terraform destroy")) for c in terraform)
    assert (tmp_path / "state-list").read_text() == FOUNDATION_STATE


def test_foundation_go_releases_then_destroys_dependents_first(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "foundation", "go", answer="destroy\n")
    assert result.returncode == 0, result.stderr
    terraform = _terraform(calls)
    (release,) = [c for c in terraform if c.startswith("terraform state rm")]
    for kept in (
        'module.databricks_dataset["braveheart-selfplay-positions"].databricks_workspace_binding.location',
        "module.dataset_catalog_storage[0].databricks_grants.location",
        "module.dataset_catalog_storage[0].databricks_workspace_binding.credential",
        'module.producer_catalog["braveheart_selfplay"].databricks_workspace_binding.host',
        "module.databricks_audit_logs[0].aws_s3_bucket.this",
        "module.databricks_audit_logs[0].aws_s3_bucket_policy.this",
        "module.databricks_audit_logs[0].aws_s3_bucket_versioning.this",
    ):
        assert kept in release, kept
    assert "databricks_mws_log_delivery" not in release
    destroys = [c for c in terraform if c.startswith("terraform destroy")]
    assert [d.split("-target=")[1] for d in destroys] == STAGES
    assert terraform.index(release) < terraform.index(destroys[0])
    left = (tmp_path / "state-list").read_text().splitlines()
    assert left == [
        'module.databricks_ci_plan["braveheart-databricks"].module.role.aws_iam_role.this',
        "module.state_bucket.aws_s3_bucket.this",
    ]


def test_a_re_run_targets_only_the_stages_still_in_state(tmp_path: Path) -> None:
    """After a stopped run, a stage whose resources are gone is not targeted: its
    dependencies may read through the shared host, which may be gone too."""
    (tmp_path / "state-list").write_text(
        "module.databricks_metastore[0].databricks_group.admins\n"
        "module.databricks_metastore[0].databricks_metastore.this\n"
        "module.state_bucket.aws_s3_bucket.this\n"
    )
    result, calls = _run(tmp_path, "foundation", "go", answer="destroy\n")
    assert result.returncode == 0, result.stderr
    terraform = _terraform(calls)
    plan = next(c for c in terraform if c.startswith("terraform plan -destroy"))
    assert "-target=module.databricks_metastore" in plan
    assert "module.databricks_dataset" not in plan and "module.databricks_shared_host" not in plan
    destroys = [c for c in terraform if c.startswith("terraform destroy")]
    assert [d.split("-target=")[1] for d in destroys] == ["module.databricks_metastore"]


def test_the_teardown_never_prints_the_secret(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "foundation", "plan")
    assert result.returncode == 0, result.stderr
    assert SECRET not in result.stdout + result.stderr


def test_foundation_go_without_confirmation_destroys_nothing(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "foundation", "go", answer="no\n")
    assert result.returncode != 0
    assert not any(
        c.startswith(("terraform state rm", "terraform destroy")) for c in _terraform(calls)
    )


def test_the_secret_is_copied_and_never_printed(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "secret")
    assert result.returncode == 0, result.stderr
    assert SECRET not in result.stdout + result.stderr
    reads = [c for c in calls if c.startswith("aws ssm get-parameter")]
    writes = [c for c in calls if c.startswith("aws ssm put-parameter")]
    assert reads and "/jwall-engineering/databricks/client-secret" in reads[0]
    assert writes and "--name /jaws/databricks/client-secret" in writes[0]
    assert "--type SecureString" in writes[0]


def test_without_a_step_it_prints_usage(tmp_path: Path) -> None:
    result, calls = _run(tmp_path)
    assert result.returncode == 2
    assert "access plan|go" in result.stderr and "foundation plan|go" in result.stderr
    assert calls == []
