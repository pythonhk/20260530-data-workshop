# Live Admin State

Target repository: `pythonhk/20260530-data-workshop`

OpenTofu manages:

- scorer private-key Actions secrets
- daily-attempt and leaderboard Actions variables
- root CA, scorer certificates, and team certificates
- local team private-key bundles
- GitHub Pages workflow mode
- branch protection for `main` and `leaderboard`

Private files under `admin/opentofu/generated/` and local OpenTofu state are
ignored and must not be committed.
