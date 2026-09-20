<#
.SYNOPSIS
  Richtet die Concept2-Logbook-Anbindung auf dem Windows-PC ein (einmalig).

.DESCRIPTION
  1. fragt Client-ID und Client-Secret der bei https://log.concept2.com/developers/keys registrierten App ab
     (Redirect-URI dort: http://localhost:8765/callback)
  2. setzt die Benutzer-Umgebungsvariablen CONCEPT2_CLIENT_ID, CONCEPT2_CLIENT_SECRET, CONCEPT2_TOKENS,
     CONCEPT2_DATA_DIR (Registry HKCU\Environment, keine Datei im Repo)
  3. startet die Browser-Autorisierung (scripts/concept2_login.py) und den Smoke-Test
  4. gibt den Wert fuer CONCEPT2_TOKENS_B64 aus (fuer die Cloud-Umgebung von Claude Code)

  Aufruf im Repo-Ordner:  powershell -ExecutionPolicy Bypass -File scripts\setup-concept2.ps1
  Nur Token anzeigen:     powershell -ExecutionPolicy Bypass -File scripts\setup-concept2.ps1 -ShowToken
#>
param(
    [switch]$ShowToken,
    [string]$TokenDir = (Join-Path $env:USERPROFILE ".concept2"),
    [string]$DataDir = "E:\Users\Marc\Claude Projekte\GarminConnect\data\concept2"
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Login = Join-Path $Repo "scripts\concept2_login.py"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv fehlt. Installieren: powershell -c `"irm https://astral.sh/uv/install.ps1 | iex`"" -ForegroundColor Yellow
    exit 1
}

if ($ShowToken) {
    $env:CONCEPT2_TOKENS = $TokenDir
    $blob = & uv run $Login --show-token
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "CONCEPT2_TOKENS_B64=$blob"
    try { Set-Clipboard -Value "CONCEPT2_TOKENS_B64=$blob"; Write-Host "(CONCEPT2_TOKENS_B64=... liegt in der Zwischenablage)" } catch {}
    exit 0
}

$ClientId = Read-Host "Concept2 Client-ID"
$SecretSecure = Read-Host "Concept2 Client-Secret (keine Anzeige)" -AsSecureString
$Secret = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecretSecure))
if (-not $ClientId -or -not $Secret) { Write-Host "Abbruch: Client-ID und Client-Secret werden gebraucht."; exit 1 }

New-Item -ItemType Directory -Force -Path $TokenDir | Out-Null
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

[Environment]::SetEnvironmentVariable("CONCEPT2_CLIENT_ID", $ClientId, "User")
[Environment]::SetEnvironmentVariable("CONCEPT2_CLIENT_SECRET", $Secret, "User")
[Environment]::SetEnvironmentVariable("CONCEPT2_TOKENS", $TokenDir, "User")
[Environment]::SetEnvironmentVariable("CONCEPT2_DATA_DIR", $DataDir, "User")
$env:CONCEPT2_CLIENT_ID = $ClientId
$env:CONCEPT2_CLIENT_SECRET = $Secret
$env:CONCEPT2_TOKENS = $TokenDir
$env:CONCEPT2_DATA_DIR = $DataDir
Write-Host "Gesetzt: CONCEPT2_CLIENT_ID, CONCEPT2_CLIENT_SECRET, CONCEPT2_TOKENS=$TokenDir, CONCEPT2_DATA_DIR=$DataDir"

Write-Host "`nAutorisierung im Browser ..."
& uv run $Login
if ($LASTEXITCODE -ne 0) { Write-Host "Autorisierung fehlgeschlagen (siehe Meldung oben)." -ForegroundColor Yellow; exit $LASTEXITCODE }

$blob = & uv run $Login --show-token
Write-Host "`nFuer Cloud-Sessions (claude.ai/code -> Umgebung -> Umgebungsvariablen) eintragen:"
Write-Host "CONCEPT2_TOKENS_B64=$blob"
try { Set-Clipboard -Value "CONCEPT2_TOKENS_B64=$blob"; Write-Host "(liegt in der Zwischenablage)" } catch {}
Write-Host "Zusaetzlich log.concept2.com in der Netzwerk-Policy der Cloud-Umgebung freigeben."
