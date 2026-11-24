# Tagging

Every AWS resource jaws builds carries the same six tags, and any the platform
stamps on everything (`context.tags`). Each tag has exactly one source, and
nothing else may set it. Names and access never depend on the
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
`Owner`. It may not state `Organization` or `ManagedBy`: the CLI refuses a file
that does, even with the value the tool would set.

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
  - The stacks refuse any missing tag, and any `ManagedBy` other than their
    `managed_by` variable, which the CLI renders from `context.managed_by`.
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
  - `Project` is `jaws`, as the foundation's, and `Repository` is
    `Jaws-Platform/jaws`, the repository that manages it. Its names keep the
    values it was first applied with.
  - Only the owner applies it, so its retag waits for their next apply.

## The platform's own tags

A platform may stamp tags of its own on everything it manages, such as a
department or a cost pool.

- **Where they are set:** `context.tags` in `config/tool.yaml`. There are none
  by default.
- **What carries them:** every stack the CLI renders, every task instance, and
  the foundation's and monitoring's resources. The owner's `owner-access/` and
  `billing-export/` do not.
- **Who may state them:** only the platform. A project file that states one is
  refused, with a message naming the key. The bot and research stop commands
  still load such a file, so an instance stays stoppable, and the platform's
  value wins. A site file that states one is refused everywhere, `preview
  remove` included: drop the key, then run the remove again.
- **Which keys:** a key may not be one jaws, a module, Databricks or a task
  sets itself (`RESERVED_TAG_KEYS` in `src/jaws/settings.py`), and may not
  start with `aws:`. Keys and values use the characters that every AWS service
  accepts.

## Moving to derived tags

Until #290 a project file stated `Organization: jaws`, and the tool stamped
`ManagedBy: jaws`. The move took three steps, all done:

1. v0.76.0 derived both tags. It ignored a stated value, with a warning in
   every run, and every onboarded project dropped `Organization: jaws` from
   `jaws.yaml`.
2. Each stack retagged on its next apply: `Organization` from `jaws` to the
   project's owner, and `ManagedBy` from `jaws` to `JAWS`, in place. Sites
   retag on their next deploy.
3. The release after that refuses `Organization` and `ManagedBy` in a project
   file (#300).

## Adding a tag

- A tag that describes every resource and that the tool can know for itself
  belongs to the tool: add it to `TOOL_TAGS` (`src/jaws/site.py`) and to this
  page.
- A tag the platform wants on everything, that only it knows, goes in
  `context.tags`.
- A tag that describes the project belongs in the project file's required
  tags.
- A tag that describes one component belongs to its module.

An IAM condition may key on a tag only if no project can set it on another
project's resources: today that is `Project`, `Component` and `Purpose`.
