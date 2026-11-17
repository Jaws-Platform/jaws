# Owner access: admin through IAM Identity Center

The account's owner gets AdministratorAccess from **IAM Identity Center**: one
browser sign-in with a passkey gives the console and short-lived CLI
credentials. There is no IAM user and no access key. Root is the backup.

| Piece | Where it lives |
| --- | --- |
| The organization, the Identity Center instance, MFA rules, sign-in length, email OTP | The console, set once ([below](#one-time-console-setup)) |
| The Identity Center user, the `AdministratorAccess` permission set and its assignment to this account | [`owner-access/`](../owner-access), from the library's [`identity-center-access`](https://registry.terraform.io/modules/jwallace145/jwall-engineering/aws/latest/submodules/identity-center-access) module, **applied only by the owner** |
| The admin role's exemption from the hardened state and site bucket policies | `bucket_admin_principal_arns` in `foundation/state.tf`, applied by CI on release |
| The `jwall-admin` CLI profile | The owner's `~/.aws/config`, from `terraform output -raw aws_config` |

Organizations and Identity Center are free.

## How it behaves

- **Two timers.** The Identity Center sign-in lasts 12 hours (one passkey tap
  per workday). Each set of credentials from the permission set lasts 1 hour.
  The AWS CLI, Terraform (provider and S3 backend) and boto3 renew credentials
  on their own until the sign-in runs out; then run `aws sso login` again. A
  `terraform apply` running when the sign-in expires can fail partway; sign in
  and re-run it. The console sends you back to the portal for one click each
  hour.
- **Nothing can act as admin without you.** Until you sign in, nothing on your
  machine has AWS access, coding agents included. After you sign in, anything
  running as you can use the session until it ends.
- **The admin role is AWS-managed.** Identity Center provisions it as
  `AWSReservedSSO_AdministratorAccess_<suffix>` under
  `/aws-reserved/sso.amazonaws.com/`, and IAM refuses edits to it, so neither CI
  nor a stray apply can change your access.
- **The infra CLI works as before.** Commands that check for a CI role still
  need `JAWS_SKIP_ROLE_CHECK=1` from your shell; owner-shell commands
  (`bot secrets set`, `cost report`, `databricks credentials set`) need nothing.

## Daily use

```sh
aws sso login --profile jwall-admin     # browser opens; passkey; good for 12 hours
export AWS_PROFILE=jwall-admin
terraform plan                          # credentials renew on their own
uv run jaws cost report
aws sso logout                          # end the session early
```

A tool that wants keys or environment variables gets temporary ones, valid at
most an hour:

```sh
eval "$(aws configure export-credentials --profile jwall-admin --format env)"
```

The console is at the access portal URL (`terraform -chdir=owner-access output
-raw access_portal_url`): pick the account, then **AdministratorAccess**.

## One-time console setup

As root, in **us-east-1**:

1. Open **IAM Identity Center** and choose **Enable**. The console offers to
   create an organization with this account as its management account: accept.
   Identity Center lives in one region, and this is it.

   Never run `aws sso-admin create-instance`. It creates an *account* instance,
   which cannot grant access to AWS accounts and cannot be converted later.

2. In Identity Center's **Settings**:
   - **Authentication → Multi-factor authentication:** prompt users for MFA
     **every time they sign in**; allow **security keys and built-in
     authenticators** and **authenticator apps**; if a user has no registered
     MFA device, **require them to register one at sign in**. Sign in with a
     passkey day to day (it only works on the real AWS domain, so it can't be
     phished) and keep an authenticator app as the backup.
   - **Authentication → Session duration:** user interactive sessions,
     **12 hours**.
   - **Authentication → Standard authentication:** turn on **Send email OTP**
     for users created from the API. Terraform creates your user without a
     password; this emails you a one-time password at first sign-in. (Otherwise,
     generate a one-time password for the user in the console after the apply.)
   - Keep the default identity source (the Identity Center directory) and the
     default access portal URL.

3. Optional, in **Account → IAM user and role access to Billing information**:
   **Activate**. Without it the console's Billing and Cost Explorer pages are
   closed to the admin role. The Cost Explorer API that `cost report` uses does
   not depend on it.

What the organization changes: nothing that exists. SCPs never apply to the
management account. AWS adds its service-linked roles and Identity Center's
SAML provider (`AWSSSO_*_DO_NOT_DELETE`) to IAM. Terraform does not manage the
organization: with one account there is nothing to configure, a managed
trusted-access list could silently cut Identity Center off, and deleting an
organization deletes the account's Cost Explorer data. Treat it as permanent.

## Applying `owner-access/`

Only the owner applies this stack, from a clean, up-to-date `main`, with admin
credentials. Release Please never applies it, and no CI role could: none has
Identity Center permissions, and its state (`project=owner-access/` in the
shared bucket) is reachable only by the break-glass principals.

```sh
cd owner-access
export AWS_PROFILE=jwall-admin   # the first time: an existing break-glass admin
terraform init -backend-config=backend/prod.hcl
terraform plan -out=owner-access.tfplan
terraform apply owner-access.tfplan
```

The stack refuses to plan until Identity Center is enabled and this account is
its organization's management account.

The user and the permission set have `prevent_destroy`. Recreating the
permission set gives its role a new suffix, which locks the old ARN out of the
bucket policies; recreating the user drops its passkeys. Do either only on
purpose, and expect to update `foundation/state.tf`.

The stack also assigns the same permission set in the production account
(`production.overrides.aws.account_id` in `config.yaml`), where everything is
moving, and `terraform output -raw aws_config` prints a `jaws-prod` profile for
it beside `jwall-admin`. The role Identity Center provisions there has its own
suffix; [production-bootstrap.md](production-bootstrap.md) reads it. The
development account gets no assignment: nothing is built there.

## First sign-in and the CLI profile

1. Open `terraform output -raw access_portal_url`. Sign in as `jwallace145`
   with the emailed one-time password, set a password, and register two MFA
   devices, such as a passkey on this Mac and an authenticator app, so losing
   one isn't a lockout.
2. Add the profile:

   ```sh
   terraform output -raw aws_config >> ~/.aws/config
   aws sso login --profile jwall-admin
   aws sts get-caller-identity --profile jwall-admin
   # arn:aws:sts::650503560686:assumed-role/AWSReservedSSO_AdministratorAccess_<suffix>/jwallace145
   ```

   The profile is named, never `default`, so nothing uses admin without asking
   for it.

## The break-glass entry

The state bucket and every site bucket deny everyone except their CI roles
and the principals in `bucket_admin_principal_arns` (`foundation/state.tf`).
The admin role must be on that list, by its exact ARN, path included:

```sh
terraform -chdir=owner-access output -raw admin_role_arn
```

If that prints nothing right after the first apply, IAM hasn't listed the new
role yet: run `terraform apply -refresh-only` and try again.

Put the ARN in the list as a literal (CI roles cannot list IAM roles, and a
lookup that came back empty would silently drop you), open a PR, and release.
CI applies it. Fixing your own access to state therefore needs no AWS
credentials, only a merged PR and a release.

If the permission set is ever recreated, its role gets a new suffix: update
the literal the same way, and use root until that release lands.

## Root: the emergency path

Root is untouched by Organizations (centralized root access applies only to
member accounts) and by Identity Center (root signs in separately), so it
works when Identity Center is down or misconfigured. It stays on the
break-glass list and never gets access keys. Give it a second MFA device kept
offline.

For emergency CLI or Terraform work as root, `aws login` needs no setup:

```sh
aws login --profile root-login          # browser sign-in as root; up to 12 hours
```

Terraform 1.14's S3 backend doesn't read `aws login` sessions, so bridge them
through a process-credentials profile in `~/.aws/config`:

```ini
[profile root-break-glass]
credential_process = aws configure export-credentials --profile root-login --format process
region = us-east-1
```

Then `AWS_PROFILE=root-break-glass terraform plan`, and `aws logout --profile
root-login` when done. Use root when Identity Center is down or misconfigured,
when a stale break-glass ARN locks the admin role out, and for root-only tasks
such as the Billing access switch.

## History: retiring the `prog-strength-admin` access key

Until 2026-11-15 the owner worked through the IAM user `prog-strength-admin`
and a long-lived access key with AdministratorAccess and no MFA. The cutover
kept at least two ways in at every step (root always):

1. A second MFA device on root.
2. The [console setup](#one-time-console-setup), after the release that added `owner-access/`.
3. The first apply of `owner-access/`, made with the old key (then a break-glass principal).
4. The [first sign-in](#first-sign-in-and-the-cli-profile) and the `jwall-admin` profile.
5. The role's ARN added to `bucket_admin_principal_arns` (#154, release 0.35.0).
6. The [verification](#verification) below, run as `jwall-admin`.
7. The key deactivated, then deleted; `AdministratorAccess` detached and the
   user deleted; its sections removed from `~/.aws/credentials` and `~/.aws/config`.
8. The user removed from `bucket_admin_principal_arns` and README.

The account has no IAM users since. Ways in: the `jwall-admin` Identity Center
session, and root for emergencies.

## Verification

With `AWS_PROFILE=jwall-admin`:

- `aws sts get-caller-identity` shows `assumed-role/AWSReservedSSO_AdministratorAccess_*/jwallace145`.
- `terraform -chdir=owner-access plan` shows no changes (the state bucket
  exempts the role), and a plan in `foundation/` runs.
- `aws s3 ls s3://jwall-engineering-tfstate/`, a site bucket and
  `s3://jwall-engineering-braveheart-nnue/data/` list.
- `uv run jaws cost report` prints the table.
- Through the portal, the console browses the state bucket and a site bucket.
- An hour later a command still works without a prompt; after the sign-in has
  expired it asks for `aws sso login`; after `aws sso logout` commands fail.
