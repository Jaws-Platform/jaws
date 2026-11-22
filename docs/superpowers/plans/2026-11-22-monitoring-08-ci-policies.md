# CI Policies for the Monitoring Stack Implementation Plan (08)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `monitoring` family to `terraform-aws-jaws-ci`'s policy catalog, so Jaws's monitoring CI roles can plan and apply the `monitoring/` stack, and release it as 0.3.0. The stack is the root module of `Jaws-Platform/jaws-monitoring/aws` 0.8.0: the billing normalizer plus the monitoring node.

**Architecture:** five leaves under `modules/ci-policies/monitoring/`, in the catalog's existing shape (one `aws_iam_policy.this`, the document built in HCL, a frozen description, `tags = { Component = "ci" }`). Write leaves grant no reads, and the apply role also takes the read leaf, as the catalog does. Every grant is scoped to the stack's names, `<prefix> = <name_root>-<project>`. In Jaws that is `jaws-monitoring`.

**Tech Stack:** Terraform `terraform test` with mock providers; `scripts/check.sh`.

**Spec:** [docs/superpowers/specs/2026-11-21-monitoring-node-design.md](../specs/2026-11-21-monitoring-node-design.md), 8 (the foundation's monitoring CI roles). The module's resources are in `terraform-aws-jaws-monitoring` 0.8.0: `modules/billing-normalizer/*.tf`, `modules/monitoring-node/*.tf`, and the root `main.tf`.

## Global Constraints

**Where things live**
- **Repo:** `/Users/jimmywallace/Projects/Jaws-Platform/terraform-aws-jaws-ci`, branch `feat/monitoring-policies` from `origin/main` (0.2.0).
- **Pattern to copy:** `modules/ci-policies/container/schedule/`, `container/read/` and `container/manage/` (statements, Sids, tests, README). Adding a leaf follows `modules/ci-policies/README.md:217-233`.

**Conventions**
- Commits are one line, at most 100 characters, scoped to the module touched (`feat(ci-policies): …`), ending `Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>`.
- PRs use `.github/PULL_REQUEST_TEMPLATE/feat.md`.
- No cloud calls.

**Size:** every leaf fits the 6,144-character managed-policy limit. Add the five leaves to `every_policy_fits_the_managed_policy_size_limit`.

**Scope: the names the monitoring module creates** (`<prefix>` = `<name_root>-<project>`, `<account>`, `<region>`):

| Kind | Names |
|---|---|
| IAM roles | `<prefix>` (the node), `<prefix>-schedule`, `<prefix>-snapshots`, `<prefix>-watchdog`, `<prefix>-watchdog-schedule`, `<prefix>-normalizer`, `<prefix>-normalizer-scheduler` |
| Instance profile | `<prefix>` |
| Lambda functions | `<prefix>-normalizer`, `<prefix>-watchdog` |
| Log groups | `/aws/lambda/<prefix>-normalizer`, `/aws/lambda/<prefix>-watchdog` |
| Schedules (group `default`) | `<prefix>-start`, `<prefix>-stop`, `<prefix>-watchdog`, `<prefix>-normalizer` |
| SNS topic | `<prefix>-watchdog` |
| Alarms | `<prefix>-system-status`, `<prefix>-instance-status` |
| Backup | vault and plan `<prefix>-snapshots`; selection `<prefix>-data` |
| S3 | `<prefix>-config-<account>` and its objects |
| SSM parameters | `/<prefix>/*` (the node writes `/<prefix>/node/*`) |
| EC2 | the instance, its data volume and its security group, tagged `Project = <project>` (from the provider's `default_tags`) and `Component = monitoring` |
| Route 53 | the record `var.domain` in `var.zone_id` (inputs; null means none) |

So IAM and Lambda patterns are `<prefix>` and `<prefix>-*`: the node's own role and profile are exactly `<prefix>`.

**The leaves**

| Leaf | Class | Grants |
|---|---|---|
| `monitoring/read` | read | Everything `terraform plan` refreshes for these resources: EC2 `Describe*`, the AMI lookup and the subnet; IAM `Get*`/`List*` on the roles and profile; Lambda `GetFunction*`, `GetPolicy`, `ListVersionsByFunction`, `ListTags`; `scheduler:GetSchedule`; `logs:DescribeLogGroups` and `ListTagsForResource`; SSM `GetParameter(s)`, `DescribeParameters`, `ListTagsForResource`; S3 bucket `Get*`/`List*` and `GetObject` on the config bucket; Backup `Describe*`/`Get*`/`List*` on the vault and plan; `cloudwatch:DescribeAlarms`, `ListTagsForResource`; SNS `GetTopicAttributes`, `GetSubscriptionAttributes`, `ListTagsForResource`; Route 53 `GetHostedZone`, `ListResourceRecordSets`, `GetChange` |
| `monitoring/node` | write | EC2 `RunInstances` (request tag `Project` = `var.project`), `TerminateInstances`, `StopInstances`, `StartInstances`, `ModifyInstanceAttribute` (resource tag); `CreateVolume`, `AttachVolume`, `DetachVolume`, `DeleteVolume`, `ModifyVolume`; the security group and its rules; `CreateTags` bounded by `ec2:CreateAction` or the resource tag; IAM role and instance-profile lifecycle, inline policies, and `AttachRolePolicy` limited to `arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup`; `iam:PassRole` of `<prefix>` to `ec2.amazonaws.com` |
| `monitoring/config` | write | The config bucket's lifecycle and settings, and `PutObject`/`DeleteObject` on its objects; SSM `PutParameter`, `DeleteParameter`, `AddTagsToResource`, `RemoveTagsFromResource` on `/<prefix>/*`; with a `zone_id` and `domain`, `route53:ChangeResourceRecordSets` in that zone limited to that record name (`route53:ChangeResourceRecordSetsNormalizedRecordNames`, as `static-site/deploy` does) |
| `monitoring/functions` | write | Lambda lifecycle, configuration, code, tags and permissions on `<prefix>-*`; log group lifecycle, retention and tags on `/aws/lambda/<prefix>-*`; SNS topic lifecycle, attributes, tags, `Subscribe` and `Unsubscribe` on `<prefix>-*`; CloudWatch `PutMetricAlarm`, `DeleteAlarms`, `TagResource`, `UntagResource` on `alarm:<prefix>-*`; Scheduler `CreateSchedule`, `UpdateSchedule`, `DeleteSchedule` on `schedule/default/<prefix>-*`; `iam:PassRole` of `<prefix>-*` to `lambda.amazonaws.com` and `scheduler.amazonaws.com` |
| `monitoring/backup` | write | Backup vault, plan and selection lifecycle, and tags, on `<prefix>-snapshots`, plus what `CreateBackupVault` needs for the default key (`backup-storage:MountCapsule`; `kms:CreateGrant`, `kms:DescribeKey` and `kms:GenerateDataKey` via `backup.<region>.amazonaws.com`); `iam:PassRole` of `<prefix>-snapshots` to `backup.amazonaws.com` |

**Inputs** (the catalog's `policy_inputs`, validated like `static-site`'s): `monitoring/config` takes `zone_id` and `domain`, both optional (null means no Route 53 statement).

**Known gaps** (README table): `ec2:Describe*`, `logs:DescribeLogGroups`, `ssm:DescribeParameters` and `backup:List*` take no resource, as the catalog's other gaps don't.

## Review Focus

1. **A plan or apply denied in real AWS** for an action the mocks can't see, such as `ec2:DescribeInstanceAttribute`, `iam:ListInstanceProfilesForRole`, `lambda:GetFunctionCodeSigningConfig`, `s3:GetBucketObjectLockConfiguration` or `backup:GetBackupVaultAccessPolicy`. Check each Terraform resource type's read and write calls against the provider (6.x). Test: each leaf's exact-statement test lists its actions. Reading the provider's resource code is the check.
2. **A grant wider than the stack**, such as `*`, another project's prefix, or PassRole without `iam:PassedToService`. Test: each leaf's `grants_nothing_else`.
3. **The node's own role and profile, named exactly `<prefix>`, fall outside `<prefix>-*`.** Test: `monitoring_node_manages_the_node_role_by_its_exact_name`.
4. **Size:** a leaf over 6,144 characters fails at apply. Test: the catalog's size run.
5. **No domain** gives `monitoring/config` without the Route 53 statement. Test: `monitoring_config_without_a_domain_changes_no_records`.

---

### Task 1: The five leaves

**Files:**
- Create: `modules/ci-policies/monitoring/{read,node,config,functions,backup}/{main,variables,outputs,versions}.tf`, `README.md`, and `tests/<leaf>.tftest.hcl` in each.

- [ ] **Step 1: Write each leaf's tests** in the `container_schedule.tftest.hcl` style, with `name_root = "jaws"` and `project = "monitoring"`:
  - **`<leaf>_grants_exactly_these_statements`:** every statement's Sid, actions, resources and conditions, with `jaws-monitoring` names.
  - **`<leaf>_grants_nothing_else`:** the Sid list, and no `Resource = "*"` outside the leaf's listed Known gaps.
  - **`description_is_frozen`.**
  - **`monitoring_node_manages_the_node_role_by_its_exact_name`:** the IAM role and instance-profile statements list both `role/jaws-monitoring` and `role/jaws-monitoring-*`.
  - **`monitoring_config_without_a_domain_changes_no_records`:** with `zone_id` null, no `route53:ChangeResourceRecordSets`.
- [ ] **Step 2: Run** `scripts/check-module.sh modules/ci-policies/monitoring/<leaf>`. Expected: it fails, with no module yet.
- [ ] **Step 3: Implement** each leaf to the table.
- [ ] **Step 4: Run it again.** Expected: it passes, and each policy is under 6,144 characters.
- [ ] **Step 5: Commit** each leaf: `feat(ci-policies): add the monitoring/<leaf> policy`.

### Task 2: The catalog and the roles

**Files:**
- Modify:
  - `modules/ci-policies/{main,outputs,variables}.tf` and its README (the catalog and family tables);
  - `modules/ci-policies/tests/ci_policies.tftest.hcl`;
  - the plan and apply role modules' variable docs and READMEs.

- [ ] **Step 1: Write the failing tests:**
  - **`a_plan_role_takes_monitoring_read`:** `monitoring/read` is accepted for the plan role, and the write leaves are rejected.
  - **`an_apply_role_takes_every_monitoring_leaf`.**
  - **The size run** covers the five new leaves (19 in all).
- [ ] **Step 2: Run** `scripts/check-module.sh modules/ci-policies`. Expected: it fails.
- [ ] **Step 3: Register the five leaves** in `local.catalog`, the module blocks, `local.created` and `policy_inputs` (`monitoring/config`'s `zone_id` and `domain`).
- [ ] **Step 4: Run** `scripts/check.sh`. Expected: all checks pass.
- [ ] **Step 5: Commit** `feat(ci-policies): add the monitoring family to the catalog`.

### Task 3: Review and release

- [ ] **Step 1: Final review** (opus, whole branch), focused on the Review Focus. One fix pass for Critical and Important findings, each RED→GREEN.
- [ ] **Step 2: Push, open the PR** (`feat.md` template) with the title `feat(ci-policies): add the monitoring family for the monitoring stack`, **merge it once CI is green, and merge the Release Please PR for 0.3.0.** The owner allowed this for the overnight run of 2026-11-22. Releasing a policy module applies nothing.
- [ ] **Step 3: Record it** in the roadmap (08 released) and a spec note.
