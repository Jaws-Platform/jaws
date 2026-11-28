# Onboarding log

**What it is.** Every manual step a new platform owner takes today to stand Jaws up, collected while the owner builds their own hub (the hub split's plans 04–07). For each step, it records:
- who does it;
- where it happens;
- what it needs;
- where it tripped someone up.

**What it's for.** It is the raw material for `jaws bootstrap`, the later step that sets up a brand-new customer from nothing ([the hub split's spec](specs/2026-11-22-hub-split-design.md), "Later steps"). Bootstrap's design starts from this log, and its "Get started" guide is tested against it.

**Adding to it.** When a step is found, or trips someone up, add a row or a dated entry: what happened, what it cost, and an idea for removing it. Keep owner values out: no account IDs, emails or GitHub IDs.

## The steps today

These are the steps a customer takes for a hub, in order. Steps that only the vendor takes, such as publishing Jaws's own image, are left out.

| # | Step | Who | Where | Needs |
|---|---|---|---|---|
| 1 | Create a GitHub organization for the platform | owner | GitHub UI | a GitHub account |
| 2 | Create the organization's release App, `<org>-releases`; install it on every repository; store its key as an organization secret | owner | GitHub UI, `gh` | org admin |
| 3 | Create the hub repository: the scaffold, the conventions PR and the Release Please PR (plan 06, Task 1) | agent or owner | `gh`, git | org admin |
| 4 | Create three more Apps: Comments, Upgrades and Deployments. About 12 clicks each, plus a logo and a key (plan 06, H2) | owner | GitHub UI | org admin |
| 5 | Apply the hub's settings: rulesets, the `prod` environment and the Actions defaults (H5) | owner | `scripts/apply-repo-settings.sh` | org admin; step 4's Deployments App |
| 6 | Store the Apps' keys: two repository secrets, and one `prod` environment secret (H3) | owner | `gh secret set` | the `.pem` files; step 5's `prod` |
| 7 | Add the hub's brand and identity: one commit editing three configuration files, with the organization's and repository's IDs (H4) | owner | editor, `gh api` | the IDs |
| 8 | Make the platform's AWS roles trust the hub: the enabling release (plan 07, O1–O2) | owner | a `jaws` release | AWS admin, release hours |
| 9 | Install the Comments App on each project repository, and store its key there (H6, O7) | owner | GitHub UI, `gh` | the key |
| 10 | Switch each project to the hub: its callers, its required checks, and removing its old variables (O8) | owner, with agent PRs | each project repository | admin of each |

The owner's own hub skips the AWS foundation, which `jaws` already applies. A brand-new customer also needs it: the accounts, the management-account roots (`owner-access/`, `billing-export/`), the state bucket and the first foundation apply. That is bootstrap's other half.

## Where it tripped us up

- **2026-11-27: a variable stored Terraform's warning.**
  - Plan 04's hand-off sets a repository variable from `$(terraform output -raw …)`. Run outside the root, or before the apply, that stores Terraform's "No outputs found" warning as the variable's value.
  - The release's check caught it before anything was published.
  - Idea: set values only through a command that checks their format first. Never `gh variable set --body "$(…)"` unchecked.
- **2026-11-27: four Apps, and it isn't clear why.**
  - Each new App takes about 12 UI steps, and its key is then copied into a secret by hand.
  - It isn't obvious why there are four (Releases, Comments, Upgrades, Deployments). Each holds one job, so a leaked key can do only that job.
  - Ideas:
    - create each App from a GitHub App manifest: a pre-filled page, one click, with the permissions already set;
    - send the key straight from the manifest's conversion into its secret, with no `.pem` on disk;
    - give each App a one-paragraph description of its job (done for the owner's Apps).
- **2026-11-27: the order matters, and it's easy to miss.**
  - The settings script needs the Deployments App to exist (it is `live`'s bypass actor). The mover's key needs the `prod` environment that the script creates.
  - So the order is H2, then H5, then H3, and only an org admin can run it.
  - Idea: one bootstrap command that runs the three in order and verifies each.
- **2026-11-27: commit identity.**
  - The owner's global git email was a private address, so a fresh clone would commit with it.
  - Separately, GitHub's web merges use the account's email unless "Keep my email addresses private" is on.
  - Idea: bootstrap checks the git identity and the account setting, and says what each choice means.
- **2026-11-27: a registry alias needs an AWS review.**
  - Requesting the ECR Public alias meant waiting days for AWS to review it. It was dropped for the registry's default alias (#334).
  - This is a vendor-side step, but the lesson carries over: avoid any step that waits on a third party's review.

## Ideas for `jaws bootstrap`

These are not a design yet.
- **A guided command** with a dry run that lists every step before it runs, and a check after each step.
- **A template repository** for the hub, in place of the scaffold, the conventions PR and the Release Please PR.
- **App manifests** for the Apps, with each key piped straight into its secret.
- **The configuration's identity filled in** from the GitHub API, so the person never handles the IDs.
- **A final verification**, like plan 06's Task 1 Step 8, that reports what is set up and what is missing.
- **A "Get started" guide,** tested end to end by someone following it on an empty organization.
