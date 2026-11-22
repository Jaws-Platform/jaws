"""The roles this repository's own workflows assume trust it under every name it has.

GitHub's OIDC subject contains the repository's name, so a rename changes the
subject of every token this repository's workflows present. The roles those
workflows assume (the foundation's, data-access's, the monitoring stack's, and
each project's plan and apply role) therefore take `repository_aliases`; the roles a consumer's
workflows assume (release, task, the sites' roles) trust another repository
and must not.

What an alias does to a trust policy is the library's test
(`github-oidc-role`). This file checks the wiring the foundation owns: which
module blocks pass the alias.
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


def test_the_roles_that_trust_this_repository_are_the_tools_own() -> None:
    trusting = {
        name
        for name, arguments in _role_modules().items()
        if arguments["repository"] == "local.context.repository"
    }
    assert trusting == TOOL_ROLES


def test_each_of_them_trusts_every_name_of_the_repository() -> None:
    modules = _role_modules()
    for name in sorted(TOOL_ROLES):
        assert modules[name].get("repository_aliases") == "local.context.repository_aliases", name
        # A transferred name is trusted under its new owner's ID, so the owner
        # IDs of the aliases travel with them.
        assert (
            modules[name].get("repository_alias_owner_ids")
            == "local.context.repository_alias_owner_ids"
        ), name


def test_roles_for_consumer_repositories_take_no_alias() -> None:
    others = {n: a for n, a in _role_modules().items() if n not in TOOL_ROLES}
    assert others, "the foundation has release, task and site roles"
    for name, arguments in others.items():
        assert "repository_aliases" not in arguments, name
        assert "repository_alias_owner_ids" not in arguments, name


def test_every_alias_owner_id_belongs_to_an_alias() -> None:
    context = (FOUNDATION / "context.tf").read_text()
    aliases = re.search(r"repository_aliases\s*=\s*\[(?P<list>[^\]]*)\]", context)
    owner_ids = re.search(r"repository_alias_owner_ids\s*=\s*\{(?P<map>[^}]*)\}", context)
    assert aliases and owner_ids
    alias_names = set(re.findall(r'"([^"]+)"', aliases["list"]))
    owner_id_names = set(re.findall(r'"([^"]+)"\s*=', owner_ids["map"]))
    assert owner_id_names <= alias_names
