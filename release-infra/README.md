# release-infra/

Jaws's release infrastructure, in the production account (the primary account
in `config/`):

- **The repository.** The ECR Public repository `jaws`, where every Jaws release
  publishes its image: `public.ecr.aws/<alias>/jaws`. Other organizations pin a
  release of it in their platform's `Dockerfile`.
- **The role.** `release-infra-publish`, which the release workflow assumes
  (GitHub OIDC, the `publish` environment of `Jaws-Platform/jaws`) to log in to
  ECR Public, push the image and prune its old versions.

It is the vendor's, not a platform's: the image is Jaws's product, so the
repository holds no one's configuration and lives with Jaws's own account, as
the spec's section 6.8 sets out.

**The owner's root.** Like `owner-access/` and `billing-export/`, it is applied
only by the owner, with the production account's admin profile, and never by CI:
no CI role, workflow or state prefix names it (`tests/test_release_infra.py`).
Two guards stop a wrong apply: the plan fails unless the credentials belong to
the production account (`main.tf`), and the repository has `prevent_destroy`.
Its state is in the platform's shared state bucket (`state.bucket`), under
`project=release-infra/env=prod/`. What keeps CI out of that state is IAM: no CI
role is granted the prefix. The bucket policy does not, since it exempts the
foundation's apply role, so only a reviewed foundation change could open it.
Agents never plan it against that state.

## Run it

The owner's hand-off for the first apply is in the release plan,
[plan 04's "Owner hand-off"](../docs/superpowers/plans/2026-11-23-hub-split-04-images.md#owner-hand-off-after-the-pr-merges)
(and in README.md's "Owner hand-off"). In this order:

1. Create the `publish` environment first, with its deployment branches set to
   `main` only: the role trusts it. Add a tag ruleset on `refs/tags/v*` that
   restricts creating, updating and deleting tags, with only the release bot's
   GitHub App allowed to bypass it. The release already refuses a tag that is
   not on `main`'s history; the ruleset also stops a tag pushed at an older
   commit of `main`, or one moved, so that only Release Please's tags are
   published.
2. Apply it:

   ```sh
   aws sso login --profile jaws-prod
   export AWS_PROFILE=jaws-prod
   cd release-infra
   terraform init -backend-config=backend/prod.hcl
   terraform plan -out=tfplan    # 3 to add: the repository jaws, the role, its inline policy
   terraform apply tfplan
   ```

3. Request the registry alias `jaws` in the ECR Public console (Public
   registry, Settings).
4. Once it is approved and primary, refresh and read the outputs:

   ```sh
   terraform apply -refresh-only
   terraform output -raw repository_uri   # public.ecr.aws/<alias>/jaws: JAWS_PUBLIC_IMAGE
   terraform output -raw role_arn         # JAWS_PUBLISH_ROLE_ARN
   ```

   and set them as the repository variables `JAWS_PUBLIC_IMAGE` and
   `JAWS_PUBLISH_ROLE_ARN`. Check that the address names the approved alias
   before setting the first.
5. From the repository root, run `scripts/apply-repo-settings.sh` again, so that
   this folder's check, `Release infrastructure validate, tflint, test`, is
   required.

## Changing it

- **The role's name stays outside `jaws-*`.** The foundation's apply role
  manages every `<name_root>-*` role, and this one is the owner's alone
  (`tests/platform/test_release_infra.py` checks).
- **The role may push and prune, and nothing else.** Its three statements log
  in, push to the repository `jaws` and describe and delete its images; widening
  it is a review of the release, not of a plan.
- **The repository is never destroyed or renamed.** It holds every release
  customers pin, so it has `prevent_destroy`, and a new name is a new address.
- **jaws-ci's version moves with the family.** The `github-oidc-role` pin is
  bumped with every other `jaws-ci` pin (`tests/test_versions.py` checks).

Locally, with no credentials:

```sh
terraform init -backend=false && terraform validate && terraform test
```
