terraform {
  required_version = ">= 1.11, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    # The monitoring module packages its Lambda functions (the normalizer, the watchdog).
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }
}
