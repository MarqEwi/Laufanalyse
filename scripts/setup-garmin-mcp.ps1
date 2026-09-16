#Requires -Version 5.1
<#
.SYNOPSIS
  Richtet den Garmin-Connect-MCP-Server (mcp-garmin) und die Skill "laufanalyse" fuer Claude Code ein (Windows).

.DESCRIPTION
  1. prueft uv und die Claude-CLI, stellt Python 3.14 fuer mcp-garmin bereit
  2. fragt E-Mail und Passwort ab (Passwort ohne Anzeige) und legt sie als BENUTZER-Umgebungsvariablen ab
     (Registry HKCU\Environment, keine Datei im Repo)
  3. meldet sich einmalig an (MFA-Code wird abgefragt) und legt den Token-Cache unter %USERPROFILE%\.garminconnect an
  4. registriert den MCP-Server "garmin" im User-Scope von Claude Code
  5. kopiert die Skill nach %USERPROFILE%\.claude\skills\laufanalyse (User-Scope)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup-garmin-mcp.ps1
  powershell -ExecutionPolicy Bypass -File scripts\setup-garmin-mcp.ps1 -SkipLogin   # nur MCP + Skill neu registrieren
#>
param(
    [string]$Email = "marc.ewers@gmx.de",
    [switch]$SkipLogin,
    [switch]$SkipMcp,
    [switch]$SkipSkill
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$TokenDir = Join-Path $env:USERPROFILE ".garminconnect"
$DataDir  = Join-Path $RepoRoot "data\garmin"

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "FEHLT: '$cmd'. $hint" -ForegroundColor Red
        exit 1
    }
}

Step "Voraussetzungen pruefen"
Need uv     "Installieren mit:  winget install --id astral-sh.uv -e   (danach neues Terminal oeffnen)"
Need claude "Claude Code CLI nicht gefunden. Installation: https://code.claude.com/docs"
Write-Host ("uv:     " + (uv --version))
Write-Host ("claude: " + (claude --version))
Write-Host "Python 3.14 fuer mcp-garmin bereitstellen (einmalig, uv laedt es herunter) ..."
uv python install 3.14 | Out-Host

Step "Zugangsdaten (werden NUR als Benutzer-Umgebungsvariablen gespeichert)"
$emailIn = Read-Host "Garmin-E-Mail [$Email]"
if ($emailIn) { $Email = $emailIn.Trim() }
$plain = $null
if (-not $SkipLogin) {
    $secure = Read-Host "Garmin-Passwort (keine Anzeige)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    if (-not $plain) { Write-Host "Kein Passwort eingegeben." -ForegroundColor Red; exit 1 }
}

[Environment]::SetEnvironmentVariable("GARMIN_EMAIL", $Email, "User")
if ($plain) { [Environment]::SetEnvironmentVariable("GARMIN_PASSWORD", $plain, "User") }
[Environment]::SetEnvironmentVariable("GARMINTOKENS", $TokenDir, "User")
[Environment]::SetEnvironmentVariable("LAUFANALYSE_DATA_DIR", $DataDir, "User")
$env:GARMIN_EMAIL = $Email
if ($plain) { $env:GARMIN_PASSWORD = $plain }
$env:GARMINTOKENS = $TokenDir
$env:LAUFANALYSE_DATA_DIR = $DataDir
New-Item -ItemType Directory -Force -Path $TokenDir | Out-Null
New-Item -ItemType Directory -Force -Path $DataDir  | Out-Null
Write-Host "Gesetzt: GARMIN_EMAIL, GARMIN_PASSWORD, GARMINTOKENS=$TokenDir, LAUFANALYSE_DATA_DIR=$DataDir"

if (-not $SkipLogin) {
    Step "Anmeldung bei Garmin Connect (bei MFA wird der Code abgefragt) + Test: letzte 5 Aktivitaeten"
    uv run (Join-Path $RepoRoot "scripts\garmin_login.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Anmeldung fehlgeschlagen - Setup abgebrochen. Passwort pruefen, bei 429 einige Minuten warten." -ForegroundColor Red
        exit 1
    }
}

if (-not $SkipMcp) {
    Step "MCP-Server 'garmin' im User-Scope registrieren"
    # Vorhandene Registrierung still entfernen
    & claude mcp remove garmin -s user 2>$null | Out-Null
    & claude mcp add garmin -s user -e "GARMINTOKENS=$TokenDir" -- uvx --python 3.14 mcp-garmin
    Write-Host "Hinweis: GARMIN_EMAIL/GARMIN_PASSWORD kommen aus den Benutzer-Umgebungsvariablen."
    Write-Host "         Claude Code muss aus einem NEUEN Terminal gestartet werden, damit es sie sieht."
    & claude mcp list
}

if (-not $SkipSkill) {
    Step "Skill 'laufanalyse' in den User-Scope kopieren"
    $SkillDst = Join-Path $env:USERPROFILE ".claude\skills\laufanalyse"
    New-Item -ItemType Directory -Force -Path (Join-Path $SkillDst "scripts") | Out-Null
    Copy-Item -Force (Join-Path $RepoRoot ".claude\skills\laufanalyse\SKILL.md") $SkillDst
    foreach ($f in "garmin_auth.py", "garmin_export.py", "garmin_login.py") {
        Copy-Item -Force (Join-Path $RepoRoot "scripts\$f") (Join-Path $SkillDst "scripts")
    }
    Write-Host "Skill liegt in: $SkillDst  (Aufruf in Claude Code: /laufanalyse)"
}

Step "Fertig"
Write-Host "Naechste Schritte:"
Write-Host "  1. Neues Terminal oeffnen (Umgebungsvariablen), dann 'claude' starten."
Write-Host "  2. /mcp  -> Server 'garmin' muss 'connected' sein."
Write-Host "  3. /laufanalyse  -> analysiert den letzten Lauf."
Write-Host "Rohdaten landen in: $DataDir"
