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

The **Data access** workflow binds and grants every agreed handshake within
15 minutes of its second half merging.
[docs/databricks.md](../docs/databricks.md#datasets-and-access) has the whole
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

## Onboarding

Onboarding is the moment to take inventory of the dataset, so the file and its
pull request say what the platform now vouches for:

1. **Look at what is under the prefix**: the key layout, the formats, how it
   grows, its size and object count, and whether the bucket keeps versions.
   The producer's own tooling, or the bucket's Metrics tab in the S3 console,
   answers this without reading the data.
2. **Write the file**: `description` says what the data is and how it is laid
   out, in words that stay true as it grows; `prefix` onboards only what
   consumers should see.
3. **Put the inventory in the pull request**: point-in-time numbers (size,
   object count, the date) belong there, not in the file, where they would go
   stale.

The foundation's plan on that pull request adds exactly the dataset's role,
storage credential, external location and their bindings to the host.

Unity Catalog refuses overlapping external locations, so the foundation's plan
fails on a URL equal to, inside, or containing any location already in the
metastore. Two registered datasets cannot overlap: each has its own bucket.

## Offboarding

Offboarding needs zero edges: remove both halves (`consumers` in the
producer's file, `reads` in each consumer's), let a sweep revoke them, then
delete the file. A pull request that deletes a file still named by
`consumers` or `reads` fails its **Data access** plan. Offboarding removes
Unity Catalog metadata and the role, never data.
