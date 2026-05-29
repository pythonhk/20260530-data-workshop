# Tournament Admin OpenTofu

This branch keeps tournament administration separate from the participant-facing
`main` branch.

The module generates local TLS material, writes public certificates into the
repository tree, sets GitHub Actions secrets and variables, enables Pages, and
configures branch protection. Private keys and state stay local and ignored.

From this directory:

```bash
mise install
cp terraform.tfvars.example terraform.tfvars
export GITHUB_TOKEN="$(gh auth token)"
mise exec -- tofu init
mise exec -- tofu apply
```

After apply, commit the generated public files from the repository root:

```text
.github/tournament/public_keys/
.github/tournament/team_allowlist.json
```

Give each team only its own folder from
`admin/opentofu/generated/teams/<team-id>/`.
