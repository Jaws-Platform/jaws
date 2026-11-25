"""The monitoring stack (monitoring/) agrees with the CLI and owns its names.

The stack is named `<name_root>-monitoring`, its CI roles are
`<name_root>-monitoring-ci-*` and its state is the `monitoring` key of
config/terraform.yaml's key template: a project registered under the key
`monitoring` would share all three. What the stack reads is what the CLI
writes: the owner's secrets under `monitoring_secrets_prefix`, and the task-run
records under `run_records.PREFIX`, joined on `run_records.JOIN_TAGS`.
"""

from __future__ import annotations

import re

from jaws import run_records
from jaws.settings import load_settings, monitoring_secrets_prefix
from tests.conftest import CONFIG_DIR, REPO_ROOT, onboarded, repo_config

STACK = REPO_ROOT / "monitoring"
RESERVED = "monitoring"


def _main() -> str:
    return (STACK / "main.tf").read_text()


def test_no_project_is_registered_under_the_monitoring_key() -> None:
    assert RESERVED not in onboarded(repo_config()), (
        f"`{RESERVED}` is reserved: its roles and state prefix would be the monitoring stack's"
    )


def test_the_state_key_follows_the_key_template() -> None:
    settings = load_settings(CONFIG_DIR, environ={})
    backend = (STACK / "backend" / "prod.hcl").read_text()
    key = settings.state.key_template.format(project=RESERVED, environment="prod")
    assert f'key          = "{key}"' in backend
    assert sorted(p.name for p in (STACK / "backend").iterdir()) == ["prod.hcl"]


def test_the_stack_reads_the_secrets_where_the_cli_writes_them() -> None:
    assert f'secrets_prefix = "{monitoring_secrets_prefix("${local.name_root}")}"' in _main()


def test_the_stack_reads_the_task_records_where_the_cli_writes_them() -> None:
    main = _main()
    assert f'prefixes  = ["{run_records.PREFIX}"]' in main
    tags = ", ".join(f'"{tag}"' for tag in run_records.JOIN_TAGS)
    assert f"join_tags = [{tags}]" in main


def test_the_stack_is_named_for_the_name_root() -> None:
    assert re.search(r'name\s*=\s*"\$\{local\.name_root\}-monitoring"', _main())


def test_the_platform_s_own_project_is_its_name_root() -> None:
    """The foundation's Project tag, and the shared host's usage, are the name root's."""
    context = (REPO_ROOT / "foundation" / "context.tf").read_text()
    assert re.search(r"^\s+project\s+= local\.account\.context\.name_root$", context, re.MULTILINE)
    assert '{ "${local.name_root}-shared" = local.name_root }' in _main()
