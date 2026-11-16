# Onboarded datasets

Each file here onboards one dataset to the platform. The foundation creates
its one read-only, platform-owned IAM role, storage credential and Unity
Catalog external location, all named `<organization>-ds-<owner>-<name>` (for
example `jwall-engineering-ds-braveheart-selfplay-positions`).

**Onboarding lets nobody read.** A Databricks workspace reads a dataset only
while both of these hold, a handshake:

- the producing project lists the workspace's project under the dataset's
  `consumers` (its own `jwall-engineering-sites.yaml`);
- the consuming project lists the dataset under its workspace's `reads`, with
  a `purpose`.

The **Data access apply** workflow binds and grants every agreed handshake,
every 15 minutes. [docs/databricks.md](../docs/databricks.md) has the whole
flow.

## A dataset's file

The path is the dataset's id, `<owner>/<name>`:

```yaml
# datasets/braveheart-selfplay/positions.yaml
description: Braveheart self-play positions and label sets, every generation
prefix: data/
```

- `<owner>` is a registered project (`foundation/bots.tf`), and `<name>` is
  one of its `dataset` components. The bucket is that component's,
  `<organization>-<owner>-<name>`.
- `description` is required: what the data is.
- `prefix` is required: what is onboarded, path segments ending in `/`, with
  no leading `/`, within the component's own prefix.
- `<owner>-<name>` may be at most 40 characters, and no two ids may share it
  (`a-b/c` and `a/b-c` would).
- Nothing else lives here: no other keys, no nested folders, no `.yml`. This
  README is the only other file.

Unity Catalog refuses overlapping external locations, so the foundation's plan
fails on a URL equal to, inside, or containing another registered dataset's
or any location already in the metastore.

## Offboarding

Delete the file, once neither project's file still names the dataset. A pull
request that offboards a dataset still named by `consumers` or `reads` fails
its **Data access** plan. Offboarding removes Unity Catalog metadata and the
role, never data.
