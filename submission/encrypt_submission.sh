#!/usr/bin/env bash
set -euo pipefail

cert_path=".github/tournament/public_keys/team_code_cert.pem"
team_private_key_path="${1:-${TEAM_PRIVATE_KEY_PATH:-}}"

if [[ ! -f "$cert_path" ]]; then
  echo "Public certificate not found: $cert_path" >&2
  exit 1
fi

openssl cms -encrypt \
  -aes-256-cbc \
  -binary \
  -outform DER \
  -in submission/clean.py \
  -out submission/clean.py.cms \
  "$cert_path"

echo "Encrypted submission/clean.py -> submission/clean.py.cms"

if [[ -n "$team_private_key_path" ]]; then
  if [[ ! -f "$team_private_key_path" ]]; then
    echo "Team private key not found: $team_private_key_path" >&2
    exit 1
  fi
  if [[ ! -f submission/manifest.json ]]; then
    echo "submission/manifest.json not found" >&2
    exit 1
  fi

  openssl dgst \
    -sha256 \
    -sign "$team_private_key_path" \
    -out submission/manifest.sig \
    submission/manifest.json

  echo "Signed submission/manifest.json -> submission/manifest.sig"
fi
