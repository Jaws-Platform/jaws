terraform {
  required_version = ">= 1.11, < 2.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # aws-billing-export's cross-account delivery (s3_bucket_owner) needs 6.73.
      version = ">= 6.73, < 7.0"
    }
  }
}
