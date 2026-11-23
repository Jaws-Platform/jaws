"""The bot and research projects of the onboarding registry (config/projects.yaml),
the foundation that serves them, the workflows that plan and apply them, and their
project files agree."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from jaws.site import load_site_config
from tests.conftest import FIXTURES, REPO_ROOT, onboarded, repo_config

BOTS_TF = REPO_ROOT / "foundation" / "bots.tf"
PROJECTS_YAML = REPO_ROOT / "config" / "projects.yaml"
#: Each registered project's file, as its repository commits it.
REGISTRY_FILES = FIXTURES / "registry"
#: The Braveheart-Chess organisation: gh api orgs/Braveheart-Chess --jq .id
BRAVEHEART_CHESS = "356866252"


#: Projects registered after the management account was retired (v0.70.0): they
#: have only ever had a stack in production, so nothing is approved under the
#: management account's name for them.
def _onboarded(*types: str) -> dict[str, dict[str, Any]]:
    """The registry's projects of `types`, each with its `owner` and `owner_id`."""
    return {
        key: {**project, "owner": owner, "owner_id": group["owner_id"]}
        for owner, group in repo_config()["projects"].items()
        for key, project in group["projects"].items()
        if project["type"] in types
    }


def registry() -> dict[str, tuple[str, str]]:
    """The bot and research projects: each one's repository and repository ID."""
    return {
        key: (f"{p['owner']}/{p['repository']}", p["repository_id"])
        for key, p in _onboarded("bot", "research").items()
    }


def owners() -> dict[str, str]:
    """Each bot and research project's `owner_id`: its GitHub owner's."""
    return {key: p["owner_id"] for key, p in _onboarded("bot", "research").items()}


def project_file(project: str) -> dict[str, Any]:
    """tests/fixtures/registry/<project>.yaml, a copy of the project file as the
    registered repository commits it (tests/fixtures/bots/ holds samples)."""
    import yaml

    path = REGISTRY_FILES / f"{project}.yaml"
    assert path.is_file(), f"{project} is registered: add its project file as {path.name}"
    raw: dict[str, Any] = yaml.safe_load(path.read_text())
    return raw


def test_registry_lists_braveheart() -> None:
    assert registry() == {
        "braveheart": ("Braveheart-Chess/braveheart", "1435162673"),
        # The engine's Lichess bot, deployed from its own repository since 2026-11-15.
        "braveheart-bot": ("Braveheart-Chess/braveheart-lichess-bot", "1459279608"),
        # The self-play dataset and the trainer, split from the engine on 2026-11-16.
        "braveheart-selfplay": ("Braveheart-Chess/braveheart-selfplay", "1459456470"),
        "braveheart-trainer": ("Braveheart-Chess/braveheart-trainer", "1459456509"),
        # Pi's benchmark files, a dataset alone, registered on 2026-11-21.
        "pi-benchmarks": ("Pi-Mathematical-Reasoning/pi-benchmarks", "1466231955"),
        # Pi's own resources, from the pi repository, registered on 2026-11-21.
        "pi-prover": ("Pi-Mathematical-Reasoning/pi", "1466017315"),
        # The cold archive of the deprecated Prog Strength, registered on 2026-11-21.
        "prog-strength-archive": ("Prog-Strength/prog-strength-archive", "1466937166"),
    }
    # The engine's project was `rusty-chess` until 2026-11-15; the old name is gone.
    assert "rusty-chess" not in PROJECTS_YAML.read_text()


#: The longest project key whose apply role's container/manage policy fits IAM's
#: 6,144-character cap on a managed policy. That policy names the project in 17
#: ARNs and is 6,043 characters for the 10-character `braveheart`, so each extra
#: character costs 17: 15 characters make about 6,128. `braveheart-lichess-bot`
#: (22) failed the v0.30.0 foundation apply with LimitExceeded.
MAX_PROJECT_KEY = 15
#: A research project gets compute/* instead of container/*, and its largest
#: policies are far from the cap. Measured with the library's ci-policies module
#: on 2026-11-16 (role, policy: characters): at 19 characters (`braveheart-selfplay`)
#: apply compute/manage 3,910 and task task/launch 4,052; at 27 characters with all
#: six task profiles, 3,990 and 4,461. So the 30 a project name allows fits.
MAX_RESEARCH_PROJECT_KEY = 30


def test_registered_projects_fit_the_apply_policy_size() -> None:
    research = _research_projects()
    for project in registry():
        limit = MAX_RESEARCH_PROJECT_KEY if project in research else MAX_PROJECT_KEY
        assert len(project) <= limit, f"{project} is {len(project)} characters; " + (
            f"a research project's policies are measured to fit up to {MAX_RESEARCH_PROJECT_KEY}"
            if project in research
            else "its ci-apply container/manage policy would exceed IAM's "
            f"6,144-character limit (keep bot keys to {MAX_PROJECT_KEY})"
        )


def test_the_long_research_keys_are_research_projects() -> None:
    # The 15-character limit binds every key that is not a research project.
    long_keys = {p for p in registry() if len(p) > MAX_PROJECT_KEY}
    assert long_keys == {"braveheart-selfplay", "braveheart-trainer", "prog-strength-archive"}
    assert long_keys <= _research_projects()


def test_every_repository_is_trusted_with_its_owners_id() -> None:
    """The release and task roles trust `repo:<owner>@<owner_id>/...`: each project's
    owner ID is its GitHub owner's, stated once for the owner in config/projects.yaml."""
    assert owners()["braveheart"] == BRAVEHEART_CHESS
    assert repo_config()["projects"]["Braveheart-Chess"]["owner_id"] == BRAVEHEART_CHESS
    assert all(re.fullmatch(r"[0-9]+", owner_id) for owner_id in owners().values())
    release, task = _module("bot_ci_release"), _module("bot_ci_task")
    assert "owner_id          = each.value.owner_id" in release
    assert "owner_id          = local.bots[each.key].owner_id" in task
    # The plan and apply roles are assumed from this repository, whoever owns the bot's.
    for name in ("bot_ci_plan", "bot_ci_apply"):
        assert re.search(r"^  owner_id += local\.platform_trust\.owner_id$", _module(name), re.M), (
            name
        )
    assert "github_owner_id" not in BOTS_TF.read_text()


def test_bot_apply_reads_the_project_file_from_a_ref_and_refuses_another_project() -> None:
    apply: dict[Any, Any] = _yaml(".github/workflows/bot-apply.yml")
    ref = apply[True]["workflow_dispatch"]["inputs"]["consumer-ref"]
    assert ref["required"] is False and ref["default"] == ""
    steps = apply["jobs"]["apply"]["steps"]
    checkout = next(s for s in steps if s.get("with", {}).get("path") == ".consumer")
    assert checkout["with"]["ref"] == "${{ inputs.consumer-ref }}"
    names = [s.get("name", "") for s in steps]
    refuse = names.index("Refuse a project file that names another project")
    run = next(i for i, s in enumerate(steps) if "$COMMAND" in s.get("run", ""))
    assert refuse < run
    assert "exit 1" in steps[refuse]["run"]


def test_bot_plan_skips_an_entry_the_project_file_does_not_name() -> None:
    ci: dict[Any, Any] = _yaml(".github/workflows/ci.yml")
    steps = ci["jobs"]["bot-plan"]["steps"]
    by_id = {s["id"]: s for s in steps if "id" in s}
    assert "matches=false" in by_id["file"]["run"] and "::warning::" in by_id["file"]["run"]
    assert by_id["assume"]["if"] == "steps.file.outputs.matches == 'true'"
    ids = [s.get("id") for s in steps]
    assert ids.index("file") < ids.index("assume")
    # A skipped assume is not "the roles do not exist yet".
    notice = next(s for s in steps if s.get("name") == "Skip the plan until the bot's roles exist")
    assert notice["if"] == (
        "steps.file.outputs.matches == 'true' && steps.assume.outcome != 'success'"
    )


def test_registry_matches_each_projects_file() -> None:
    for project, (repository, _) in registry().items():
        file = project_file(project)
        assert (file["project"], file["repository"]) == (project, repository)


def test_bot_state_prefixes_are_in_the_state_bucket_policy() -> None:
    state = (REPO_ROOT / "foundation" / "state.tf").read_text()
    assert "local.bots" in state and "project=${key}/" in state
    assert "module.bot_ci_plan[key].role_arn" in state
    assert "module.bot_ci_apply[key].role_arn" in state


def _yaml(path: str) -> dict[Any, Any]:
    """A workflow as data. PyYAML reads the bare `on:` key as True, hence Any keys."""
    import yaml

    data: dict[Any, Any] = yaml.safe_load((REPO_ROOT / path).read_text())
    return data


def _listed(*types: str) -> list[dict[str, str]]:
    import json

    out = subprocess.run(
        ["scripts/projects.sh", *types], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    listed: list[dict[str, str]] = json.loads(out.stdout)
    return listed


def test_the_workflows_take_every_bot_from_the_registry() -> None:
    """Onboarding a bot or research project is one change to config/projects.yaml:
    the plan matrix and the apply lookup both read it through scripts/projects.sh."""
    assert {e["project"]: e["repository"] for e in _listed("bot", "research")} == {
        k: r for k, (r, _) in registry().items()
    }
    ci: dict[Any, Any] = _yaml(".github/workflows/ci.yml")
    lister = ci["jobs"]["bot-projects"]
    assert "scripts/projects.sh bot research" in lister["steps"][-1]["run"]
    plan = ci["jobs"]["bot-plan"]
    assert plan["needs"] == ["terraform-static", "bot-projects"]
    assert plan["strategy"]["matrix"] == {
        "include": "${{ fromJSON(needs.bot-projects.outputs.projects) }}"
    }
    apply: dict[Any, Any] = _yaml(".github/workflows/bot-apply.yml")
    # PyYAML reads the bare `on:` key as True. A string, not a choice: no list to keep.
    assert apply[True]["workflow_dispatch"]["inputs"]["project"]["type"] == "string"
    lookup = next(s for s in apply["jobs"]["apply"]["steps"] if s.get("id") == "bot")
    assert "scripts/projects.sh bot research" in lookup["run"]


@pytest.mark.parametrize(
    ("project", "repository"),
    [
        ("braveheart-bot", "Braveheart-Chess/braveheart-lichess-bot"),
        ("main-site", None),
        ("nope", None),
    ],
    ids=["a-bot", "a-site", "unknown"],
)
def test_bot_apply_looks_up_only_bot_and_research_projects(
    tmp_path: Path, project: str, repository: str | None
) -> None:
    apply: dict[Any, Any] = _yaml(".github/workflows/bot-apply.yml")
    lookup = next(s for s in apply["jobs"]["apply"]["steps"] if s.get("id") == "bot")
    output = tmp_path / "out"
    result = subprocess.run(
        ["bash", "-e", "-c", lookup["run"]],
        cwd=REPO_ROOT,
        env={**os.environ, "PROJECT": project, "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        check=False,
    )
    if repository is None:
        assert result.returncode != 0
        assert (
            f"{project} is not a bot or research project in config/projects.yaml" in result.stdout
        )
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert output.read_text().splitlines() == [f"repository={repository}"]


def test_bot_plan_and_apply_use_the_bots_roles() -> None:
    ci = (REPO_ROOT / ".github/workflows/ci.yml").read_text()
    apply = (REPO_ROOT / ".github/workflows/bot-apply.yml").read_text()
    assert ':role/${name_root}-${PROJECT}-ci-plan"' in ci
    assert ':role/${name_root}-${PROJECT}-ci-apply"' in apply
    assert "environment:" in apply and "name: prod" in apply


def test_container_release_runs_this_commit_and_pins_nothing() -> None:
    text = (REPO_ROOT / ".github/workflows/container-release.yml").read_text()
    assert "ref: ${{ job.workflow_sha }}" in text
    assert "@v0." not in text and "x-release-please-version" not in text
    assert 'bot reconcile "${version_args[@]}"' in text
    assert 'version_args=(--version "$VERSION")' in text
    assert "--config .jaws-tool/config " in text
    release: dict[Any, Any] = _yaml(".github/workflows/container-release.yml")
    assert release["permissions"] == {}
    job = release["jobs"]["release"]
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert release["concurrency"]["cancel-in-progress"] is False
    assert set(release[True]["workflow_call"]["inputs"]) == {
        "project",
        "version",
        "release-role-arn",
        "debug",
    }


WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def test_no_workflow_needs_account_or_role_variables() -> None:
    """Role ARNs are derived from the primary account (config/aws.yaml) and the project name."""
    for path in WORKFLOWS_DIR.glob("*.yml"):
        text = path.read_text()
        assert "vars.AWS_ACCOUNT_ID" not in text, path.name
        assert "AWS_RELEASE_ROLE_ARN" not in text, path.name


def test_container_release_role_is_optional() -> None:
    release: dict[Any, Any] = _yaml(".github/workflows/container-release.yml")
    role = release[True]["workflow_call"]["inputs"]["release-role-arn"]
    assert role["required"] is False
    assert role["default"] == ""


def test_bot_plan_runs_without_a_variable_and_skips_until_roles_exist() -> None:
    ci: dict[Any, Any] = _yaml(".github/workflows/ci.yml")
    job = ci["jobs"]["bot-plan"]
    # No repository variable gates the job; it waits only for a non-empty registry.
    assert job["if"] == "needs.bot-projects.outputs.projects != '[]'"
    steps = {s.get("id"): s for s in job["steps"] if "id" in s}
    assert steps["assume"]["continue-on-error"] is True
    # The steps that run the CLI (not the one that only reads the project file's name).
    # Every command that needs the role; `config env` runs before it, to name it.
    gated = [
        s
        for s in job["steps"]
        if "uv run jaws" in str(s.get("run", "")) and "config env" not in s["run"]
    ]
    assert gated and all("steps.assume.outcome == 'success'" in s["if"] for s in gated)


def test_foundation_takes_the_account_from_config() -> None:
    state = (REPO_ROOT / "foundation" / "state.tf").read_text()
    assert "570327089884" not in state
    assert "local.account_id" in state


def _module(name: str, path: Path = BOTS_TF) -> str:
    """The text of one module block in a foundation file (bots.tf by default)."""
    text = path.read_text()
    match = re.search(rf'^module "{name}" \{{\n(.*?)^\}}', text, re.MULTILINE | re.DOTALL)
    assert match, f"module {name} not found in {path.name}"
    return match.group(1)


_RESEARCH_CHOICE = re.compile(
    r"^\s*policies\s*=\s*concat\(\s*contains\(local\.research_projects, each\.key\)"
    r"\s*\?\s*\[([^\]]*)\]\s*:\s*\[([^\]]*)\]",
    re.MULTILINE,
)


def _research_policies(block: str) -> list[str]:
    """The base policies when the project is a research project."""
    match = _RESEARCH_CHOICE.search(block)
    assert match, "the role does not choose its base policies by research_projects"
    return re.findall(r'"([^"]+)"', match.group(1))


def _policies(block: str) -> list[str]:
    # A role choosing by kind: what a bot gets.
    choice = _RESEARCH_CHOICE.search(block)
    if choice:
        return re.findall(r'"([^"]+)"', choice.group(2))
    # The first list: the policies every bot gets, before any concat()ed extras.
    match = re.search(r"^\s*policies\s*=\s*(?:concat\(\s*)?\[([^\]]*)\]", block, re.MULTILINE)
    assert match, "no policies list"
    return re.findall(r'"([^"]+)"', match.group(1))


def _projects() -> dict[str, Any]:
    """Every onboarded project by key, with its reviewed guardrails (config/projects.yaml),
    as the foundation decodes it (local.registry)."""
    return onboarded(repo_config())


def _task_types() -> dict[str, list[str]]:
    return {k: list(p["instance_types"]) for k, p in _projects().items() if p.get("instance_types")}


def test_bot_plan_and_apply_carry_the_task_policies() -> None:
    assert "task/read" in _policies(_module("bot_ci_plan"))
    assert "task/manage" not in _policies(_module("bot_ci_plan"))
    assert {"task/read", "task/manage"} <= set(_policies(_module("bot_ci_apply")))


def test_task_role_is_the_launch_role_for_the_bot_repository() -> None:
    block = _module("bot_ci_task")
    assert 'source   = "Jaws-Platform/jaws-ci/aws//modules/ci-task-role"' in block
    # Every project with a task runner.
    assert "for_each = local.bot_task_types" in block
    assert "repository        = local.bots[each.key].repository" in block
    assert "repository_id     = local.bots[each.key].repository_id" in block
    assert _policies(block) == ["task/launch"]
    assert "instance_types = each.value" in block
    assert "profiles       = local.bot_task_profiles[each.key]" in block
    # With the billing bucket, the run records under the project's own prefix
    # (foundation/monitoring.tf local.task_records).
    assert 'contains(keys(local.task_records), each.key) ? ["task/records"] : []' in block
    assert "records        = lookup(local.task_records, each.key, null)" in block
    # No subjects override: the module's default trusts pull_request and main only.
    assert "subjects" not in block


def _task_runners() -> dict[str, dict[str, Any]]:
    """Each registered project's task-runner component, if it has one."""
    runners: dict[str, dict[str, Any]] = {}
    for project in registry():
        for component in project_file(project)["components"]:
            if component["kind"] == "task-runner":
                runners[project] = component
    return runners


def _instance_types(runner: dict[str, Any]) -> list[str]:
    expected = list(runner["instance_types"])
    for profile in runner.get("profiles", {}).values():
        expected += [t for t in profile["instance_types"] if t not in expected]
    return expected


def test_task_instance_types_match_the_project_files() -> None:
    expected = {project: _instance_types(runner) for project, runner in _task_runners().items()}
    assert "braveheart" in expected
    assert _task_types() == expected
    assert set(_task_types()) <= set(registry())


def _task_profiles() -> dict[str, list[str]]:
    return {k: list(p["task_profiles"]) for k, p in _projects().items() if p.get("task_profiles")}


def test_task_profiles_match_the_project_files() -> None:
    expected = {
        project: ["cpu", *runner.get("profiles", {})] for project, runner in _task_runners().items()
    }
    assert "braveheart" in expected
    assert _task_profiles() == expected
    assert set(_task_profiles()) == set(_task_types())


def test_bots_output_names_the_task_role() -> None:
    outputs = (REPO_ROOT / "foundation" / "outputs.tf").read_text()
    assert "task_role_arn" in outputs and "module.bot_ci_task[key].role_arn" in outputs


def _bot_datasets() -> dict[str, list[str]]:
    return {k: list(p["datasets"]) for k, p in _projects().items() if p.get("datasets")}


def test_dataset_buckets_match_the_project_files() -> None:
    expected = {}
    for project in registry():
        components = project_file(project)["components"]
        names = [c["name"] for c in components if c["kind"] == "dataset"]
        # Approved under the name root: <name_root>-<project>-<name>.
        buckets = [f"jaws-{project}-{name}" for name in names]
        if buckets:
            expected[project] = buckets
    # The engine gave its dataset up at the split's cutover; the data is the satellites'.
    assert "braveheart" not in expected
    assert {"braveheart-selfplay", "braveheart-trainer"} <= set(expected)
    assert {k: sorted(v) for k, v in _bot_datasets().items()} == {
        k: sorted(v) for k, v in expected.items()
    }
    assert set(_bot_datasets()) <= set(registry())


def test_bot_plan_and_apply_carry_the_dataset_policies() -> None:
    plan, apply = _module("bot_ci_plan"), _module("bot_ci_apply")
    assert '["dataset/read"]' in plan and "dataset/manage" not in plan
    assert '["dataset/read", "dataset/manage"]' in apply
    for block in (plan, apply):
        assert "contains(keys(local.bot_datasets), each.key)" in block
        assert "bucket_names = local.bot_datasets[each.key]" in block


def test_foundation_reads_lists_from_config() -> None:
    text = BOTS_TF.read_text()
    assert not re.search(r"\b(?:c8a|g6e?|p[345])\.\w+", text), (
        "instance types live in config/projects.yaml"
    )
    for name in ("bot_task_types", "bot_task_profiles", "bot_datasets"):
        match = re.search(rf"^\s+{name}\s*=\s*(.*)$", text, re.MULTILINE)
        assert match, name
        # bot_datasets is the per-account selection of bot_dataset_names, which reads config.
        source = "local.bot_dataset_names" if name == "bot_datasets" else "local.registry"
        assert source in match.group(1), name
    assert re.search(r"bot_dataset_names = \{\s*for k, p in local\.registry", text)
    # Only bot and research projects are approved for tasks or datasets.
    approved = {
        k
        for k, p in _projects().items()
        if set(p) & {"instance_types", "task_profiles", "datasets"}
    }
    assert approved <= set(registry())
    assert set(_task_profiles()) == set(_task_types())


def test_the_foundation_takes_its_bots_from_the_registry() -> None:
    text = BOTS_TF.read_text()
    assert re.search(
        r"bots = \{\s*for key, project in local\.registry : key => \{.*?\} "
        r'if contains\(\["bot", "research"\], project\.type\)',
        text,
        re.S,
    )
    assert (
        "research_projects = toset([for key, project in local.registry : "
        'key if project.type == "research"])'
    ) in text


def _research_projects() -> set[str]:
    """The research projects (type research in config/projects.yaml)."""
    return set(_onboarded("research"))


def test_research_projects_are_registered() -> None:
    assert _research_projects() <= set(registry())


def test_research_projects_are_exactly_the_files_of_that_kind() -> None:
    """A file of the wrong kind would get the wrong policies: compute/* or container/*."""
    research = {
        project
        for project in registry()
        if load_site_config(REGISTRY_FILES / f"{project}.yaml").kind == "research"
    }
    assert _research_projects() == research


def test_foundation_gives_research_projects_no_release_role() -> None:
    match = re.search(r"^\s*for_each\s*=\s*(.+)$", _module("bot_ci_release"), re.MULTILINE)
    assert match, "bot_ci_release has no for_each"
    comprehension = re.fullmatch(
        r"\{\s*for (\w+), (\w+) in local\.bots\s*:\s*\1\s*=>\s*\2\s*"
        r"if !contains\(local\.research_projects,\s*\1\)\s*\}",
        match.group(1).strip(),
    )
    assert comprehension, f"for_each must filter research out, keeping keys: {match.group(1)}"


def test_foundation_gives_research_projects_compute_and_bots_container() -> None:
    plan, apply = _module("bot_ci_plan"), _module("bot_ci_apply")
    # Same order as before research existed: reordering would churn braveheart's attachments.
    assert _policies(plan) == ["tfstate/read", "container/read", "task/read"]
    assert _research_policies(plan) == ["tfstate/read", "compute/read", "task/read"]
    # container/schedule is appended, not inserted, for the same reason; it is its
    # own policy because container/manage is near IAM's 6,144-character limit.
    assert _policies(apply) == [
        "tfstate/write",
        "container/read",
        "container/manage",
        "task/read",
        "task/manage",
        "container/schedule",
    ]
    assert _research_policies(apply) == [
        "tfstate/write",
        "compute/read",
        "compute/manage",
        "task/read",
        "task/manage",
    ]


def test_outputs_do_not_reach_for_a_research_projects_release_role() -> None:
    outputs = (REPO_ROOT / "foundation" / "outputs.tf").read_text()
    match = re.search(r"^\s*release_role_arn\s*=\s*(.+)$", outputs, re.MULTILINE)
    assert match
    assert match.group(1).strip() == (
        "contains(local.research_projects, key) ? null : module.bot_ci_release[key].role_arn"
    )
    # Plan and apply roles exist for every project, so the state policy needs no change.
    state = (REPO_ROOT / "foundation" / "state.tf").read_text()
    assert "bot_ci_release" not in state


# --- Databricks workspace projects (type databricks; foundation/databricks.tf) ---

DATABRICKS_TF = REPO_ROOT / "foundation" / "databricks.tf"
CI_ROLES_TF = REPO_ROOT / "foundation" / "ci-roles.tf"


def databricks_registry() -> dict[str, tuple[str, str]]:
    """The Databricks projects: each one's repository and repository ID."""
    return {
        key: (f"{p['owner']}/{p['repository']}", p["repository_id"])
        for key, p in _onboarded("databricks").items()
    }


def _squashed(text: str) -> str:
    """HCL with runs of spaces collapsed, so `terraform fmt` alignment does not matter."""
    return re.sub(r"[ \t]+", " ", text)


def _hcl_list(block: str, attribute: str) -> list[str]:
    match = re.search(rf"^\s*{attribute}\s*=\s*\[([^\]]*)\]", block, re.MULTILINE)
    assert match, f"no {attribute} list"
    return re.findall(r'"([^"]+)"', match.group(1))


def test_the_registered_databricks_projects() -> None:
    # repository_id is GitHub's numeric ID: gh api repos/<owner>/<repo> --jq .id
    assert databricks_registry() == {
        "braveheart-databricks": ("Braveheart-Chess/braveheart-databricks", "1458504699"),
    }


def test_every_databricks_project_has_numeric_repository_and_owner_ids() -> None:
    # owner_id: gh api repos/<owner>/<repo> --jq .owner.id. A deployer's
    # federation subject names both: repo:<owner>@<owner_id>/<name>@<repository_id>.
    assert {
        k: (p["repository_id"], p["owner_id"]) for k, p in _onboarded("databricks").items()
    } == {
        "braveheart-databricks": ("1458504699", "356866252"),
    }
    assert re.search(
        r"databricks_projects = \{\s*for key, project in local\.registry : key => \{.*?\} "
        r'if project\.type == "databricks"',
        DATABRICKS_TF.read_text(),
        re.S,
    )


def test_databricks_projects_are_not_bots_and_have_guardrails() -> None:
    projects = _projects()
    for key in databricks_registry():
        assert projects.get(key, {}).get("databricks"), f"projects.{key}.databricks is missing"
        assert key not in registry()
    text = DATABRICKS_TF.read_text()
    assert 'check "databricks_projects_have_guardrails"' in text
    assert "local.registry[key].databricks" in text


def test_databricks_projects_get_plan_and_apply_roles_with_databricks_policies() -> None:
    plan = _module("databricks_ci_plan", DATABRICKS_TF)
    apply = _module("databricks_ci_apply", DATABRICKS_TF)
    assert "modules/ci-plan-role" in plan and "modules/ci-apply-role" in apply
    for block in map(_squashed, (plan, apply)):
        assert "for_each = local.databricks_projects" in block
        # Planned and applied from this repository, as bots are.
        assert "repository = local.platform_trust.repository" in block
        assert "tfstate = local.databricks_ci[each.key].tfstate" in block
        assert "databricks = local.databricks_ci[each.key].databricks" in block
    assert _hcl_list(plan, "policies") == ["tfstate/read", "compute/read", "databricks/read"]
    assert _hcl_list(apply, "policies") == [
        "tfstate/write",
        "compute/read",
        "compute/manage",
        "databricks/read",
        "databricks/manage",
    ]
    assert 'environment = "prod"' in _squashed(apply)


def test_databricks_projects_get_no_release_or_task_role() -> None:
    text = DATABRICKS_TF.read_text()
    assert "ci-release-role" not in text and "ci-task-role" not in text
    # Only state.tf (the state prefixes) reads the registry outside databricks.tf.
    readers = {
        p.name
        for p in (REPO_ROOT / "foundation").glob("*.tf")
        if "databricks_projects" in p.read_text()
    }
    assert readers == {"databricks.tf", "state.tf"}


def test_databricks_policy_inputs_point_at_the_secret_and_the_projects_events() -> None:
    text = _squashed(DATABRICKS_TF.read_text())
    assert (
        'databricks_secret_parameter_arn = "arn:aws:ssm:${local.region}:${local.account_id}:'
        'parameter/${trimprefix(local.databricks.secret_parameter, "/")}"'
    ) in text
    assert (
        'databricks_events_arn_prefix = "arn:aws:s3:::${local.databricks.audit_bucket}/'
        '${trimsuffix(local.databricks.events_prefix, "/")}/"'
    ) in text
    assert 'events_object_arn = "${local.databricks_events_arn_prefix}project=${key}/*"' in text
    # One prefix covers both stacks' state keys (account and workspace).
    assert 'prefix = "project=${key}/"' in text


def test_databricks_project_state_prefixes_are_in_the_state_bucket_policy() -> None:
    state = (REPO_ROOT / "foundation" / "state.tf").read_text()
    assert "for key, project in local.databricks_projects" in state
    assert "module.databricks_ci_plan[key].role_arn" in state
    assert "module.databricks_ci_apply[key].role_arn" in state


def test_infra_roles_read_the_databricks_secret() -> None:
    plan, apply = _module("infra_ci_plan", CI_ROLES_TF), _module("infra_ci_apply", CI_ROLES_TF)
    assert _hcl_list(plan, "policies") == ["tfstate/read", "foundation/read", "databricks/read"]
    assert _hcl_list(apply, "policies") == [
        "tfstate/write",
        "foundation/read",
        "foundation/manage",
        "ecr/push",
        "databricks/read",
    ]
    for block in (plan, apply):
        assert "databricks = local.infra_ci.databricks" in _squashed(block)
    text = _squashed(CI_ROLES_TF.read_text())
    assert "secret_parameter_arn = local.databricks_secret_parameter_arn" in text
    assert 'events_object_arn = "${local.databricks_events_arn_prefix}project=infra/*"' in text


def test_databricks_account_resources_wait_for_enabled() -> None:
    text = DATABRICKS_TF.read_text()
    assert re.search(r"^\s+databricks_enabled\s*=\s*local\.databricks\.enabled$", text, re.M)
    for name in ("databricks_metastore", "databricks_audit_logs"):
        block = _squashed(_module(name, DATABRICKS_TF))
        assert "count = local.databricks_enabled ? 1 : 0" in block, name
        assert "databricks = databricks.account" in block, name
    metastore = _squashed(_module("databricks_metastore", DATABRICKS_TF))
    assert "admin_user_names = local.databricks.metastore_admins" in metastore
    assert "service_principal_application_id = local.databricks.client_id" in metastore
    assert "name = local.databricks.metastore_name" in metastore
    audit = _squashed(_module("databricks_audit_logs", DATABRICKS_TF))
    assert "account_id = local.databricks.account_id" in audit
    assert "bucket_name = local.databricks.audit_bucket" in audit
    # The foundation never creates the secret: the owner sets it with the CLI.
    assert "aws_ssm_parameter" not in text
    # Enabled: the foundation plan creates the metastore and the audit log delivery.
    assert yaml_config()["databricks"]["enabled"] is True


def test_the_shared_host_waits_for_the_metastore_module() -> None:
    """The host looks the admin group up by name (a data source). In a fresh
    account the group is created in the same apply, so the read must wait for
    the metastore module, or the first plan fails ("cannot find group")."""
    host = _squashed(_module("databricks_shared_host", DATABRICKS_TF))
    assert "depends_on = [module.databricks_metastore]" in host
    metastore = _squashed(_module("databricks_metastore", DATABRICKS_TF))
    assert 'admin_group_name = "${local.context.name_root}-metastore-admins"' in metastore


def yaml_config() -> dict[str, Any]:
    return repo_config()


def test_databricks_provider_authenticates_from_the_environment_only() -> None:
    providers = (REPO_ROOT / "foundation" / "providers.tf").read_text()
    match = re.search(r'^provider "databricks" \{\n(.*?)^\}', providers, re.M | re.S)
    assert match
    body = match.group(1)
    assert 'alias = "account"' in _squashed(body)
    assert 'auth_type = "oauth-m2m"' in _squashed(body)
    assert "client_secret" not in body and "client_id" not in body


def _reconcile_step() -> str:
    release: dict[Any, Any] = _yaml(".github/workflows/container-release.yml")
    steps = release["jobs"]["release"]["steps"]
    script: str = next(s["run"] for s in steps if s.get("name") == "jaws bot reconcile")
    return script


@pytest.mark.skipif(shutil.which("yq") is None, reason="needs yq, as on the GitHub runners")
@pytest.mark.parametrize(
    ("track", "version_input", "expected"),
    [
        ("latest-release", "", "bot reconcile --version v0.1.0"),
        ("pinned", "", "bot reconcile"),
        ("pinned", "v0.13.0", "bot reconcile --version v0.13.0"),
    ],
)
def test_container_release_passes_the_release_tag_unless_the_bot_is_pinned(
    tmp_path: Path, track: str, version_input: str, expected: str
) -> None:
    """A pinned bot's release tag is its own repository's, not an engine release."""
    (tmp_path / "jaws.yaml").write_text(
        f"components:\n  - kind: container-image\n  - kind: lichess-bot\n    track: {track}\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text('#!/usr/bin/env bash\necho "$@" > "$UV_LOG"\n')
    uv.chmod(0o755)
    log = tmp_path / "uv.log"
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        # As the job sets it: the version input, else the caller's release tag.
        "VERSION": version_input or "v0.1.0",
        "VERSION_INPUT": version_input,
        "DEBUG": "false",
        "UV_LOG": str(log),
    }
    subprocess.run(["bash", "-e", "-c", _reconcile_step()], cwd=tmp_path, env=env, check=True)
    assert log.read_text().strip().endswith(expected)
