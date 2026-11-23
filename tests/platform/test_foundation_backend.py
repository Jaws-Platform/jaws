"""The foundation's backend file names the owner's state bucket."""

from __future__ import annotations

from jaws.settings import load_settings
from tests.conftest import PLATFORM_CONFIG_DIR, REPO_ROOT


def test_the_backend_file_names_the_accounts_state_bucket() -> None:
    """`-backend-config=backend/prod.hcl` must point at the bucket config/terraform.yaml names."""
    settings = load_settings(PLATFORM_CONFIG_DIR, environ={})
    backend = (REPO_ROOT / "foundation" / "backend" / "prod.hcl").read_text()
    values = dict(
        (key.strip(), value.strip().strip('"'))
        for key, value in (line.split("=", 1) for line in backend.splitlines() if "=" in line)
    )
    assert values["bucket"] == settings.state.bucket
    assert values["region"] == settings.state.region
    assert values["key"] == "project=infra/env=prod/infra-prod.tfstate"
    assert sorted(p.name for p in (REPO_ROOT / "foundation" / "backend").iterdir()) == ["prod.hcl"]
