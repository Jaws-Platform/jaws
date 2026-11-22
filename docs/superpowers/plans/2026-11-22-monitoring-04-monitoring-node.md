# Monitoring Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `monitoring-node` submodule to `terraform-aws-jaws-monitoring`, and release it as 0.3.0. It covers:
- one EC2 instance and a separate data volume;
- public HTTPS (optional);
- a bootstrap and a reconciler;
- the container stack: Caddy, Grafana on Postgres, Prometheus, node-exporter, cAdvisor, postgres-exporter and blackbox-exporter;
- a content-addressed config bundle, so a change is applied without replacing the instance.

Dashboards, alert rules and Slack come in plan 05.

**Architecture:**
- **Terraform** renders a config bundle (`compose.yaml`, the Prometheus, Caddy and blackbox configs, Grafana provisioning) as one JSON object at `bundles/<sha256>.json` in a small config bucket, and names it in the SSM parameter `/<name>/node/config-bundle`.
- **User data** only bootstraps the node: Docker, the pinned Compose plugin, the data volume, swap, DNS and the systemd units.
- **The reconciler,** a Python 3.9 stdlib script, runs at boot and every 5 minutes. It converges to the named bundle: it reads the secrets, generates the local ones once, writes the release, pulls, swaps it in, runs `compose up`, and records its status. A failed pull never touches the running stack.

**Tech Stack:**
- Terraform `>= 1.11`, `hashicorp/aws ~> 6.0`;
- cloud-init on Amazon Linux 2023 arm64;
- Docker with Compose v5.6.1, systemd;
- Python 3.9 (AL2023's `python3`) using only the stdlib, with tests in `unittest` and fake `aws` and `docker` binaries.

**Spec:** [docs/superpowers/specs/2026-11-21-monitoring-node-design.md](../specs/2026-11-21-monitoring-node-design.md), sections 6.5 (all of it, including the owner's image decision) and 6.11. Series: [00-roadmap](2026-11-21-monitoring-00-roadmap.md).

## Global Constraints

**Where things live**
- **Repo:** `$REPO` = `/Users/jimmywallace/Projects/Jaws-Platform/terraform-aws-jaws-monitoring`. Work on branch `feat/monitoring-node`, cut from `origin/main` (0.2.0).
- **Module:** `$MOD` = `$REPO/modules/monitoring-node`.

**Conventions**
- No provider configuration, no tag maps, and no organisation names; examples use `acme` and `example.com`.
- Every resource carries `Name` and `Component = "monitoring"`.
- terraform-docs READMEs with absolute links.
- One-line commits with the `Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>` trailer.
- No cloud calls.

**The instance**
- AMI: looked up by `ami_name` (owner `amazon`, `arm64`), so a new name is a deliberate replacement.
- `instance_type` defaults to `t9g.medium`.
- Metadata: `http_tokens = "required"` and `http_put_response_hop_limit = 2`, because containers on the Docker bridge (Grafana's CloudWatch data source) need instance metadata.
- `credit_specification { cpu_credits = "standard" }`.
- Root volume: gp3, encrypted, `root_volume_gb` (default 12).
- A public IPv4 address.
- `user_data_replace_on_change = true`, so a change to the bootstrap means a new instance, and the data volume is reattached.
- Access through Session Manager (`AmazonSSMManagedInstanceCore`), with no SSH key.

**The data volume**
- An `aws_ebs_volume`: gp3, encrypted, `data_volume_gb` (default 30), in the subnet's availability zone.
- Attached as `/dev/sdf` with `stop_instance_before_detaching = true`.
- Mounted at `/data` by its NVMe serial (`vol…` without the hyphen), and formatted xfs only if it has no filesystem.
- **Layout:**
  - `/data/prometheus` (uid 65534)
  - `/data/grafana` (uid 472)
  - `/data/postgres`
  - `/data/caddy`
  - `/data/config/releases/<sha>/`, with `/data/config/current` as a symlink to the running release
  - `/data/secrets/` (0700)
- **Snapshots** (optional) are a DLM policy on the volume's tag, at `snapshots.time_utc` (default `03:00`), keeping `snapshots.keep` (default 7).

**Network**
- With `domain` set, the security group admits 443 and 80 from `0.0.0.0/0` and `::/0`. Without it, there is no ingress at all, and Grafana is published on `127.0.0.1:3000` for a Session Manager port forward.
- Egress is open.

**DNS** (with `domain`)
- `aws_route53_record` A with `ttl = 60` and `ignore_changes = [records]`.
- At every boot, the bootstrap upserts the instance's public IPv4 address.
- IAM allows `route53:ChangeResourceRecordSets` on that zone, with `ForAllValues:StringEquals` on:
  - `route53:ChangeResourceRecordSetsNormalizedRecordNames = [domain]`;
  - `route53:ChangeResourceRecordSetsRecordTypes = ["A"]`;
  - `route53:ChangeResourceRecordSetsActions = ["UPSERT"]`.

**Images**
- Pinned by digest, in `local.default_images` and overridable per key with `images`.
- All are multi-arch with `linux/arm64`, checked 2026-11-22:

```text
caddy              docker.io/library/caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0
grafana            docker.io/grafana/grafana:13.3.1@sha256:0615ec4fbd4072004b7d86b46ded63013a74b7d6eb1119273dd89e8fa25c13cf
prometheus         docker.io/prom/prometheus:v3.16.0@sha256:e04987641b57704f408e31f6373ba4138ecf27cb4a165d24aabb6c38fddd0f06
node-exporter      docker.io/prom/node-exporter:v1.13.1@sha256:7296504d4ada44b7d7ab4431e27e9f9900d8488f8d55842f4b12ae2704e16dfe
cadvisor           gcr.io/cadvisor/cadvisor:v0.55.1@sha256:3de2bd5203120b866d74a9b283b2ffb8ec382fbf9dc321814700c6ea6f44ec57
postgres           docker.io/library/postgres:17.12-alpine3.24@sha256:f9cf3e1f0066f0eb0c48707d864f0ac5941e9ff454a072077d97a4d278d07d73
postgres-exporter  docker.io/prometheuscommunity/postgres-exporter:v0.21.1@sha256:3b8e05a84282cd1199ad2fb6c66f362738bf4c68c1547d8f4226a34a7dd6d8d7
blackbox-exporter  docker.io/prom/blackbox-exporter:v0.29.1@sha256:ea1c7aa3ef3f307cd03e85f34abb604478ccb90b567fc690da0cd9776da76b13
```

- **Compose plugin:** v5.6.1, `https://github.com/docker/compose/releases/download/v5.6.1/docker-compose-linux-aarch64`, sha256 `42cfa75f51ad0ccf290bad37899e0038a8c10a0069e85233ecc1d53e3ff1347d`. It is checked before it is installed.

**Memory limits** (compose `mem_limit`): caddy 128m, grafana 512m, prometheus 1g, node-exporter 64m, cadvisor 256m, postgres 512m, postgres-exporter 64m, blackbox-exporter 64m. Swap is a 2 GB file on the root volume.

**Prometheus**
- `--storage.tsdb.retention.time=<prometheus_retention.time>` (default `365d`);
- `--storage.tsdb.retention.size=<size_gb>GB` (default `12`);
- `--web.enable-lifecycle`;
- scrape interval 15s, with `external_labels { node = <name> }`;
- jobs `prometheus`, `node` (`host.docker.internal:9100`, because node-exporter uses host networking and pid), `cadvisor`, `postgres`, `grafana`, and `blackbox` (with a domain: probe `https://<domain>` with module `http_2xx`).

**Grafana**
- Postgres database `grafana`, as the user `monitoring`, whose password is generated once on the node.
- Admin user and password from the SSM SecureString parameters `grafana_admin.user_parameter` and `.password_parameter`.
- Environment:
  - `GF_AUTH_ANONYMOUS_ENABLED=false`, `GF_USERS_ALLOW_SIGN_UP=false`;
  - `GF_SECURITY_DISABLE_INITIAL_ADMIN_PASSWORD_CHANGE=true`;
  - `GF_SERVER_ROOT_URL` = `https://<domain>` or `http://localhost:3000`;
  - `GF_SECURITY_COOKIE_SECURE=true` with a domain.
- Data sources, provisioned:
  - `prometheus` (default);
  - `cloudwatch` (default credentials from the instance role, `defaultRegion` = the region).
- A dashboard provider for `/var/lib/grafana/dashboards`, with `allowUiUpdates: false`.

**Caddy** (with a domain): reverse-proxies `grafana:3000`, answers `/metrics*` with 404, and sets `Strict-Transport-Security`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`. ACME takes `acme_email` if set.

**The bundle** (`schema: "monitoring-bundle-1"`):

```json
{"schema": "monitoring-bundle-1",
 "files":     {"compose.yaml": "…", "prometheus/prometheus.yml": "…", "caddy/Caddyfile": "…", "blackbox/blackbox.yml": "…",
               "grafana/provisioning/datasources/datasources.yaml": "…", "grafana/provisioning/dashboards/dashboards.yaml": "…"},
 "secrets":   {"GF_SECURITY_ADMIN_USER": "<ssm name>", "GF_SECURITY_ADMIN_PASSWORD": "<ssm name>"},
 "generated": ["POSTGRES_PASSWORD"]}
```

- Each compose service carries the label `monitoring.config-hash`, the sha256 of the files it mounts, so `compose up -d` recreates exactly the services whose files changed.
- `compose.yaml` uses `${VAR}` for the secrets and generated values, read from the env file the reconciler writes, `/etc/monitoring/stack.env` (0600).
- No literal `$` appears in any Grafana provisioning file except deliberate `$VAR` expansions; plan 05 adds them.

**The reconciler's guarantees**
- One run at a time, with `flock /run/monitoring-reconcile.lock`.
- Nothing is swapped in until every secret was read and every image pulled. Pulls are retried 5 times with backoff.
- A failure leaves the running release as it was and writes `status = failed:<reason>`. The reasons are:
  - `missing secret <parameter>`;
  - `bundle <reason>`;
  - `pull`;
  - `up`.
- On success it writes `status = ok` and `running-config = <bundle key>`.
- Generated secrets are created once, in `/data/secrets/<NAME>`, and reused.

## Review Focus

1. **A secret parameter that doesn't exist yet** (the owner hasn't run `secrets set`). The node must report `failed:missing secret <name>` and keep whatever ran before, not start Grafana with an empty password (Task 3, `test_a_missing_secret_changes_nothing_and_says_which`).
2. **A registry that is down or rate-limiting during a replacement.** Pulls must be retried. If they still fail, the old release keeps running, and the next 5-minute run tries again (Task 3, `test_a_failed_pull_keeps_the_running_release`).
3. **The node restarting with no network to S3 or SSM,** for example a scheduled start before the endpoint is reachable. The stack must still come up from `/data/config/current` and the env file, before any fetch (Task 3, `test_with_ssm_unreachable_the_current_release_still_starts`).
4. **The same bundle every five minutes.** No download, no pull, no recreate; only an idempotent `up -d` (Task 3, `test_an_unchanged_bundle_only_ensures_the_stack_is_up`).
5. **No domain.** The node must have no ingress at all, no Caddy and no blackbox, and Grafana only on `127.0.0.1` (Task 1, `without_a_domain_nothing_is_reachable_from_outside`; Task 4, `without_a_domain_grafana_is_only_on_localhost`).

---

### Task 1: The node's infrastructure

**Files:**
- Create: `$MOD/{versions.tf,variables.tf,main.tf,iam.tf,network.tf,storage.tf,outputs.tf,README.md}`
- Test: `$MOD/tests/monitoring_node.tftest.hcl`

**Interfaces:**
- **Inputs:**
  - `name` (string, required, `^[a-z0-9-]{1,40}$`);
  - `vpc_id`, `subnet_id` (required);
  - `instance_type` (default `"t9g.medium"`);
  - `ami_name` (string, required);
  - `root_volume_gb` (default 12, minimum 8), `data_volume_gb` (default 30, minimum 10);
  - `domain` (default null), `zone_id` (default null, required when `domain` is set), `acme_email` (default null);
  - `grafana_admin = object({ user_parameter = string, password_parameter = string })`, required;
  - `prometheus_retention = object({ time = optional(string, "365d"), size_gb = optional(number, 12) })`, default `{}`;
  - `snapshots = object({ enabled = optional(bool, false), time_utc = optional(string, "03:00"), keep = optional(number, 7) })`, default `{}`;
  - `images` (`map(string)`, default `{}`).
- **Outputs:**
  - `instance_id`, `public_ip`, `security_group_id`;
  - `role_name`, `role_arn`;
  - `config_bucket`;
  - `parameter_prefix` (`"/<name>/node"`);
  - `data_volume_id`;
  - `grafana_url`.
- **Names:**
  - `name`, for the instance's `Name`, the security group, the role and the instance profile;
  - `<name>-config-<account id>`, for the config bucket;
  - `/<name>/node/{config-bundle,status,running-config}`, for the parameters.

- [ ] **Step 1: Write the failing tests**

The tests mock `aws`, with `override_during = plan`:
- `aws_caller_identity` = `123456789012`, `aws_region` = `us-east-1`;
- `aws_subnet` with `availability_zone = "us-east-1a"`;
- `aws_ami` with `id = "ami-0123456789abcdef0"`;
- `aws_instance` with `id = "i-0123456789abcdef0"` and `public_ip = "198.51.100.7"`.

The variables are:
- `name = "acme-monitoring"`, `vpc_id = "vpc-0123"`, `subnet_id = "subnet-0123"`;
- `ami_name = "al2023-ami-2023.12.20261026.1-kernel-6.18-arm64"`;
- `grafana_admin = { user_parameter = "/acme/monitoring/grafana-admin-user", password_parameter = "/acme/monitoring/grafana-admin-password" }`.

Its runs:
- **`the_instance_is_imdsv2_standard_credits_encrypted_and_public`:**
  - `ami == "ami-0123456789abcdef0"` and `instance_type == "t9g.medium"`;
  - `metadata_options[0].http_tokens == "required"` and `.http_put_response_hop_limit == 2`;
  - `credit_specification[0].cpu_credits == "standard"`;
  - a root volume that is `gp3`, encrypted and 12 GB;
  - `associate_public_ip_address`, and `user_data_replace_on_change`;
  - tags `{ Name = "acme-monitoring", Component = "monitoring" }`.
  - `data.aws_ami.this` filters `name` = `ami_name` and `architecture` = `arm64`, with owners `["amazon"]`.
- **`the_data_volume_is_separate_and_survives_the_instance`:** `aws_ebs_volume.data` is 30 GB `gp3`, encrypted, in `us-east-1a`, with `Name = "acme-monitoring-data"`. `aws_volume_attachment.data` uses `device_name == "/dev/sdf"` and `stop_instance_before_detaching`.
- **`without_a_domain_nothing_is_reachable_from_outside`:** the security group has no ingress and open egress, there is no `aws_route53_record`, and no IAM statement has the Sid `UpdateItsDnsRecord`.
- **`with_a_domain_only_web_traffic_comes_in`:** with `domain = "grafana.example.com"` and `zone_id = "Z123"`:
  - ingress is exactly 443 and 80 from `0.0.0.0/0` and `::/0`;
  - the record is A, TTL 60, `records == toset(["198.51.100.7"])`;
  - the `UpdateItsDnsRecord` statement is exactly as in Global Constraints, on `arn:aws:route53:::hostedzone/Z123`.
- **`the_role_reads_its_bundle_and_secrets_and_writes_its_status`:** the inline policy's statements are exactly:
  - `ReadTheBundle`: `s3:GetObject` on `arn:aws:s3:::acme-monitoring-config-123456789012/bundles/*`;
  - `ReadTheParameters`: `ssm:GetParameter` on the `config-bundle` parameter ARN and the two Grafana parameter ARNs;
  - `WriteTheStatus`: `ssm:PutParameter` on the `status` and `running-config` ARNs;
  - `ReadMetrics`: `cloudwatch:GetMetricData`, `cloudwatch:ListMetrics` and `cloudwatch:GetMetricStatistics` on `"*"`.
  
  `AmazonSSMManagedInstanceCore` is attached.
- **`the_parameters_name_the_bundle`:** `/acme-monitoring/node/config-bundle` holds the key of the `aws_s3_object.bundle`. The `status` and `running-config` parameters exist.
- **`snapshots_are_opt_in`:** by default `length(aws_dlm_lifecycle_policy.snapshots) == 0`. With `snapshots = { enabled = true }`, one policy targets `{ Name = "acme-monitoring-data" }` at `03:00`, keeping 7.
- **`rejects_a_domain_without_a_zone`:** `expect_failures = [aws_route53_record.this]`, through a precondition, or `[var.zone_id]` through validation.
- **`rejects_an_invalid_name`**, and **`rejects_a_tiny_data_volume`** (`data_volume_gb = 5`).

- [ ] **Step 2: Run them to see them fail.** Run: `cd $MOD && terraform init -backend=false >/dev/null && terraform test`. Expected: undeclared resources.

- [ ] **Step 3: Implement the infrastructure**
  - `network.tf`: the security group and the record.
  - `storage.tf`: the data volume, the attachment, the DLM role and policy, and the config bucket (versioned, private, SSE-S3, `prevent_destroy` not set, noncurrent versions expiring after 30 days).
  - `iam.tf`: as tested.
  - `main.tf`: the AMI lookup, the instance and the parameters.

  `user_data` is a placeholder `local.user_data` that Task 2 replaces. `aws_s3_object.bundle` is a placeholder too, which Task 4 fills.

- [ ] **Step 4: Run them to see them pass.** Expected: `Success! 10 passed`.

- [ ] **Step 5: Commit.** `feat(monitoring-node): add the node's instance, data volume, network and role` (with the trailer).

---

### Task 2: The bootstrap

**Files:**
- Create:
  - `$MOD/files/user-data.yaml.tftpl`;
  - `$MOD/files/monitoring-bootstrap.sh` (every boot: mount `/data`, the directories and their owners, swap, Docker's log rotation, the Compose plugin, the DNS upsert);
  - `$MOD/files/monitoring-release-check.sh` (the node-exporter textfile metrics `monitoring_os_release_info{release}`, `monitoring_os_release_update_available` and `monitoring_os_release_update_since_seconds`, from `dnf check-release-update`);
  - `$MOD/user-data.tf`.
- Test: the module's tftest (the rendered user data), and `shellcheck` on `files/*.sh`, which `check-module.sh` already runs.

**Interfaces:**
- Produces `local.user_data`, which writes:
  - `/etc/monitoring/node.env`: `NAME`, `REGION`, `PARAMETER_PREFIX`, `CONFIG_BUCKET`, `DATA_VOLUME_ID`, `DOMAIN`, `ZONE_ID`;
  - `/usr/local/bin/monitoring-{bootstrap,reconcile,release-check}`;
  - the units:
    - `monitoring-bootstrap.service` (oneshot, every boot, before `docker.service`);
    - `monitoring-reconcile.service` (oneshot, after bootstrap and docker);
    - `monitoring-reconcile.timer` (`OnBootSec=1min`, `OnUnitActiveSec=5min`);
    - `monitoring-release-check.{service,timer}` (`OnBootSec=5min`, `OnUnitActiveSec=6h`).
  
  `runcmd` installs `docker` with dnf, then enables `docker` and all the units. Per-boot work lives only in units, never in `runcmd`.

- [ ] **Step 1: Write the failing tftest run, `the_user_data_bootstraps_every_boot`:**
  - the rendered `aws_instance.this.user_data` contains `v5.6.1/docker-compose-linux-aarch64` and `42cfa75f51ad0ccf290bad37899e0038a8c10a0069e85233ecc1d53e3ff1347d`;
  - it contains `PARAMETER_PREFIX='/acme-monitoring/node'` and the data volume ID;
  - `monitoring-bootstrap.service` has `Before=docker.service`;
  - the reconcile timer has `OnUnitActiveSec=5min`.

  Run: `terraform test`. Expected: FAIL.

- [ ] **Step 2: Write the two scripts and the template.** `monitoring-bootstrap.sh`:
  - finds the volume through `/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_<vol id without hyphen>`;
  - runs `mkfs.xfs` only if `blkid` finds no filesystem;
  - adds an fstab entry with `nofail`;
  - creates the directories with their owners;
  - creates the 2 GB swap file once;
  - writes `/etc/docker/daemon.json` (`json-file`, `max-size 10m`, `max-file 3`);
  - installs the Compose plugin only if its checksum matches;
  - with a domain, gets the public IPv4 address from IMDSv2 and upserts the record with `aws route53 change-resource-record-sets`, retrying 5 times.

- [ ] **Step 3: Run the checks.** Run: `scripts/check-module.sh modules/monitoring-node`. Expected: shellcheck is clean, and terraform test shows `11 passed`.

- [ ] **Step 4: Commit.** `feat(monitoring-node): bootstrap the node on every boot` (with the trailer).

---

### Task 3: The reconciler

**Files:**
- Create: `$MOD/files/monitoring-reconcile.py`. Python 3.9: `from __future__ import annotations`, no `match`, stdlib only, using `aws` and `docker` through `subprocess`.
- Test: `$MOD/files/test_monitoring_reconcile.py`. Fake `aws` and `docker` executables on `PATH` keep the SSM parameters, the S3 objects and the docker calls in a JSON state file, as in `container-instance`'s tests. Each test runs the real script in a temporary root, with `MONITORING_ROOT` overriding `/data`, `/etc/monitoring` and `/run`.

**Interfaces:**
- `monitoring-reconcile [--force]`; exits 0 on `ok` and 1 on `failed:*`.
- The environment comes from `/etc/monitoring/node.env`, and `MONITORING_ROOT` (tests only) prefixes every path.
- Order of a run:
  1. Lock.
  2. `compose up -d` the current release, if there is one. This covers Review Focus 3: the stack runs before any network call.
  3. Get the `config-bundle` parameter.
  4. If it equals `running-config` and `--force` isn't set, stop here.
  5. Download and parse the bundle, and check its schema.
  6. Read every secret.
  7. Create any missing generated secret.
  8. Write the release to `releases/<sha>/`.
  9. Write `stack.env.next`.
  10. `compose pull` the new release, with retries.
  11. Swap the `current` symlink and the env file, atomically.
  12. `compose up -d --remove-orphans`.
  13. Put `status` and `running-config`.

- [ ] **Step 1: Write the failing tests**
  - **`test_a_first_run_installs_the_bundle_and_starts_the_stack`:**
    - `current` points to `releases/<sha>`;
    - the files match the bundle;
    - `stack.env` (mode 0600) holds both Grafana values and a 32+ character `POSTGRES_PASSWORD`;
    - the docker calls are `pull` and then `up -d --remove-orphans`;
    - `status == "ok"` and `running-config` is the key.
  - **`test_an_unchanged_bundle_only_ensures_the_stack_is_up`:** the second run makes no S3 call and no `pull`, and exactly one `up -d`.
  - **`test_a_new_bundle_swaps_the_release`.**
  - **`test_generated_secrets_are_made_once`:** the same `POSTGRES_PASSWORD` across runs.
  - **`test_a_missing_secret_changes_nothing_and_says_which`:** `status == "failed:missing secret /acme/monitoring/grafana-admin-password"`, with no pull, no swap and the old release still current.
  - **`test_a_failed_pull_keeps_the_running_release`:** the fake docker fails `pull` 5 times, so there are 5 pull attempts, `status == "failed:pull"` and `current` is unchanged.
  - **`test_a_bad_bundle_is_refused`:** a wrong `schema` gives `failed:bundle schema`.
  - **`test_with_ssm_unreachable_the_current_release_still_starts`:** the fake aws fails every call, so `up -d` still ran on the current release and the exit code is 1.

- [ ] **Step 2: Run them to see them fail.** Run: `scripts/check-module.sh modules/monitoring-node`. Expected: FAIL (no script).

- [ ] **Step 3: Implement the reconciler.**

- [ ] **Step 4: Run them to see them pass.** Expected: `Ran 8 tests … OK`, and terraform test unchanged.

- [ ] **Step 5: Commit.** `feat(monitoring-node): converge the node to its config bundle` (with the trailer).

---

### Task 4: The bundle and the container stack

**Files:**
- Create: `$MOD/bundle.tf` (every file as HCL plus `yamlencode`, so the tests can `yamldecode` them), `$MOD/files/Caddyfile.tftpl` and `$MOD/examples/basic/{main.tf,versions.tf}`.
- Modify: `$MOD/README.md`, and the root `README.md` and `main.tf` (the submodule list).
- Test: the module's tftest.

**Interfaces:**
- `local.bundle` is the object in Global Constraints. `aws_s3_object.bundle` is at key `bundles/<sha256(jsonencode(local.bundle))>.json` with `content_type = "application/json"`.
- Plan 05 adds files under `grafana/provisioning/alerting/` and `grafana/dashboards/`, and keys in `secrets` for the Slack webhooks, by merging into `local.bundle_files` and `local.bundle_secrets`.

- [ ] **Step 1: Write the failing tests**
  - **`every_image_is_pinned_by_digest`:** `alltrue([for s in values(yamldecode(local.bundle.files["compose.yaml"]).services) : strcontains(s.image, "@sha256:")])`.
  - **`the_stack_has_memory_limits_and_restarts`:** every service has `mem_limit` (`prometheus` 1g, `grafana` 512m) and `restart == "unless-stopped"`.
  - **`without_a_domain_grafana_is_only_on_localhost`:** the services are exactly `grafana`, `prometheus`, `node-exporter`, `cadvisor`, `postgres` and `postgres-exporter`, and `grafana.ports == ["127.0.0.1:3000:3000"]`.
  - **`with_a_domain_caddy_serves_grafana_and_blackbox_probes_it`:**
    - `caddy` publishes `80:80` and `443:443`;
    - the Caddyfile has `grafana.example.com {`, `reverse_proxy grafana:3000` and a `/metrics*` matcher answering 404;
    - grafana publishes no ports;
    - the Prometheus `blackbox` job targets `https://grafana.example.com`.
  - **`prometheus_keeps_a_year_within_a_size_cap`:** its command has `--storage.tsdb.retention.time=365d` and `--storage.tsdb.retention.size=12GB`, and its jobs include `prometheus`, `node`, `cadvisor`, `postgres` and `grafana`.
  - **`grafana_uses_postgres_and_provisioned_sources`:**
    - `GF_DATABASE_TYPE == "postgres"`;
    - the admin password comes from `${GF_SECURITY_ADMIN_PASSWORD}`;
    - the data sources have uids `prometheus` (the default) and `cloudwatch` (region `us-east-1`);
    - `bundle.secrets` maps both Grafana variables to their parameters;
    - `generated == ["POSTGRES_PASSWORD"]`.
  - **`a_service_is_recreated_only_when_its_files_change`:** `compose.services.prometheus.labels["monitoring.config-hash"] == sha256(local.bundle.files["prometheus/prometheus.yml"])`.

- [ ] **Step 2: Run them to see them fail.** Expected: FAIL.

- [ ] **Step 3: Implement `bundle.tf`, the Caddyfile and the blackbox config.**

- [ ] **Step 4: Run the whole suite.** Run: `scripts/check.sh`. Expected: `All checks passed.`

- [ ] **Step 5: README.** Cover:
  - what it creates, and the data volume layout;
  - how a change rolls out (the bundle, the 5-minute timer, or `systemctl start monitoring-reconcile` through Session Manager);
  - the status parameter's values;
  - recovery (spec 6.11);
  - reaching Grafana without a domain: `aws ssm start-session --document-name AWS-StartPortForwardingSession --parameters portNumber=3000,localPortNumber=3000`;
  - the secrets the owner must set first.

- [ ] **Step 6: Commit.** `feat(monitoring-node): render the container stack as a content-addressed bundle` (with the trailer).

---

### Task 5: Publish 0.3.0 (owner permission, asked for at this step)

- [ ] **Step 1:** Push and open the PR (`feat.md`). Expected: CI is green.
- [ ] **Step 2:** Squash-merge, then merge the `release 0.3.0` PR. Expected: the tag `v0.3.0` exists.
- [ ] **Step 3:** Record it on the Jaws docs branch: tick this plan, set the roadmap, and update spec 6.5 with what was built (the hop limit of 2, the bundle format, the reconciler order).
