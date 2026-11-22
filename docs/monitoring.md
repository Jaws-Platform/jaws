# Monitoring and costs

The monitoring and cost platform is one node running Grafana and Prometheus,
the billing bucket the foundation creates, and the pipeline that fills it. The
design is [the spec](superpowers/specs/2026-11-21-monitoring-node-design.md);
its settings are [`config/monitoring.yaml`](../config/monitoring.yaml), which
only this repository can change (no project file can set any of it).

## Secrets

The stack reads four kinds of secret from SSM Parameter Store, all
SecureStrings under `/jaws/monitoring/`. They belong to the owner: Terraform
never creates, reads into state or changes them, and the node and the watchdog
report `missing secret <name>` while one is absent.

| Name | Parameter | What it is |
| --- | --- | --- |
| `grafana-admin-user` | `/jaws/monitoring/grafana-admin-user` | Grafana's admin user name |
| `grafana-admin-password` | `/jaws/monitoring/grafana-admin-password` | Its password; a new value is applied at the node's next reconcile |
| `slack/<channel>` | the channel's value in `monitoring.slack.channels` | The channel's Slack incoming-webhook URL, one per channel in `config/monitoring.yaml` (`slack/platform`, `slack/costs`) |

Set them from your shell, with admin credentials in the primary account
(the command refuses another account's):

```sh
jaws monitoring secrets set grafana-admin-user      # prompts, no echo
jaws monitoring secrets set grafana-admin-password
jaws monitoring secrets set slack/platform           # the webhook URL Slack gave the channel
jaws monitoring secrets set slack/costs
jaws monitoring secrets check                        # lists what is missing; exit 0 when nothing is
```

`set` overwrites, so it also rotates a secret. A name the configuration does
not imply is refused: a `slack/<channel>` needs the channel in
`monitoring.slack.channels` first. `check` never reads a value; it exits 3 and
names every missing secret while any is missing.
