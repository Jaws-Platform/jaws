# Billing Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the new `terraform-aws-jaws-monitoring` module repository with its first two submodules: `billing-bucket`, the never-delete billing bucket, and `aws-billing-export`, the org-wide FOCUS 1.2 daily Data Export delivered cross-account. Then release it as 0.1.0.

**Architecture:**
- The repo copies the tooling of `terraform-aws-jaws-lichess-bot`: scripts, CI, commitlint, Release Please and the conventions.
- Both submodules are plain Terraform, tested with `terraform test` and a mocked AWS provider. Nothing needs credentials.
- The root module is a documented placeholder in this plan. Plan 06 turns it into the all-in-one composition.

**Tech Stack:**
- Terraform 1.14.7 (`>= 1.11`), with `hashicorp/aws` `>= 6.73, < 7.0` for the export and `~> 6.0` for the bucket;
- tflint 0.59.1 with the aws ruleset 0.49.0, and terraform-docs 0.24.0;
- Node 24 for commitlint.

**Spec:** [docs/superpowers/specs/2026-11-21-monitoring-node-design.md](../specs/2026-11-21-monitoring-node-design.md), sections 6.1, 6.2, 7 and 12.1–2. Series: [00-roadmap](2026-11-21-monitoring-00-roadmap.md).

## Global Constraints

**Where things live**
- **New repo:** `Jaws-Platform/terraform-aws-jaws-monitoring`, cloned locally at `/Users/jimmywallace/Projects/Jaws-Platform/terraform-aws-jaws-monitoring` (written `$REPO` below).
- **Template:** `/Users/jimmywallace/Projects/Jaws-Platform/terraform-aws-jaws-lichess-bot` (written `$TEMPLATE`).
- **Registry address:** `Jaws-Platform/jaws-monitoring/aws`.

**Module conventions**
- Modules never configure a provider and never take a tag map. Each resource gets `Name` (where it has one) and `Component` from the module; every other tag comes from the caller's `default_tags`.
- Both modules here set `Component = "billing"`.
- No organisation names in module code. Examples use `acme`, `example.com` and the account IDs `111111111111` and `222222222222`.
- Every module has `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`, a `README.md` (terraform-docs between `BEGIN_TF_DOCS` and `END_TF_DOCS`), `examples/basic/` and `tests/`.
- Usage snippets pin the module with a line ending in `# x-release-please-version`.

**Repo rules**
- **Commits:** one line, `type(scope)?: subject`, at most 100 characters. Then only a blank line and `Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>`, with exactly that casing; commitlint rejects `Co-Authored-By`.
- **Changes reach `main` only through a PR** opened with a typed template (`gh pr create --template feat.md`), with every section filled.
- **No cloud:** CI has no cloud credentials, and nothing in this plan runs `terraform apply` or calls AWS.
- **Owner steps:** creating the GitHub repo, setting its secrets, applying its settings, merging, and publishing on the registry. Each one happens only with the owner's explicit permission at that step.

**Fixed values from the spec**
- **Bucket layout:**
  - AWS deliveries go under `raw/provider=aws/source=data-exports`;
  - other sources follow `raw/provider=<p>/source=<s>/`;
  - the normalized output goes under `normalized/`.
- **Raw protection:** the bucket policy denies `s3:DeleteObject` and `s3:DeleteObjectVersion` on `raw/*` to `"*"` when `protect_raw` is true (the default). Raw data never expires. Noncurrent versions under `normalized/` expire after 30 days (the default).
- **Bucket settings:**
  - versioning `Enabled`;
  - SSE-S3 (`AES256`);
  - `BucketOwnerEnforced`;
  - all four Block Public Access settings on;
  - non-TLS requests denied;
  - incomplete multipart uploads aborted after 7 days.
- **Data Exports delivery statement:**
  - principal `bcm-data-exports.amazonaws.com`;
  - action `s3:PutObject` on `arn:aws:s3:::<bucket>/*`;
  - `ArnLike` `aws:SourceArn` = `arn:aws:bcm-data-exports:us-east-1:<account>:export/*`;
  - `StringEquals` `aws:SourceAccount` = `<account>`.
- **The export:**
  - table `FOCUS_1_2_AWS`, with configuration `{ FOCUS_1_2_AWS = { TIME_GRANULARITY = "DAILY" } }`;
  - all 60 FOCUS 1.2 columns, listed explicitly;
  - output `PARQUET` / `PARQUET` / `CUSTOM`, overwrite `CREATE_NEW_REPORT`, refresh `SYNCHRONOUS`;
  - cross-account through `s3_bucket_owner` (verified in provider v6.73.0, 2026-11-21).

## Review Focus

1. **Account IDs that aren't 12-digit strings.** An ID like `"12345"`, or one that has lost its leading zeros, must be rejected at plan, not turn into a policy that silently never matches (Task 2, `rejects_malformed_export_account_ids`; Task 3, `rejects_a_malformed_bucket_owner`).
2. **Turning `protect_raw` off.** Only the delete deny may go. The TLS deny and the delivery allow must stay, or Data Exports stops delivering (Task 2, `protect_raw_off_keeps_tls_and_delivery`).
3. **A bucket with no export accounts,** the default. The policy must be valid, with no `Allow` statement and no empty principal list (Task 2, `defaults_protect_raw_and_require_tls`).
4. **A same-account export.** With `bucket_owner_account_id` null, `s3_bucket_owner` must be null, not an empty string, which AWS would reject (Task 3, `same_account_leaves_the_bucket_owner_unset`).
5. **A prefix with a leading, trailing or doubled slash.** It would scatter deliveries under a key nobody reads. It must be rejected (Task 3, `rejects_prefixes_with_stray_slashes`).

---

### Task 1: Bootstrap the repository

**Files:**
- Create, copied verbatim from `$TEMPLATE`:
  - `.github/CODEOWNERS`
  - `.github/PULL_REQUEST_TEMPLATE/{chore,ci,docs,feat,fix,refactor}.md`
  - `.github/pull_request_template.md`
  - `.github/dependabot.yml`
  - `.github/workflows/ci.yml`
  - `.github/workflows/release-please.yml`
  - `.gitignore`
  - `.pre-commit-config.yaml`
  - `.terraform-docs.yml`
  - `.tflint.hcl`
  - `AGENTS.md`
  - `CLAUDE.md`
  - `CONTRIBUTING.md`
  - `LICENSE`
  - `commitlint.config.mjs`
  - `package.json`
  - `package-lock.json`
  - `release-please-config.json`
  - `scripts/*.sh`
  - `tests/commitlint/**`
- Create: `.release-please-manifest.json` containing `{}`. Do not copy `CHANGELOG.md` or `version.txt`.
- Create: the root module, `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf` and `README.md`.
- Modify: every copied file that names the old family (Step 3).

**Interfaces:**
- Produces:
  - `scripts/check.sh` and `scripts/check-module.sh <dir>`, the local CI;
  - `scripts/list-modules.sh`, which finds modules by their `versions.tf`.

- [ ] **Step 1: Check the tools**

Run: `terraform version | head -1; tflint --version | head -1; terraform-docs --version; shellcheck --version | sed -n 2p; node --version`
Expected: Terraform v1.14.x, TFLint 0.59.x, terraform-docs v0.24.x, a shellcheck version, and node v24.x. If any is missing, stop and tell the owner.

- [ ] **Step 2: Copy the tooling**

```bash
mkdir -p "$REPO" && cd "$REPO" && git init -q -b main
cd "$TEMPLATE" && git ls-files -z -- .github .gitignore .pre-commit-config.yaml .terraform-docs.yml .tflint.hcl \
  AGENTS.md CLAUDE.md CONTRIBUTING.md LICENSE commitlint.config.mjs package.json package-lock.json \
  release-please-config.json scripts tests/commitlint | xargs -0 -I{} rsync -R {} "$REPO/"
cd "$REPO" && printf '{}\n' > .release-please-manifest.json
```

- [ ] **Step 3: Rename the family**

Run: `grep -rIn -i -E 'lichess|jaws-lichess-bot|container-instance|ecr-repository' --exclude-dir=node_modules .`
Expected: hits only in `scripts/apply-repo-settings.sh`, `package.json`, `CONTRIBUTING.md` and `.github/pull_request_template.md`.

In each of them:
- `terraform-aws-jaws-lichess-bot` becomes `terraform-aws-jaws-monitoring`;
- `jaws-lichess-bot/aws` becomes `jaws-monitoring/aws`;
- any module list becomes `billing-bucket` and `aws-billing-export`;
- prose about bots and containers becomes prose about billing storage and monitoring.

Then re-run the grep.
Expected: no output.

- [ ] **Step 4: Write the root module**

- `versions.tf`: `terraform { required_version = ">= 1.11" }`.
- `main.tf`, `variables.tf` and `outputs.tf`: comments only.
  - `main.tf` says the root becomes the all-in-one composition in a later release, and lists today's submodules.
  - `variables.tf` and `outputs.tf` each say there are no inputs or outputs yet.
- `README.md`, above the empty `BEGIN_TF_DOCS` / `END_TF_DOCS` markers:
  - a title and a one-paragraph summary of the family;
  - a table of submodules (name, what it is, applied in which account);
  - the bucket layout contract from spec 6.1, as a code block.

Generate the docs block: `terraform-docs --config .terraform-docs.yml .`

- [ ] **Step 5: Run the whole suite**

Run: `npm ci && scripts/list-modules.sh && scripts/check.sh`
Expected: `list-modules.sh` prints `.`, and `check.sh` ends with `All checks passed.`

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -q -m "chore: bootstrap the repository with the family conventions" -m "Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `billing-bucket`

**Files:**
- Create: `modules/billing-bucket/{versions.tf,variables.tf,main.tf,outputs.tf,README.md}`
- Create: `modules/billing-bucket/examples/basic/{main.tf,versions.tf}`
- Test: `modules/billing-bucket/tests/billing_bucket.tftest.hcl`

**Interfaces:**
- Consumes: nothing.
- Produces (used by plans 02, 03, 05 and 08):
  - **Inputs:**
    - `bucket_name` (string, required);
    - `aws_export_source_account_ids` (list(string), default `[]`);
    - `protect_raw` (bool, default `true`);
    - `normalized_noncurrent_days` (number, default `30`).
  - **Outputs:**
    - `name`;
    - `arn` (`"arn:aws:s3:::<name>"`, known at plan);
    - `raw_prefix` (`"raw"`);
    - `aws_export_prefix` (`"raw/provider=aws/source=data-exports"`);
    - `normalized_prefix` (`"normalized"`).

- [ ] **Step 1: Write the failing tests**

Create `tests/billing_bucket.tftest.hcl`:

```hcl
mock_provider "aws" {}

variables {
  bucket_name = "acme-billing"
}

run "defaults_protect_raw_and_require_tls" {
  command = plan

  assert {
    condition     = [for s in jsondecode(aws_s3_bucket_policy.this.policy).Statement : s.Sid] == ["DenyInsecureTransport", "DenyRawDeletes"]
    error_message = "with no export accounts the policy is the TLS deny and the raw/ delete deny, and no Allow"
  }

  assert {
    condition = one([for s in jsondecode(aws_s3_bucket_policy.this.policy).Statement : s if s.Sid == "DenyInsecureTransport"]) == {
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = ["arn:aws:s3:::acme-billing", "arn:aws:s3:::acme-billing/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }
    error_message = "requests without TLS are denied"
  }

  assert {
    condition = one([for s in jsondecode(aws_s3_bucket_policy.this.policy).Statement : s if s.Sid == "DenyRawDeletes"]) == {
      Sid       = "DenyRawDeletes"
      Effect    = "Deny"
      Principal = "*"
      Action    = ["s3:DeleteObject", "s3:DeleteObjectVersion"]
      Resource  = "arn:aws:s3:::acme-billing/raw/*"
    }
    error_message = "nobody may delete an object or a version under raw/"
  }
}

run "export_accounts_may_put_objects_from_their_own_exports" {
  command = plan

  variables {
    aws_export_source_account_ids = ["111111111111", "222222222222"]
  }

  assert {
    condition = one([for s in jsondecode(aws_s3_bucket_policy.this.policy).Statement : s if s.Sid == "AllowDataExportsDelivery"]) == {
      Sid       = "AllowDataExportsDelivery"
      Effect    = "Allow"
      Principal = { Service = "bcm-data-exports.amazonaws.com" }
      Action    = "s3:PutObject"
      Resource  = "arn:aws:s3:::acme-billing/*"
      Condition = {
        ArnLike = { "aws:SourceArn" = [
          "arn:aws:bcm-data-exports:us-east-1:111111111111:export/*",
          "arn:aws:bcm-data-exports:us-east-1:222222222222:export/*",
        ] }
        StringEquals = { "aws:SourceAccount" = ["111111111111", "222222222222"] }
      }
    }
    error_message = "Data Exports may put objects, and only for exports of the listed accounts"
  }
}

run "protect_raw_off_keeps_tls_and_delivery" {
  command = plan

  variables {
    aws_export_source_account_ids = ["111111111111"]
    protect_raw                   = false
  }

  assert {
    condition     = [for s in jsondecode(aws_s3_bucket_policy.this.policy).Statement : s.Sid] == ["DenyInsecureTransport", "AllowDataExportsDelivery"]
    error_message = "turning protect_raw off removes only the delete deny"
  }
}

run "versioned_encrypted_owner_enforced_and_private" {
  command = plan

  assert {
    condition     = aws_s3_bucket_versioning.this.versioning_configuration[0].status == "Enabled"
    error_message = "versioning is on, so an overwrite never loses the older version"
  }

  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.this.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
    error_message = "objects are encrypted with SSE-S3 (Data Exports does not support a KMS key here without extra grants)"
  }

  assert {
    condition     = aws_s3_bucket_ownership_controls.this.rule[0].object_ownership == "BucketOwnerEnforced"
    error_message = "ACLs are disabled"
  }

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.this.block_public_acls,
      aws_s3_bucket_public_access_block.this.block_public_policy,
      aws_s3_bucket_public_access_block.this.ignore_public_acls,
      aws_s3_bucket_public_access_block.this.restrict_public_buckets,
    ])
    error_message = "the bucket can never be public"
  }
}

run "only_normalized_versions_expire" {
  command = plan

  assert {
    condition     = [for r in aws_s3_bucket_lifecycle_configuration.this.rule : r.id] == ["abort-incomplete-uploads", "expire-old-normalized-versions"]
    error_message = "two lifecycle rules, and none for raw/"
  }

  assert {
    condition = one([for r in aws_s3_bucket_lifecycle_configuration.this.rule : r if r.id == "expire-old-normalized-versions"]).filter[0].prefix == "normalized/" && one([for r in aws_s3_bucket_lifecycle_configuration.this.rule : r if r.id == "expire-old-normalized-versions"]).noncurrent_version_expiration[0].noncurrent_days == 30
    error_message = "noncurrent versions under normalized/ expire after 30 days"
  }

  assert {
    condition = alltrue([for r in aws_s3_bucket_lifecycle_configuration.this.rule : length(r.expiration) == 0]) && length(one([for r in aws_s3_bucket_lifecycle_configuration.this.rule : r if r.id == "abort-incomplete-uploads"]).noncurrent_version_expiration) == 0
    error_message = "no rule ever expires a current object, and the bucket-wide rule only aborts uploads"
  }

  assert {
    condition     = one([for r in aws_s3_bucket_lifecycle_configuration.this.rule : r if r.id == "abort-incomplete-uploads"]).abort_incomplete_multipart_upload[0].days_after_initiation == 7
    error_message = "incomplete multipart uploads are aborted after 7 days"
  }
}

run "normalized_retention_is_an_input" {
  command = plan

  variables {
    normalized_noncurrent_days = 7
  }

  assert {
    condition     = one([for r in aws_s3_bucket_lifecycle_configuration.this.rule : r if r.id == "expire-old-normalized-versions"]).noncurrent_version_expiration[0].noncurrent_days == 7
    error_message = "normalized_noncurrent_days sets the retention of old normalized versions"
  }
}

run "tags_and_outputs" {
  command = plan

  assert {
    condition     = aws_s3_bucket.this.tags == { Name = "acme-billing", Component = "billing" }
    error_message = "the module sets Name and Component only; everything else comes from default_tags"
  }

  assert {
    condition     = output.name == "acme-billing" && output.arn == "arn:aws:s3:::acme-billing"
    error_message = "name and ARN are known at plan"
  }

  assert {
    condition     = output.raw_prefix == "raw" && output.aws_export_prefix == "raw/provider=aws/source=data-exports" && output.normalized_prefix == "normalized"
    error_message = "the prefixes are the layout contract"
  }
}

run "rejects_malformed_export_account_ids" {
  command = plan

  variables {
    aws_export_source_account_ids = ["12345"]
  }

  expect_failures = [var.aws_export_source_account_ids]
}

run "rejects_invalid_bucket_names" {
  command = plan

  variables {
    bucket_name = "Acme_Billing"
  }

  expect_failures = [var.bucket_name]
}

run "rejects_a_zero_retention" {
  command = plan

  variables {
    normalized_noncurrent_days = 0
  }

  expect_failures = [var.normalized_noncurrent_days]
}
```

Also create `versions.tf`: `required_version = ">= 1.11"` and `aws = { source = "hashicorp/aws", version = "~> 6.0" }`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd "$REPO/modules/billing-bucket" && terraform init -backend=false -input=false >/dev/null && terraform test`
Expected: FAIL, because the resources the assertions name, such as `aws_s3_bucket_policy.this`, don't exist.

- [ ] **Step 3: Implement the module**

**`variables.tf`**
- `bucket_name`: validation `can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name)) && !strcontains(var.bucket_name, "..")`.
- `aws_export_source_account_ids`: validation `alltrue([for id in var.aws_export_source_account_ids : can(regex("^[0-9]{12}$", id))])`.
- `protect_raw`: no validation.
- `normalized_noncurrent_days`: validation `>= 1 && == floor(...)`.
- Every description explains the input's effect in a sentence or two, as `container-instance` does. `protect_raw`'s description says: "switch it on once the first deliveries have been checked".

**`main.tf`** resources:
- `aws_s3_bucket.this`, with tags `{ Name, Component = "billing" }`;
- `aws_s3_bucket_ownership_controls.this`;
- `aws_s3_bucket_public_access_block.this`;
- `aws_s3_bucket_versioning.this`;
- `aws_s3_bucket_server_side_encryption_configuration.this`;
- `aws_s3_bucket_lifecycle_configuration.this`, with `depends_on` the versioning resource:
  - `abort-incomplete-uploads`: `filter {}`, abort after 7 days;
  - `expire-old-normalized-versions`: `filter { prefix = "normalized/" }`, `noncurrent_version_expiration`;
- `aws_s3_bucket_policy.this`: `policy = jsonencode(local.policy)`, with `depends_on` the public access block.

**`locals`**
- `arn = "arn:aws:s3:::${var.bucket_name}"`.
- The policy's statements are `concat([tls], var.protect_raw ? [raw_deny] : [], length(ids) > 0 ? [delivery] : [])`, exactly as the tests spell them. With one account, the delivery condition values are still lists.

**`outputs.tf`**: the five outputs, each with a description.

- [ ] **Step 4: Run the tests to see them pass**

Run: `terraform test`
Expected: `Success! 10 passed, 0 failed.`

- [ ] **Step 5: Write the example and the README**

**`examples/basic/main.tf`:**
- `provider "aws" { region = "us-east-1" }`;
- `module "billing" { source = "../.."; bucket_name = "acme-billing"; aws_export_source_account_ids = ["111111111111"] }`;
- outputs passed through.

**`examples/basic/versions.tf`:** the same as the module's.

**`README.md`**, above the markers, in plain prose:
- what the bucket is for;
- the layout, copied from spec 6.1, with this repo's generic names;
- the protections, and why there is no Object Lock;
- **order of operations:** create the bucket with the payer account in `aws_export_source_account_ids`, then create the export;
- **turning on `protect_raw`** after checking the first deliveries, and that `terraform destroy` fails while it is on, by design;
- **the policy warning from AWS:** editing the policy or changing the bucket's owner after an export exists can stop deliveries;
- a usage snippet pinned `version = "0.1.0" # x-release-please-version`.

Then run: `terraform-docs --config ../../.terraform-docs.yml .`

- [ ] **Step 6: Run the module's full check**

Run: `cd "$REPO" && scripts/check-module.sh modules/billing-bucket`
Expected: every step passes (validate, tflint, test, the docs diff, the example), with no errors.

- [ ] **Step 7: Commit**

```bash
git add modules/billing-bucket && git commit -q -m "feat(billing-bucket): add the billing bucket that never loses raw data" -m "Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `aws-billing-export`

**Files:**
- Create: `modules/aws-billing-export/{versions.tf,variables.tf,columns.tf,main.tf,outputs.tf,README.md}`
- Create: `modules/aws-billing-export/examples/basic/{main.tf,versions.tf}`
- Test: `modules/aws-billing-export/tests/aws_billing_export.tftest.hcl`

**Interfaces:**
- Consumes: the bucket's name and `aws_export_prefix` (Task 2), passed in by the caller.
- Produces (used by plan 08's `billing-export/` root):
  - **Inputs:**
    - `name` (string, required);
    - `description` (string, default `"FOCUS 1.2 with AWS columns"`);
    - `bucket_name` (string, required);
    - `bucket_owner_account_id` (string, default `null`);
    - `bucket_region` (string, default `"us-east-1"`);
    - `prefix` (string, default `"raw/provider=aws/source=data-exports"`);
    - `time_granularity` (string, default `"DAILY"`).
  - **Outputs:**
    - `arn`;
    - `name`;
    - `delivery_prefix` (`"<prefix>/<name>"`, under which AWS writes `data/BILLING_PERIOD=YYYY-MM/<timestamp>-<execution-id>/` and `metadata/BILLING_PERIOD=YYYY-MM/Manifest.json`).

- [ ] **Step 1: Write the failing tests**

Create `tests/aws_billing_export.tftest.hcl`:

```hcl
mock_provider "aws" {}

variables {
  name        = "acme-focus-daily"
  bucket_name = "acme-billing"
}

run "defaults_are_focus_1_2_daily_parquet_in_new_files" {
  command = plan

  assert {
    condition     = startswith(aws_bcmdataexports_export.this.export[0].data_query[0].query_statement, "SELECT AvailabilityZone, BilledCost, BillingAccountId, ") && endswith(aws_bcmdataexports_export.this.export[0].data_query[0].query_statement, ", SubAccountType, Tags, x_Discounts, x_Operation, x_ServiceCode FROM FOCUS_1_2_AWS")
    error_message = "the query selects the FOCUS 1.2 columns, listed explicitly, from FOCUS_1_2_AWS"
  }

  assert {
    condition     = length(split(", ", trimsuffix(trimprefix(aws_bcmdataexports_export.this.export[0].data_query[0].query_statement, "SELECT "), " FROM FOCUS_1_2_AWS"))) == 60
    error_message = "all 60 columns of FOCUS_1_2_AWS"
  }

  assert {
    condition     = aws_bcmdataexports_export.this.export[0].data_query[0].table_configurations == { FOCUS_1_2_AWS = { TIME_GRANULARITY = "DAILY" } }
    error_message = "daily granularity"
  }

  assert {
    condition = aws_bcmdataexports_export.this.export[0].destination_configurations[0].s3_destination[0].s3_output_configurations[0] == {
      compression = "PARQUET"
      format      = "PARQUET"
      output_type = "CUSTOM"
      overwrite   = "CREATE_NEW_REPORT"
    }
    error_message = "Parquet, and every refresh in new files, so a delivery is never overwritten"
  }

  assert {
    condition     = aws_bcmdataexports_export.this.export[0].refresh_cadence[0].frequency == "SYNCHRONOUS"
    error_message = "refreshed whenever the bill changes"
  }

  assert {
    condition     = aws_bcmdataexports_export.this.export[0].destination_configurations[0].s3_destination[0].s3_bucket == "acme-billing" && aws_bcmdataexports_export.this.export[0].destination_configurations[0].s3_destination[0].s3_prefix == "raw/provider=aws/source=data-exports" && aws_bcmdataexports_export.this.export[0].destination_configurations[0].s3_destination[0].s3_region == "us-east-1"
    error_message = "delivered under the bucket's AWS prefix in us-east-1"
  }

  assert {
    condition     = aws_bcmdataexports_export.this.tags == { Name = "acme-focus-daily", Component = "billing" }
    error_message = "the module sets Name and Component only"
  }

  assert {
    condition     = output.delivery_prefix == "raw/provider=aws/source=data-exports/acme-focus-daily"
    error_message = "AWS writes data/ and metadata/ under <prefix>/<name>"
  }
}

run "same_account_leaves_the_bucket_owner_unset" {
  command = plan

  assert {
    condition     = aws_bcmdataexports_export.this.export[0].destination_configurations[0].s3_destination[0].s3_bucket_owner == null
    error_message = "no bucket owner for a bucket in the same account"
  }
}

run "cross_account_names_the_bucket_owner" {
  command = plan

  variables {
    bucket_owner_account_id = "222222222222"
  }

  assert {
    condition     = aws_bcmdataexports_export.this.export[0].destination_configurations[0].s3_destination[0].s3_bucket_owner == "222222222222"
    error_message = "a bucket in another account is named with its owner"
  }
}

run "granularity_is_an_input" {
  command = plan

  variables {
    time_granularity = "HOURLY"
  }

  assert {
    condition     = aws_bcmdataexports_export.this.export[0].data_query[0].table_configurations == { FOCUS_1_2_AWS = { TIME_GRANULARITY = "HOURLY" } }
    error_message = "time_granularity sets TIME_GRANULARITY"
  }
}

run "rejects_prefixes_with_stray_slashes" {
  command = plan

  variables {
    prefix = "/raw//aws/"
  }

  expect_failures = [var.prefix]
}

run "rejects_a_malformed_bucket_owner" {
  command = plan

  variables {
    bucket_owner_account_id = "2222"
  }

  expect_failures = [var.bucket_owner_account_id]
}

run "rejects_an_unknown_granularity" {
  command = plan

  variables {
    time_granularity = "WEEKLY"
  }

  expect_failures = [var.time_granularity]
}

run "rejects_an_invalid_export_name" {
  command = plan

  variables {
    name = "acme focus/daily"
  }

  expect_failures = [var.name]
}
```

Also create `versions.tf`: `required_version = ">= 1.11"` and `aws = { source = "hashicorp/aws", version = ">= 6.73, < 7.0" }`. 6.73.0 is the version in which `s3_bucket_owner` was verified.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd "$REPO/modules/aws-billing-export" && terraform init -backend=false -input=false >/dev/null && terraform test`
Expected: FAIL, because `aws_bcmdataexports_export.this` doesn't exist.

- [ ] **Step 3: Confirm the column list is current**

Fetch https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-focus-1-2-aws-columns.html and compare it with the list below. If it differs, use the page's list. Update the 60 in the test, and record the change in spec 12.2.

As read on 2026-11-21:

```text
AvailabilityZone BilledCost BillingAccountId BillingAccountName BillingAccountType BillingCurrency
BillingPeriodEnd BillingPeriodStart CapacityReservationId CapacityReservationStatus ChargeCategory
ChargeClass ChargeDescription ChargeFrequency ChargePeriodEnd ChargePeriodStart
CommitmentDiscountCategory CommitmentDiscountId CommitmentDiscountName CommitmentDiscountQuantity
CommitmentDiscountStatus CommitmentDiscountType CommitmentDiscountUnit ConsumedQuantity ConsumedUnit
ContractedCost ContractedUnitPrice EffectiveCost InvoiceId InvoiceIssuerName ListCost ListUnitPrice
PricingCategory PricingCurrency PricingCurrencyContractedUnitPrice PricingCurrencyEffectiveCost
PricingCurrencyListUnitPrice PricingQuantity PricingUnit ProviderName PublisherName RegionId
RegionName ResourceId ResourceName ResourceType ServiceCategory ServiceName ServiceSubcategory SkuId
SkuMeter SkuPriceId SkuPriceDetails SubAccountId SubAccountName SubAccountType Tags x_Discounts
x_Operation x_ServiceCode
```

- [ ] **Step 4: Implement the module**

- **`columns.tf`:** `locals { focus_1_2_aws_columns = [ ...the 60 names, in that order... ] }`, with a comment giving the source URL and the date read.
- **`variables.tf` validations:**
  - `name`: `^[0-9A-Za-z!_.*'()-]{1,128}$`.
  - `bucket_owner_account_id`: `var.bucket_owner_account_id == null || can(regex("^[0-9]{12}$", ...))`.
  - `prefix`: `length(var.prefix) > 0 && !startswith(var.prefix, "/") && !endswith(var.prefix, "/") && !strcontains(var.prefix, "//")`.
  - `time_granularity`: one of `HOURLY`, `DAILY`, `MONTHLY`.
- **`main.tf`:** one `aws_bcmdataexports_export.this`, with tags `{ Name = var.name, Component = "billing" }` and an `export` block.
  - `query_statement = "SELECT ${join(", ", local.focus_1_2_aws_columns)} FROM FOCUS_1_2_AWS"`.
  - The `table_configurations`, `s3_destination` (bucket, `s3_bucket_owner = var.bucket_owner_account_id`, prefix, region), output configuration and refresh cadence take the values the tests assert.
  - A header comment says the export must be created in the account whose bill it exports: the payer for organization-wide data.
- **`outputs.tf`:**
  - `arn = aws_bcmdataexports_export.this.arn`;
  - `name`;
  - `delivery_prefix = "${var.prefix}/${var.name}"`.

- [ ] **Step 5: Run the tests to see them pass**

Run: `terraform test`
Expected: `Success! 8 passed, 0 failed.`

- [ ] **Step 6: Write the example and the README**

**`examples/basic/main.tf`:** the cross-account case.
- `provider "aws" { region = "us-east-1" }`, standing for the payer;
- `module "export"` with `name = "acme-focus-daily"`, `bucket_name = "acme-billing"` and `bucket_owner_account_id = "222222222222"`.

**`README.md`:**
- what the export contains: FOCUS 1.2 with AWS columns, daily, every account if created in the payer;
- where the files land and how the manifest tells you which execution is newest;
- that AWS rewrites the current month and may restate the previous one for two weeks;
- the order of operations: the bucket first, then the export;
- backfill: a free AWS Support billing case after the first delivery, as in spec 12.9;
- a usage snippet pinned `# x-release-please-version`.

Then run terraform-docs as in Task 2.

- [ ] **Step 7: Run the module's full check**

Run: `cd "$REPO" && scripts/check-module.sh modules/aws-billing-export`
Expected: every step passes.

- [ ] **Step 8: Commit**

```bash
git add modules/aws-billing-export && git commit -q -m "feat(aws-billing-export): add the org-wide FOCUS 1.2 daily export" -m "Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The organization example and the whole-repo check

**Files:**
- Create: `examples/organization-billing/{main.tf,versions.tf,README.md}`
- Modify: `README.md` (the root module): link both submodules and the example.

**Interfaces:**
- Consumes: both submodules, through `source = "../../modules/<name>"`.
- Produces: the registry's root example.

- [ ] **Step 1: Write the example**

**`main.tf`:**
- Two providers:
  - `provider "aws" { region = "us-east-1" }` for the bucket account;
  - `provider "aws" { alias = "payer"; region = "us-east-1" }`.
- `module "bucket"`: `billing-bucket` with `bucket_name = "acme-billing"` and `aws_export_source_account_ids = ["111111111111"]`.
- `module "export"`: `aws-billing-export`, with `providers = { aws = aws.payer }`, `bucket_name = module.bucket.name`, `bucket_owner_account_id = "222222222222"` and `prefix = module.bucket.aws_export_prefix`.

**`README.md`:** explains that in real use the two halves are usually applied from separate roots, one per account, bucket first. The example only shows the wiring.

- [ ] **Step 2: Run the whole suite**

Run: `cd "$REPO" && scripts/check.sh`
Expected: `All checks passed.`, covering three modules (`.`, `modules/aws-billing-export`, `modules/billing-bucket`), their examples and the commitlint tests.

- [ ] **Step 3: Commit**

```bash
git add examples README.md && git commit -q -m "docs: add the organization billing example" -m "Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Publish the repository and release 0.1.0

Every step that touches GitHub needs the owner's explicit permission, asked for at that step. These steps are not code; they have checks instead of tests.

- [ ] **Step 1 (owner permission): Create the repository**

Run: `gh repo create Jaws-Platform/terraform-aws-jaws-monitoring --public --add-readme --description "Terraform modules for a self-hosted monitoring and multi-source cost platform on AWS"`
Expected: the repository exists, with one commit, `Initial commit`, on `main`.

- [ ] **Step 2: Put the work on a branch on top of `main`**

```bash
cd "$REPO" && git remote add origin https://github.com/Jaws-Platform/terraform-aws-jaws-monitoring.git && git fetch -q origin
git switch -q -c feat/billing-storage && git rebase -q -X theirs --onto origin/main --root   # our README wins over GitHub's
git push -q -u origin feat/billing-storage
```

Expected: `git log --oneline origin/main..HEAD` shows the four commits from Tasks 1–4, and nothing else.

- [ ] **Step 3: Open the PR**

Run: `gh pr create --template feat.md --title "feat: add the billing bucket and the AWS billing export"`, then fill every section of the template.
Expected: CI passes, including `commitlint`, `pr-title`, `fmt` and `terraform`.

- [ ] **Step 4 (owner permission): Merge, then apply the settings and secrets**

Run each of these in order:
1. `gh pr merge --squash`.
2. `scripts/apply-repo-settings.sh Jaws-Platform/terraform-aws-jaws-monitoring`.
3. `gh secret set RELEASE_BOT_CLIENT_ID --repo Jaws-Platform/terraform-aws-jaws-monitoring --body "$(cat /Users/jimmywallace/Projects/Jaws-Platform/jaws-platform-release-bot/client-id)"`.
4. `gh secret set RELEASE_BOT_PRIVATE_KEY --repo Jaws-Platform/terraform-aws-jaws-monitoring < /Users/jimmywallace/Projects/Jaws-Platform/jaws-platform-release-bot/jaws-platform-release-bot.private-key.pem`. Never print the key.

Expected: the `main` ruleset exists (`gh api repos/Jaws-Platform/terraform-aws-jaws-monitoring/rulesets --jq '.[].name'` prints `main`). If Release Please ran before the secrets were set, re-run the `release-please` workflow.

- [ ] **Step 5 (owner permission): Release 0.1.0**

Run: `gh pr list --repo Jaws-Platform/terraform-aws-jaws-monitoring --author 'app/jaws-platform-release-bot'`, then merge the release PR for `0.1.0`.
Expected: the tag `v0.1.0` exists, along with a GitHub release.

- [ ] **Step 6 (owner): Publish on the Terraform Registry**

The owner publishes `Jaws-Platform/terraform-aws-jaws-monitoring` in HCP Terraform under the `Jaws-Platform` namespace. Then check it:

Run: `curl -s https://registry.terraform.io/v1/modules/Jaws-Platform/jaws-monitoring/aws | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])'`
Expected: `0.1.0`.

- [ ] **Step 7: Record the outcome**

In the Jaws repo, on branch `docs/monitoring-node-design`:
- tick this plan's checkboxes;
- mark plan 01 `done` in [00-roadmap](2026-11-21-monitoring-00-roadmap.md).

Commit: `docs(monitoring): record the billing storage release`.
