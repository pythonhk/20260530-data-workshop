output "repository" {
  value = "${var.github_owner}/${var.repository_name}"
}

output "team_ids" {
  value = local.team_ids
}

output "team_bundle_directory" {
  value = "${path.module}/generated/teams"
}

output "scorer_key_directory" {
  value = "${path.module}/generated/scorer"
}

output "public_config_files" {
  value = concat(
    [
      local_file.root_ca_cert_repo.filename,
      local_file.team_allowlist_repo.filename,
    ],
    [for cert in local_file.scorer_cert_repo : cert.filename],
    [for cert in local_file.team_cert_repo : cert.filename],
  )
}

output "pages_url" {
  value = var.enable_pages ? github_repository_pages.leaderboard[0].html_url : null
}
