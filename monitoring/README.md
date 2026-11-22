# monitoring/

The monitoring and cost platform's stack: the root module of
[`Jaws-Platform/jaws-monitoring/aws`](https://registry.terraform.io/modules/Jaws-Platform/jaws-monitoring/aws/latest)
(the billing normalizer and the monitoring node) in a VPC of its own
([`jaws-network`'s `vpc`](https://registry.terraform.io/modules/Jaws-Platform/jaws-network/aws/latest/submodules/vpc):
one public subnet, no NAT). Everything is named `jaws-monitoring`
(`<name_root>-monitoring`), and tagged `Project = monitoring`: the stack's CI
roles are scoped to both.

## Inputs

None by hand. The stack reads the tool configuration (`config/`) as the
foundation does, and builds nothing without its `monitoring` section:

| What | From |
|---|---|
| The node's type, image, domain, snapshots and schedule | `config/monitoring.yaml` `monitoring` |
| The zone of the Grafana record | `config/sites.yaml` `dns.zone_id`, only with `monitoring.domain` |
| The Grafana admin | the owner's `/jaws/monitoring/grafana-admin-user` and `grafana-admin-password` (`jaws monitoring secrets`) |
| Slack | `monitoring.slack`: each channel's webhook parameter, and the routes |
| The billing bucket, budgets and anomaly floor | `monitoring.cost` (the foundation creates the bucket) |
| The AWS bill | `raw/provider=aws/source=data-exports/jaws-focus-daily`, where `billing-export/` delivers, with `monitoring.cost.aws` |
| Databricks billing | the foundation's job, with `monitoring.cost.databricks`, Databricks enabled and its shared host recorded; usage without a `Project` tag takes its workspace's project |
| Task runs | `raw/provider=jaws/source=task-runs`, written by `task run` and `task sweep`, joined on `RunId` and `TaskId` |

The node's zone is pinned in `main.tf` (`us-east-1a`): moving it means a new
subnet, instance and data volume. The plan stops if the instance type is not
offered there.

## How it is applied

- **Pull requests:** `ci.yml` validates and tests it, and plans it with
  `jaws-monitoring-ci-plan` (skipped, with a notice, until the release that
  creates that role).
- **Releases:** the Release apply job applies it after the foundation, with
  `jaws-monitoring-ci-apply`, so the first release creates the roles, the
  billing bucket and then the stack.
- State: `project=monitoring/env=prod/monitoring-prod.tfstate` in the shared
  state bucket (`backend/prod.hcl`), reachable only by the stack's two roles.

Locally, with no credentials:

```sh
terraform init -backend=false && terraform validate && terraform test
```

Operations, recovery and the owner's steps: [docs/monitoring.md](../docs/monitoring.md).
