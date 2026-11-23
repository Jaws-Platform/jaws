"""Each root's backend file names the owner's state bucket."""

from __future__ import annotations

from jaws.settings import load_settings
from tests.conftest import PLATFORM_CONFIG_DIR, REPO_ROOT


def _backend(root: str) -> str:
    return (REPO_ROOT / root / "backend" / "prod.hcl").read_text()


def _management_bucket() -> str:
    accounts = load_settings(PLATFORM_CONFIG_DIR, environ={}).aws.accounts.values()
    management = next(a for a in accounts if a.type == "management")
    return f"jaws-owner-access-state-{management.account_id}"


def test_the_monitoring_state_is_in_the_shared_bucket() -> None:
    settings = load_settings(PLATFORM_CONFIG_DIR, environ={})
    assert f'bucket       = "{settings.state.bucket}"' in _backend("monitoring")


def test_owner_access_and_billing_export_state_is_in_the_management_accounts_bucket() -> None:
    shared = load_settings(PLATFORM_CONFIG_DIR, environ={}).state.bucket
    for root in ("owner-access", "billing-export"):
        backend = _backend(root)
        assert f'bucket       = "{_management_bucket()}"' in backend, root
        assert shared not in backend, f"{root}: never the shared state bucket, which CI reaches"
