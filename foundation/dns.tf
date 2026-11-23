# The platform's hosted zone (config/sites.yaml, dns.zone). The zone itself is
# owned here; records are owned by the project repos. The only records this stack
# manages are zone-level ones: CAA and the TXT records that belong to the zone
# owner (domain verification, dns.txt_records). The module hard-codes
# prevent_destroy.

locals {
  zone_name = local.tool_config.dns.zone

  zone_comment = "${local.context.name_root}: zone owned by ${local.context.repository_tag}; records owned by project repos"

  # Certificate authorities allowed to issue for the zone and its subdomains.
  # ACM needs the four Amazon entries: every site is served by CloudFront with
  # an ACM certificate. The monitoring node's Caddy gets its certificate for
  # monitoring.domain (config/monitoring.yaml) from Let's Encrypt, which honours
  # this apex record (RFC 8659 climbs to it), so letsencrypt.org is allowed
  # while that domain is configured. No other issuer is allowed.
  caa_issuers = concat(
    [
      "amazon.com",
      "amazontrust.com",
      "awstrust.com",
      "amazonaws.com",
    ],
    try(local.monitoring.domain, null) == null ? [] : ["letsencrypt.org"],
  )

  # TXT records that belong to the zone owner, not to a project (config/sites.yaml,
  # dns.txt_records; the reason each is kept is written there).
  txt_records = try(local.tool_config.dns.txt_records, {})
}

module "zone" {
  source  = "Jaws-Platform/jaws-static-site/aws//modules/hosted-zone"
  version = "0.1.2"

  name        = local.zone_name
  comment     = local.zone_comment
  caa_issuers = local.caa_issuers
  txt_records = local.txt_records
  name_tag    = "${local.name_prefix}-dns-zone"
}
