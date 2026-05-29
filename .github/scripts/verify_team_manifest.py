from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


TEAM_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{2,64}$")


@dataclass(frozen=True)
class VerificationConfig:
    manifest: Path
    signature: Path
    allowlist: Path
    ca_cert: Path
    repository_root: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--signature", required=True, type=Path)
    parser.add_argument("--allowlist", required=True, type=Path)
    parser.add_argument("--ca-cert", required=True, type=Path)
    parser.add_argument("--repository-root", default=Path("."), type=Path)
    return parser.parse_args()


def read_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def validate_team_id(manifest: dict) -> str:
    team_id = manifest.get("team_id")
    if not isinstance(team_id, str) or not TEAM_ID_RE.fullmatch(team_id):
        raise ValueError("manifest.json must contain a valid team_id")
    if manifest.get("code_path") != "submission/clean.py.cms":
        raise ValueError("manifest.json code_path must be submission/clean.py.cms")
    return team_id


def resolve_repo_path(repository_root: Path, value: str) -> Path:
    root = repository_root.resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path escapes repository root: {value}")
    return path


def resolve_team_cert(
    team_id: str,
    team_entry: dict,
    repository_root: Path,
    temp_dir: Path,
) -> Path:
    cert_pem = team_entry.get("cert_pem")
    cert_path = team_entry.get("cert_path")

    if isinstance(cert_pem, str):
        cert = temp_dir / f"{team_id}.cert.pem"
        cert.write_text(cert_pem, encoding="utf-8")
        return cert

    if isinstance(cert_path, str):
        cert = resolve_repo_path(repository_root, cert_path)
        if not cert.is_file():
            raise FileNotFoundError(cert)
        return cert

    raise ValueError(f"{team_id} allowlist entry must include cert_pem")


def run_openssl(args: list[str]) -> None:
    subprocess.run(["openssl", *args], check=True)


def verify_submission(config: VerificationConfig) -> str:
    if not config.allowlist.is_file():
        print(f"No team allowlist found at {config.allowlist}; skipping verification.")
        return ""

    if not config.signature.is_file():
        raise FileNotFoundError(config.signature)
    if not config.ca_cert.is_file():
        raise FileNotFoundError(config.ca_cert)

    manifest = read_json(config.manifest)
    team_id = validate_team_id(manifest)
    allowlist = read_json(config.allowlist)
    teams = allowlist.get("teams")
    if not isinstance(teams, dict) or team_id not in teams:
        raise ValueError(f"{team_id} is not in the team allowlist")

    team_entry = teams[team_id]
    if not isinstance(team_entry, dict):
        raise ValueError(f"{team_id} has an invalid allowlist entry")
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        cert = resolve_team_cert(team_id, team_entry, config.repository_root, temp_path)
        expected_sha256 = team_entry.get("cert_sha256")
        actual_sha256 = hashlib.sha256(cert.read_bytes()).hexdigest()
        if expected_sha256 != actual_sha256:
            raise ValueError(f"{team_id} certificate digest does not match allowlist")

        run_openssl(["verify", "-CAfile", str(config.ca_cert), str(cert)])
        public_key = Path(temp_dir) / "team_public_key.pem"
        subprocess.run(
            [
                "openssl",
                "x509",
                "-in",
                str(cert),
                "-pubkey",
                "-noout",
                "-out",
                str(public_key),
            ],
            check=True,
        )
        run_openssl(
            [
                "dgst",
                "-sha256",
                "-verify",
                str(public_key),
                "-signature",
                str(config.signature),
                str(config.manifest),
            ]
        )
    print(f"Verified signed manifest for {team_id}.")
    return team_id


def main() -> None:
    args = parse_args()
    verify_submission(
        VerificationConfig(
            manifest=args.manifest,
            signature=args.signature,
            allowlist=args.allowlist,
            ca_cert=args.ca_cert,
            repository_root=args.repository_root,
        )
    )


if __name__ == "__main__":
    main()
