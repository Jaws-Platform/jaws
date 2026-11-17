# Bootstrapping the production account

One time, by the owner, with admin credentials. It gives the production account
(570327089884) a foundation that CI can then plan and apply like the management
account's: a state bucket, the tool's own two CI roles, the image repository
and a hosted zone. No project moves here; that comes after, one project at a
time. Nothing is created in the development account.

Do the steps in order. Each says what a correct result looks like; if a result
differs, stop there.

## Before you start

- `main` is clean and up to date, and contains this file.
- Terraform is the version `config.yaml` pins (`terraform version`).
- You can sign in to the management account: `aws sso login --profile jwall-admin`.

## 1. Give yourself admin access to production

The `owner-access/` stack assigns your `AdministratorAccess` permission set in
the production account as well. Apply it as [owner-access.md](owner-access.md#applying-owner-access)
describes:

```sh
cd owner-access
export AWS_PROFILE=jwall-admin
terraform init -backend-config=backend/prod.hcl
terraform plan -out=owner-access.tfplan
```

The plan must be **1 to add, 0 to change, 0 to destroy**: one
`aws_ssoadmin_account_assignment.additional["570327089884"]`. Then:

```sh
terraform apply owner-access.tfplan
terraform output -raw aws_config
```

Add the printed `[profile jaws-prod]` block to `~/.aws/config`, then:

```sh
aws sso login --profile jaws-prod
aws sts get-caller-identity --profile jaws-prod --query Account --output text
```

Correct: `570327089884`.

## 2. Tell the tool your admin role's name in production

Identity Center created a role for you in the production account, with a suffix
only AWS knows. The hardened bucket policies exempt that exact role, so the
tool needs its ARN before it creates any bucket.

```sh
aws iam list-roles --profile jaws-prod \
  --path-prefix /aws-reserved/sso.amazonaws.com/ \
  --query 'Roles[?starts_with(RoleName, `AWSReservedSSO_AdministratorAccess_`)].Arn' --output text
```

Correct: one ARN, `arn:aws:iam::570327089884:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_<16 hex>`.

It goes into `config.yaml` as `production.overrides.aws.admin_role_arn` (and
the same line in `tests/fixtures/config.yaml`), in a pull request merged before
step 5. The foundation refuses to plan for production without it.

## 3. Ask for the quotas production will need

A new account has default quotas, far below what the task runners use. Compare
the two accounts and request every value production has lower. Approval takes
from minutes to a few days, so do this now.

```sh
for service in ec2 vpc; do
  for profile in jwall-admin jaws-prod; do
    aws service-quotas list-service-quotas --service-code "$service" \
      --profile "$profile" --region us-east-1 \
      --query 'Quotas[].[QuotaCode,QuotaName,Value]' --output text | sort \
      > "/tmp/quotas-$service-$profile.txt"
  done
  diff "/tmp/quotas-$service-jwall-admin.txt" "/tmp/quotas-$service-jaws-prod.txt"
done
```

The ones that matter, at least:

| Quota | Code | Why |
| --- | --- | --- |
| VPCs per Region | `L-F678F1CE` | one per bot, research and Databricks project; the management account was raised to 10 |
| Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances | `L-1216C47A` | task runners fall back to on demand; `tasks.limits.max_vcpus` is 256 |
| All Standard (A, C, D, H, I, M, R, T, Z) Spot Instance Requests | `L-34B43A08` | task runners run on spot |
| Running On-Demand G and VT instances | `L-DB2E81BA` | the trainer's GPU profile |

For each, with the management account's value:

```sh
aws service-quotas request-service-quota-increase --profile jaws-prod --region us-east-1 \
  --service-code ec2 --quota-code L-1216C47A --desired-value <value>
```

(`--service-code vpc` for the VPC quota.) Nothing below waits for these; the
first project to move does.

## 4. Create the GitHub OIDC provider

An account holds one OIDC provider per URL, and the foundation reads it rather
than owning it, as in the management account.

```sh
aws iam create-open-id-connect-provider --profile jaws-prod \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com
```

Correct: it prints `arn:aws:iam::570327089884:oidc-provider/token.actions.githubusercontent.com`.

## 5. Apply the foundation with local state

The state bucket does not exist yet, so the first apply keeps its state in a
local file. Step 2's pull request must be merged and pulled first.

```sh
cd foundation
export AWS_PROFILE=jaws-prod
printf 'terraform {\n  backend "local" {}\n}\n' > backend_override.tf
terraform init
terraform plan -var account=production -out=bootstrap.tfplan
```

If the plan stops with "These credentials belong to account …", the profile is
wrong; with "no admin_role_arn …", step 2 is not merged.

Read the plan. It must be **39 to add, 0 to change, 0 to destroy**, and only
these:

- the state bucket `jaws-terraform-state`, with its versioning, encryption,
  ownership controls, public access block and policy (6);
- four roles, `jaws-infra-ci-plan`, `jaws-infra-ci-apply`,
  `jaws-data-access-ci-plan` and `jaws-data-access-ci-apply`, with twelve
  managed policies and their twelve attachments (28);
- the image repository `jaws-cli` and its lifecycle policy (2);
- a hosted zone `jwall.engineering`, with its CAA record and one TXT record (3).

No site bucket, no project role, nothing from Databricks, and nothing whose name
starts with `jwall-engineering-`. Then:

```sh
terraform apply bootstrap.tfplan
```

## 6. Move the state into the bucket

```sh
rm backend_override.tf
terraform init -backend-config=backend/production.hcl -migrate-state
rm -f terraform.tfstate terraform.tfstate.backup bootstrap.tfplan
terraform plan -var account=production
```

Correct: the last plan says **No changes**.

## 7. Hand over the zone

```sh
terraform output -raw hosted_zone_id
terraform output hosted_zone_name_servers
```

The zone ID goes into `config.yaml` as `production.overrides.dns.zone_id`,
together with `production.bootstrapped: true`. That pull request is the first
one whose checks plan the production account; its plan must say "No changes".

**Do not change the name servers at the registrar.** The new zone is empty and
the old one still serves every site. The name servers are switched later, as
its own step, once the new zone holds a copy of every record.

## What exists afterwards

In the production account: the state bucket, four roles that only this
repository's workflows can assume, an empty image repository, an empty hosted
zone that is not yet authoritative, and the OIDC provider. Cost: the hosted
zone, $0.50 a month. Everything in the management account is untouched.

## Undoing it

Before any project has moved, the production foundation can be removed with
admin credentials: `terraform destroy -var account=production` from
`foundation/` after emptying the state bucket's other prefixes (there are none
yet). The state bucket and the hosted zone refuse to be destroyed by design;
remove them from state (`terraform state rm`) and delete them in the console.
