# The tool configuration

Everything about how jaws runs, the accounts it knows and the projects it
serves, as opposed to what one project is (that lives in each project
repository's `jaws.yaml`). The CLI, the foundation and the workflows read these
files as **one document**: each file holds some of its top-level sections, and
a section lives in exactly one file. Both the CLI and the foundation refuse a
section defined twice, and a `.yml` file instead of skipping it.

| File | Sections | What it holds |
| --- | --- | --- |
| [`projects.yaml`](projects.yaml) | `projects` | Every onboarded project, grouped by its GitHub owner: its type, repository, and what it is approved for |
| [`aws.yaml`](aws.yaml) | `aws` | The account registry: every account by type, and `primary`, the one jaws builds in |
| [`terraform.yaml`](terraform.yaml) | `state` | The state bucket and key template |
| [`tool.yaml`](tool.yaml) | `context`, `ecr` | The name root, the Organization tag of jaws's own stacks, the owner and the ManagedBy tag, the CLI's image repository |
| [`sites.yaml`](sites.yaml) | `dns` | The hosted zone sites live in |
| [`bots.yaml`](bots.yaml) | `bot`, `tasks` | How a bot instance runs, and how remote tasks run and what any task may ask for |
| [`databricks.yaml`](databricks.yaml) | `databricks` | The Databricks account, its service principal, the metastore and the compute policies |
| [`monitoring.yaml`](monitoring.yaml) | `monitoring` | The monitoring node (type, image, name, snapshots, off-hours), the billing bucket and its providers, budgets, and the Slack channels and routes for alerts |

Which file holds a section is organisation only. Workflows and scripts read a
few sections from their file with `yq` (`aws`, `projects`, `ecr`,
`databricks`), so move a section only with its readers;
`tests/test_settings.py` pins the layout.

The Terraform version and the module family versions are the release's
(`src/jaws/product.yaml`), not this directory's. The product's defaults for
logging, timeouts, cache headers and the bot health check apply unless a
section here overrides them. An override goes in the section's file: `tool` in
`tool.yaml`, `terraform` (timeouts) in `terraform.yaml`, `sync` in `sites.yaml`,
`bot.health_*` in `bots.yaml`; a new section also goes in `SECTION_FILES` in
`tests/test_settings.py`.

## Onboarding a project

A project is onboarded with one reviewed change to [`projects.yaml`](projects.yaml):
an entry under the GitHub organization or user that owns its repository (add
the owner, with its numeric `owner_id`, if it is new):

```yaml
projects:
  Braveheart-Chess:
    owner_id: "356866252"           # gh api users/Braveheart-Chess --jq .id
    projects:
      braveheart-trainer:
        description: The trainer for Braveheart's NNUE nets, with bullet on GPU instances
        type: research              # site | bot | research | databricks
        repository: braveheart-trainer
        repository_id: "1459456509" # gh api repos/Braveheart-Chess/braveheart-trainer --jq .id
        instance_types: [c8a.xlarge, g6.xlarge]
        task_profiles: [cpu, gpu]
```

Its `type` decides what the foundation gives it:

| Type | Stack | Roles and resources |
| --- | --- | --- |
| `site` | site | A site bucket and plan, preview and apply roles; needs `domain` |
| `bot` | bot | Plan, apply and release roles, and a task role with `instance_types` |
| `research` | bot | Plan and apply roles (compute, not container) and a task role; no release role |
| `databricks` | databricks-account, databricks-workspace | Plan and apply roles; needs its `databricks` entry |

Nothing else changes: CI plans the new project's stack from this file, Bot
apply and Databricks apply look it up here, and the foundation apply of the
next release creates its roles. A project's own `jaws.yaml` can never widen
what its entry here approves.

## The accounts

[`aws.yaml`](aws.yaml) lists every account with its type (`management`,
`development`, `staging` or `production`). jaws builds only in `primary`; the
others are recorded for owner-access, which grants the owner admin access to
them. Projects choosing their environments from this registry is
[#294](https://github.com/Jaws-Platform/jaws/issues/294).

## Reading it elsewhere

```sh
uv run jaws config show                     # the effective configuration, as JSON
uv run jaws config env                      # the primary account's values, for a workflow
scripts/projects.sh bot research            # onboarded projects of some types, as JSON
uv run jaws --config path/to/config ...     # another configuration: a directory, or one file
```
