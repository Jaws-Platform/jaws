# Tagging

Every AWS resource jaws builds carries the same six tags. Each tag has exactly
one source, and nothing else may set it. Names and access never depend on the
`Organization` or `ManagedBy` tag, so changing either one retags resources in
place: nothing is renamed or replaced, and no access is granted or revoked.

## The six tags

| Tag | Value | Source | Set by |
| --- | --- | --- | --- |
| `Organization` | The GitHub organization or user that owns the project's repository, spelled as GitHub spells it, e.g. `Braveheart-Chess` or `jwallace145`. For jaws's own stacks it is `Jaws-Platform`. | For a project, the owner it is registered under in `config/projects.yaml`. For jaws's own stacks, `context.organization` in `config/tool.yaml`. | the tool |
| `ManagedBy` | `JAWS` | `context.managed_by` in `config/tool.yaml` | the tool |
| `Project` | The project's key, e.g. `braveheart-bot`. `jaws` for the foundation. | the project file, cross-checked against `project` | the project file |
| `Environment` | `prod` | the project file, cross-checked | the project file |
| `Repository` | The project's `owner/repo` | the project file, cross-checked against `repository` | the project file |
| `Owner` | The person responsible, e.g. `jwallace145` | the project file | the project file |

A project file (`jaws.yaml`) states `Project`, `Environment`, `Repository` and
`Owner`, and leaves `Organization` and `ManagedBy` out:

```yaml
tags:
  Project: braveheart-bot
  Environment: prod
  Repository: Braveheart-Chess/braveheart-lichess-bot
  Owner: jwallace145
```

Modules and components add their own tags where these apply:
- `Component`, `Purpose` and `Lifecycle` on the resources of one component;
- `Profile` on task instances;
- `Name`;
- `CostCenter` and `Workspace` on a Databricks project's resources.

`CostCenter` comes from the project's `databricks.cost_center` entry in
`config/projects.yaml`. A project file never sets any of these, and may not use
the keys Databricks reserves for itself.

## The rules

1. **One source per tag.** The tool decides `Organization` and `ManagedBy` for
   every resource. A project cannot choose them, because they are what the
   tool knows about the project from its own registry. A project file states
   the four that describe the project, and the CLI cross-checks `Project`,
   `Environment` and `Repository` against the rest of the file.
2. **Names never come from tags.** Every name is built from
   `context.name_root` (`jaws`): `jaws-<project>-records`,
   `jaws-<project>-ci-apply`, `jaws-infra-ci-plan`, `/jaws/<project>/...` in
   SSM. A name is a name only; no tag carries it.
3. **Access never comes from `Organization` or `ManagedBy`.** The CI roles'
   IAM conditions key only on `Project`, `Component` and `Purpose`
   (`aws:ResourceTag` and `aws:RequestTag`). The apply roles may change tags
   on their own project's existing resources, bounded by `Project`, so a
   retag is an ordinary apply.
4. **Tags are for attribution and cost.** `Organization` answers "whose
   project is this?", `ManagedBy` answers "what changes it?", and all six are
   cost allocation tags (`cost report`, [costs.md](costs.md)).

## How each stack gets them

- **Project stacks** (`site`, `bot`, `databricks-account`,
  `databricks-workspace`):
  - The CLI renders `tags` from the project file's four tags plus
    `Organization` and `ManagedBy`, and passes the name root as its own
    `name_root` variable.
  - The stacks apply `tags` through the provider's `default_tags`.
  - The stacks refuse any `ManagedBy` other than `JAWS` and any missing tag.
- **Task instances:** `RunInstances` does not inherit `default_tags`, so a
  task is launched with the same six tags. It also gets `Component`,
  `Purpose`, `Profile`, `Lifecycle`, `Name` and the run's own tags
  (`Workflow`, `RunId`, `TaskId` and so on).
- **The foundation:**
  - Its tags come from the library's `context` module: `Organization`
    `Jaws-Platform`, `Project` `jaws`, `Repository` `Jaws-Platform/jaws`,
    `ManagedBy` `JAWS`.
  - The resources it creates for projects (their CI roles, dataset buckets
    and Databricks objects) are the foundation's and carry its tags.
  - The shared Databricks workspace's `CostCenter` is the name root, `jaws`.
- **Owner access:**
  - `Organization` is `Jaws-Platform` and `ManagedBy` is `JAWS`, like every
    jaws stack.
  - Its `Project` and `Repository` tags and its names keep the values it was
    first applied with.
  - Only the owner applies it, so its retag waits for their next apply.

## Moving to derived tags

Until #290 a project file stated `Organization: jaws`, and the tool stamped
`ManagedBy: jaws`. From the release that derives them:

1. Files may still state `Organization` or `ManagedBy`. The value is ignored,
   and every run warns, as a `::warning::` annotation in GitHub Actions.
   Remove both from `jaws.yaml` in the PR that bumps to that release.
2. Each stack retags on its next apply. `Organization` changes from `jaws` to
   the project's owner, and `ManagedBy` from `jaws` to `JAWS`. Each is an
   in-place change.
3. A later release refuses `Organization` and `ManagedBy` in a project file.

## Adding a tag

- A tag that describes every resource and that the tool can know for itself
  belongs to the tool: add it to `TOOL_TAGS` (`src/jaws/site.py`) and to this
  page.
- A tag that describes the project belongs in the project file's required
  tags.
- A tag that describes one component belongs to its module.

An IAM condition may key on a tag only if no project can set it on another
project's resources: today that is `Project`, `Component` and `Purpose`.
