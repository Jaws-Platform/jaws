"""The roles this repository's own workflows assume trust `platform.repositories`.

GitHub's OIDC subject contains the repository's name, so a rename or a move
changes the subject of every token this repository's workflows present. The
roles those workflows assume (the foundation's, data-access's, the monitoring
stack's, and each project's plan and apply role) therefore trust the first of
`platform.repositories` and every further entry (`additional_repositories`);
a site's plan role also trusts the hub. The roles a consumer's workflows assume
(release, task, preview, a site's apply role) trust another repository and
must not.

What `additional_repositories` does to a trust policy is the library's test
(`github-oidc-role`). This file checks the wiring the foundation owns: which
module blocks pass it.
"""

from __future__ import annotations

import re

from tests.conftest import REPO_ROOT

FOUNDATION = REPO_ROOT / "foundation"
_MODULE = re.compile(r'^module "(?P<name>\w+)" \{\n(?P<body>.*?)^\}', re.MULTILINE | re.DOTALL)
_ARGUMENT = re.compile(r"^  (?P<key>\w+)\s*=\s*(?P<value>.+)$", re.MULTILINE)
_ROLE_SOURCE = re.compile(r'//modules/ci-(plan|apply|preview|release|task)-role"$')

#: The role modules whose roles this repository's own workflows assume.
TOOL_ROLES = {
    "infra_ci_plan",
    "infra_ci_apply",
    "data_access_ci_plan",
    "data_access_ci_apply",
    "monitoring_ci_plan",
    "monitoring_ci_apply",
    "bot_ci_plan",
    "bot_ci_apply",
    "databricks_ci_plan",
    "databricks_ci_apply",
}


def _role_modules() -> dict[str, dict[str, str]]:
    """Every CI role module block in the foundation: name -> its top-level arguments."""
    modules: dict[str, dict[str, str]] = {}
    for path in sorted(FOUNDATION.glob("*.tf")):
        for match in _MODULE.finditer(path.read_text()):
            arguments = {m["key"]: m["value"].strip() for m in _ARGUMENT.finditer(match["body"])}
            if _ROLE_SOURCE.search(arguments.get("source", "")):
                assert match["name"] not in modules, match["name"]
                modules[match["name"]] = arguments
    return modules


def test_the_roles_that_trust_the_platform_s_repositories_are_the_tools_own() -> None:
    trusting = {
        name
        for name, arguments in _role_modules().items()
        if arguments.get("repository") == "local.platform_trust.repository"
    }
    assert trusting == TOOL_ROLES


def test_each_of_them_trusts_every_platform_repository() -> None:
    modules = _role_modules()
    for name in sorted(TOOL_ROLES):
        assert modules[name].get("owner_id") == "local.platform_trust.owner_id", name
        assert modules[name].get("repository_id") == "local.platform_trust.repository_id", name
        assert (
            modules[name].get("additional_repositories")
            == "local.platform_trust.additional_repositories"
        ), name
        assert "repository_aliases" not in modules[name], name
        assert "repository_alias_owner_ids" not in modules[name], name


def test_a_site_plan_role_also_trusts_the_hub() -> None:
    assert _role_modules()["site_ci_plan"].get("additional_repositories") == "local.hub_trust"


def test_other_roles_trust_only_their_own_repository() -> None:
    others = {
        n: a for n, a in _role_modules().items() if n not in TOOL_ROLES and n != "site_ci_plan"
    }
    assert others, "the foundation has release, task and site roles"
    for name, arguments in others.items():
        assert "additional_repositories" not in arguments, name
        assert "repository_aliases" not in arguments, name
        assert "repository_alias_owner_ids" not in arguments, name
