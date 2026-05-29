data "github_repository" "target" {
  full_name = "${var.github_owner}/${var.repository_name}"
}

locals {
  repository_root = abspath("${path.module}/../..")

  team_ids = [
    for index in range(var.team_count) :
    format("%s-%02d", var.team_prefix, index + 1)
  ]

  scorer_keys = {
    team_code      = "TEAM_CODE_PRIVATE_KEY"
    cleaned_output = "CLEANED_OUTPUT_PRIVATE_KEY"
    hidden_labels  = "HIDDEN_LABELS_PRIVATE_KEY"
  }

  scorer_public_cert_paths = {
    team_code      = "${local.repository_root}/.github/tournament/public_keys/team_code_cert.pem"
    cleaned_output = "${local.repository_root}/.github/tournament/public_keys/cleaned_output_cert.pem"
    hidden_labels  = "${local.repository_root}/.github/tournament/public_keys/hidden_labels_cert.pem"
  }

  team_allowlist = {
    schema_version = 1
    tournament     = var.tournament_name
    ca_cert_path   = ".github/tournament/public_keys/tournament_ca_cert.pem"
    teams = {
      for team_id, cert in tls_locally_signed_cert.team :
      team_id => {
        cert_pem    = cert.cert_pem
        cert_sha256 = sha256(cert.cert_pem)
      }
    }
  }
}

resource "tls_private_key" "root_ca" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "tls_self_signed_cert" "root_ca" {
  private_key_pem = tls_private_key.root_ca.private_key_pem

  is_ca_certificate     = true
  validity_period_hours = var.certificate_validity_hours

  allowed_uses = [
    "cert_signing",
    "crl_signing",
    "digital_signature",
  ]

  subject {
    common_name  = "${var.tournament_name} Root CA"
    organization = var.tournament_name
  }
}

resource "tls_private_key" "scorer" {
  for_each = local.scorer_keys

  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "tls_cert_request" "scorer" {
  for_each = local.scorer_keys

  private_key_pem = tls_private_key.scorer[each.key].private_key_pem

  subject {
    common_name  = "${var.tournament_name} ${replace(each.key, "_", " ")}"
    organization = var.tournament_name
  }
}

resource "tls_locally_signed_cert" "scorer" {
  for_each = local.scorer_keys

  cert_request_pem   = tls_cert_request.scorer[each.key].cert_request_pem
  ca_private_key_pem = tls_private_key.root_ca.private_key_pem
  ca_cert_pem        = tls_self_signed_cert.root_ca.cert_pem

  validity_period_hours = var.certificate_validity_hours

  allowed_uses = [
    "data_encipherment",
    "digital_signature",
    "key_encipherment",
  ]
}

resource "tls_private_key" "team" {
  for_each = toset(local.team_ids)

  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "tls_cert_request" "team" {
  for_each = toset(local.team_ids)

  private_key_pem = tls_private_key.team[each.key].private_key_pem

  subject {
    common_name  = each.key
    organization = var.tournament_name
  }
}

resource "tls_locally_signed_cert" "team" {
  for_each = toset(local.team_ids)

  cert_request_pem   = tls_cert_request.team[each.key].cert_request_pem
  ca_private_key_pem = tls_private_key.root_ca.private_key_pem
  ca_cert_pem        = tls_self_signed_cert.root_ca.cert_pem

  validity_period_hours = var.certificate_validity_hours

  allowed_uses = [
    "client_auth",
    "code_signing",
    "digital_signature",
  ]
}

resource "local_sensitive_file" "root_ca_private_key" {
  filename        = "${path.module}/generated/root_ca/private_key.pem"
  content         = tls_private_key.root_ca.private_key_pem
  file_permission = "0600"
}

resource "local_file" "root_ca_cert" {
  filename        = "${path.module}/generated/root_ca/cert.pem"
  content         = tls_self_signed_cert.root_ca.cert_pem
  file_permission = "0644"
}

resource "local_file" "root_ca_cert_repo" {
  filename        = "${local.repository_root}/.github/tournament/public_keys/tournament_ca_cert.pem"
  content         = tls_self_signed_cert.root_ca.cert_pem
  file_permission = "0644"
}

resource "local_sensitive_file" "scorer_private_key" {
  for_each = local.scorer_keys

  filename        = "${path.module}/generated/scorer/${each.key}_private_key.pem"
  content         = tls_private_key.scorer[each.key].private_key_pem
  file_permission = "0600"
}

resource "local_file" "scorer_cert" {
  for_each = local.scorer_keys

  filename        = "${path.module}/generated/scorer/${each.key}_cert.pem"
  content         = tls_locally_signed_cert.scorer[each.key].cert_pem
  file_permission = "0644"
}

resource "local_file" "scorer_cert_repo" {
  for_each = local.scorer_public_cert_paths

  filename        = each.value
  content         = tls_locally_signed_cert.scorer[each.key].cert_pem
  file_permission = "0644"
}

resource "local_file" "scorer_public_key" {
  for_each = local.scorer_keys

  filename        = "${path.module}/generated/scorer/${each.key}_public_key.pem"
  content         = tls_private_key.scorer[each.key].public_key_pem
  file_permission = "0644"
}

resource "local_sensitive_file" "team_private_key" {
  for_each = toset(local.team_ids)

  filename        = "${path.module}/generated/teams/${each.key}/team_private_key.pem"
  content         = tls_private_key.team[each.key].private_key_pem
  file_permission = "0600"
}

resource "local_file" "team_cert" {
  for_each = toset(local.team_ids)

  filename        = "${path.module}/generated/teams/${each.key}/team_cert.pem"
  content         = tls_locally_signed_cert.team[each.key].cert_pem
  file_permission = "0644"
}

resource "local_file" "team_public_key" {
  for_each = toset(local.team_ids)

  filename        = "${path.module}/generated/teams/${each.key}/team_public_key.pem"
  content         = tls_private_key.team[each.key].public_key_pem
  file_permission = "0644"
}

resource "local_file" "team_readme" {
  for_each = toset(local.team_ids)

  filename        = "${path.module}/generated/teams/${each.key}/README.md"
  file_permission = "0644"
  content         = <<-EOT
    # ${each.key}

    Give this folder to ${each.key} through a private channel.

    Files:
    - team_private_key.pem: keep private; never commit.
    - team_public_key.pem: safe to share; included for inspection/debugging.
    - team_cert.pem: public team certificate; the repository stores it in the allowlist.

    Sign a submission manifest before opening a PR:

    submission/encrypt_submission.sh /path/to/team_private_key.pem

    The tournament repository verifies submission/manifest.sig with this team's
    public certificate and the generated root CA.
  EOT
}

resource "local_file" "team_allowlist" {
  filename        = "${path.module}/generated/team_allowlist.json"
  content         = jsonencode(local.team_allowlist)
  file_permission = "0644"
}

resource "local_file" "team_allowlist_repo" {
  filename        = "${local.repository_root}/.github/tournament/team_allowlist.json"
  content         = jsonencode(local.team_allowlist)
  file_permission = "0644"
}

resource "github_actions_secret" "scorer_private_key" {
  for_each = local.scorer_keys

  repository  = var.repository_name
  secret_name = each.value
  value       = tls_private_key.scorer[each.key].private_key_pem
}

resource "github_actions_variable" "leaderboard_branch" {
  repository    = var.repository_name
  variable_name = "LEADERBOARD_BRANCH"
  value         = var.leaderboard_branch
}

resource "github_actions_variable" "max_daily_scored_attempts" {
  repository    = var.repository_name
  variable_name = "MAX_DAILY_SCORED_ATTEMPTS"
  value         = tostring(var.max_daily_scored_attempts)
}

resource "github_actions_variable" "score_metric" {
  repository    = var.repository_name
  variable_name = "SCORE_METRIC"
  value         = var.score_metric
}

resource "github_actions_variable" "tournament_timezone" {
  repository    = var.repository_name
  variable_name = "TOURNAMENT_TIMEZONE"
  value         = var.tournament_timezone
}

resource "github_repository_pages" "leaderboard" {
  count = var.enable_pages ? 1 : 0

  repository = var.repository_name
  build_type = "workflow"
}

resource "github_branch_protection" "main" {
  count = var.enable_branch_protection ? 1 : 0

  repository_id = data.github_repository.target.node_id
  pattern       = var.main_branch

  enforce_admins                  = false
  allows_deletions                = false
  allows_force_pushes             = false
  require_conversation_resolution = false
  required_linear_history         = true

  required_status_checks {
    strict   = true
    contexts = ["validate", "run-cleaner"]
  }

  required_pull_request_reviews {
    dismiss_stale_reviews           = true
    require_code_owner_reviews      = false
    require_last_push_approval      = false
    required_approving_review_count = 0
  }
}

resource "github_branch_protection" "leaderboard" {
  count = var.enable_branch_protection ? 1 : 0

  repository_id = data.github_repository.target.node_id
  pattern       = var.leaderboard_branch

  enforce_admins                  = false
  allows_deletions                = false
  allows_force_pushes             = false
  require_conversation_resolution = false
  required_linear_history         = true
}
