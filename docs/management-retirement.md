# Retiring the management account

Since 2026-11-21 every project runs in the production account (570327089884).
The management account (650503560686) keeps only what jaws left behind: the old
foundation (CI roles, site buckets, an image repository, a hosted zone that no
longer serves the domain, the EC2 Spot service-linked role), old data and task
buckets, and the state of retired stacks. This page retires all of it. Once,
by the owner, with admin sign-ins to both accounts.

What stays in the management account, because it isn't jaws's to remove: AWS
Organizations and IAM Identity Center, `owner-access/` and its state in
`jwall-engineering-tfstate`, and everything prog-strength owns (its buckets,
its stack and the account's GitHub OIDC provider).

## 1. Stop CI from touching the management account

`production.management_retired: true` in `config.yaml`, released.
`jaws config accounts` then lists production alone, so no workflow plans,
applies or publishes an image in management, and production's plan reports
the `Terraform plan` check that the `main` ruleset requires. Any run that would
address management is refused. The flag needs every project `moved`.

## 2. Check, then retire

```sh
aws sso login --profile jwall-admin    # management
aws sso login --profile jaws-prod      # production
uv run python scripts/retire_management.py            # the checks; changes nothing
uv run python scripts/retire_management.py --execute  # retires, asking before each phase
```

Run it from an up-to-date `main`. It takes about ten minutes before it asks
anything: it lists every object of the old buckets and of production's.

**The checks.** Nothing changes unless all of them pass:

- each profile signs in to the account `config.yaml` names for it;
- no EC2 instance tagged by jaws exists in management;
- the registrar's name servers are production's zone's alone;
- every object of each old data bucket is in its production home with the same
  key, size and ETag, and no old bucket holds a key outside the prefixes that
  were copied:

  | Old bucket | Its production home |
  |---|---|
  | `jwall-engineering-braveheart-selfplay-positions` | `jaws-braveheart-selfplay-positions` |
  | `jwall-engineering-braveheart-trainer-nets` | `jaws-braveheart-trainer-nets` |
  | `jwall-engineering-braveheart-nnue`, `jwall-engineering-rusty-chess-nnue` | `data/selfplay/` in the positions bucket, `data/nets/` in the nets bucket |
  | `jwall-engineering-braveheart-records` | `jaws-braveheart-bot-records` |

  Every one of these buckets uses SSE-S3 and holds no multipart upload, so an
  equal ETag is an equal MD5 of the object's bytes. The script stops on a
  multipart ETag rather than trust it.

**The phases.** Each asks first; type `retire` to go ahead. Each can be run
again and skips what is already gone.

1. **The foundation's state**, from `v0.69.0`, the last release that managed it,
   in a temporary worktree. The state bucket, the old zone and the Spot role are
   released from state. The site buckets and the image repository are emptied.
   Then a destroy plan, shown and confirmed, removes the rest: the four CI roles
   with their policies, the three site buckets and the repository.
2. **The leftovers:** the EC2 Spot service-linked role (no task runs here any
   more), the old `jwall.engineering` zone (its records, then the zone), and
   `/jwall-engineering/databricks/client-secret`.
3. **The buckets**, every version: the five old data buckets above, the three
   task results buckets and `jwall-engineering-databricks-audit-logs`, and the
   site buckets if phase 1 left any.
4. **The retired stacks' state** in `jwall-engineering-tfstate`, every version
   outside `project=owner-access/`. The bucket stays: owner-access keeps its
   state there.

## What is lost on purpose

Only what production doesn't need:

- old versions in the positions bucket, among them the `N8x` label set deleted
  on 2026-11-18. Only current versions were copied;
- task results, which expire after days anyway;
- the management workspace's Databricks audit logs, from before Databricks
  moved on 2026-11-19. Production writes its own;
- the site images in `jwall-engineering-sites`. Production builds its own.

The 84 Lichess games in `jwall-engineering-braveheart-records` were copied to
`jaws-braveheart-bot-records` on 2026-11-21 before this page was written. The
script checks them like the rest.

## Afterwards

Fold the `production:` section into the top level of `config.yaml` and remove
the code paths for two accounts. That is its own pull request: nothing waits
on it.
