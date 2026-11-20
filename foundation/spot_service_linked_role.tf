# The account's EC2 Spot service-linked role, AWSServiceRoleForEC2Spot. EC2
# needs it before the first Spot launch in an account and creates it on that
# launch only when the caller may call iam:CreateServiceLinkedRole. A task
# launch role may not, so in an account without the role every spot task
# fails with AuthFailure.ServiceLinkedRoleCreationNotPermitted. That is how
# production's first Datagen run failed on 2026-11-19
# (Braveheart-Chess/braveheart-selfplay run 44546406893).
#
# One per account, so it is the foundation's, never a project stack's, and it
# exists wherever a project runs tasks (local.hosts_task_runners, bots.tf).
# The module never destroys it (prevent_destroy): an account that stops
# hosting task runners fails its plan here until the owner decides, by
# removing it from state or keeping it.
module "spot_service_linked_role" {
  count   = local.hosts_task_runners ? 1 : 0
  source  = "jaws-platform/jaws-foundation/aws//modules/service-linked-role"
  version = "0.1.0"

  aws_service_name = "spot.amazonaws.com"
  # EC2's own description for the role, so the management account's role is
  # adopted with no change to it, and production's matches.
  description = "Default EC2 Spot Service Linked Role"
}

# The management account has had the role since 2025-10-10, created by hand
# before this repository existed; the foundation adopts it (owner's decision,
# 2026-11-19). IAM refuses a second one, so it is imported, never created.
# Production had none and gets a new one. Once imported, this block is a no-op.
import {
  for_each = var.account == "management" && local.hosts_task_runners ? toset(["spot"]) : toset([])

  to = module.spot_service_linked_role[0].aws_iam_service_linked_role.this
  id = "arn:aws:iam::${local.account_id}:role/aws-service-role/spot.amazonaws.com/AWSServiceRoleForEC2Spot"
}
