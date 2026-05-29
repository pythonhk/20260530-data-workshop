variable "github_owner" {
  description = "GitHub owner or organization that owns the tournament repository."
  type        = string
}

variable "repository_name" {
  description = "Tournament repository name, without owner."
  type        = string
}

variable "main_branch" {
  description = "Participant starter branch."
  type        = string
  default     = "main"
}

variable "leaderboard_branch" {
  description = "Branch that stores the static leaderboard site and leaderboard.json."
  type        = string
  default     = "leaderboard"
}

variable "tournament_name" {
  description = "Human-readable tournament name embedded into generated certificates."
  type        = string
  default     = "HKPUG Data Cleaning Tournament"
}

variable "team_count" {
  description = "Number of pre-provisioned team identities."
  type        = number
  default     = 20
}

variable "team_prefix" {
  description = "Prefix used for generated team ids."
  type        = string
  default     = "team"
}

variable "certificate_validity_hours" {
  description = "Validity window for generated root, service, and team certificates."
  type        = number
  default     = 17520
}

variable "max_daily_scored_attempts" {
  description = "Maximum scored attempts per team per tournament timezone day."
  type        = number
  default     = 3
}

variable "tournament_timezone" {
  description = "Timezone used for daily attempt limits and dashboard formatting."
  type        = string
  default     = "Asia/Hong_Kong"
}

variable "score_metric" {
  description = "Primary score metric identifier."
  type        = string
  default     = "roc_auc"
}

variable "enable_pages" {
  description = "Enable GitHub Pages using workflow-based deployment."
  type        = bool
  default     = true
}

variable "enable_branch_protection" {
  description = "Configure branch protection for main and leaderboard."
  type        = bool
  default     = true
}
