param(
    [Parameter(Position = 0)]
    [string]$TeamPrivateKeyPath = $env:TEAM_PRIVATE_KEY_PATH
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$CertPath = Join-Path $RepoRoot ".github/tournament/public_keys/team_code_cert.pem"
$CleanPath = Join-Path $RepoRoot "submission/clean.py"
$CmsPath = Join-Path $RepoRoot "submission/clean.py.cms"
$ManifestPath = Join-Path $RepoRoot "submission/manifest.json"
$SignaturePath = Join-Path $RepoRoot "submission/manifest.sig"

function Find-OpenSsl {
    $Command = Get-Command openssl -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }

    function Join-OptionalPath {
        param(
            [string]$Root,
            [string]$Child
        )

        if ([string]::IsNullOrWhiteSpace($Root)) {
            return $null
        }
        return Join-Path $Root $Child
    }

    $Candidates = @(
        (Join-OptionalPath $env:ProgramFiles "Git/usr/bin/openssl.exe"),
        (Join-OptionalPath ${env:ProgramFiles(x86)} "Git/usr/bin/openssl.exe"),
        (Join-OptionalPath $env:ProgramFiles "OpenSSL-Win64/bin/openssl.exe"),
        (Join-OptionalPath $env:ProgramFiles "OpenSSL-Win32/bin/openssl.exe")
    )

    foreach ($Candidate in $Candidates) {
        if ($Candidate -and (Test-Path $Candidate)) {
            return $Candidate
        }
    }

    throw "OpenSSL was not found. Install Git for Windows, then reopen PowerShell and try again."
}

function Invoke-OpenSsl {
    param([string[]]$OpenSslArgs)

    & $script:OpenSslPath @OpenSslArgs
    if ($LASTEXITCODE -ne 0) {
        throw "OpenSSL failed: $($OpenSslArgs -join ' ')"
    }
}

if (-not (Test-Path $CertPath)) {
    throw "Public certificate not found: $CertPath"
}
if (-not (Test-Path $CleanPath)) {
    throw "Cleaner file not found: $CleanPath"
}

$script:OpenSslPath = Find-OpenSsl

Invoke-OpenSsl @(
    "cms",
    "-encrypt",
    "-aes-256-cbc",
    "-binary",
    "-outform",
    "DER",
    "-in",
    $CleanPath,
    "-out",
    $CmsPath,
    $CertPath
)

Write-Host "Encrypted submission/clean.py -> submission/clean.py.cms"

if ($TeamPrivateKeyPath) {
    if (-not (Test-Path $TeamPrivateKeyPath)) {
        throw "Team private key not found: $TeamPrivateKeyPath"
    }
    if (-not (Test-Path $ManifestPath)) {
        throw "submission/manifest.json not found"
    }

    $Manifest = Get-Content -Raw -Path $ManifestPath | ConvertFrom-Json
    $CodeSha256 = (Get-FileHash -Algorithm SHA256 -Path $CmsPath).Hash.ToLowerInvariant()

    $Manifest | Add-Member -NotePropertyName "code_path" -NotePropertyValue "submission/clean.py.cms" -Force
    $Manifest | Add-Member -NotePropertyName "code_sha256" -NotePropertyValue $CodeSha256 -Force

    $Json = $Manifest | ConvertTo-Json -Depth 20
    $Utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
    [System.IO.File]::WriteAllText($ManifestPath, "$Json`n", $Utf8NoBom)

    Invoke-OpenSsl @(
        "dgst",
        "-sha256",
        "-sign",
        $TeamPrivateKeyPath,
        "-out",
        $SignaturePath,
        $ManifestPath
    )

    Write-Host "Signed submission/manifest.json -> submission/manifest.sig"
}
