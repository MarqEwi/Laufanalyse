#Requires -Version 5.1
<#
.SYNOPSIS
  Richtet den Garmin-MCP-Server und die Skill "laufanalyse" fuer Claude Code auf dem Windows-PC ein
  und erzeugt den Token-Wert fuer Cloud-Sessions (Smartphone / claude.ai/code).

.DESCRIPTION
  1. prueft uv und die Claude-CLI
  2. fragt E-Mail und Passwort ab (Passwort ohne Anzeige) und legt sie als BENUTZER-Umgebungsvariablen ab
     (Registry HKCU\Environment, keine Datei im Repo)
  3. meldet sich einmalig an (MFA-Code wird abgefragt), Token-Cache unter %USERPROFILE%\.garminconnect,
     Test: letzte 5 Aktivitaeten + Kennzahlen des letzten Laufs
  4. registriert den MCP-Server "garmin" (scripts\garmin_mcp_server.py) im User-Scope von Claude Code,
     damit er auch ausserhalb dieses Repos verfuegbar ist (im Repo greift zusaetzlich .mcp.json)
  5. kopiert die Skill nach %USERPROFILE%\.claude\skills\laufanalyse (User-Scope)
  6. gibt den Wert fuer GARMIN_TOKENS_B64 aus (fuer die Cloud-Umgebung von Claude Code)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup-garmin-mcp.ps1
  powershell -ExecutionPolicy Bypass -File scripts\setup-garmin-mcp.ps1 -SkipLogin   # nur MCP + Skill neu registrieren
  powershell -ExecutionPolicy Bypass -File scripts\setup-garmin-mcp.ps1 -ShowTokenOnly # nur Token fuer die Cloud ausgeben
#>
param(
    [string]$Email = "marc.ewers@gmx.de",
    [switch]$SkipLogin,
    [switch]$SkipMcp,
    [switch]$SkipSkill,
    [switch]$ShowTokenOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ExpectedRoot = "E:\Users\Marc\Claude Projekte\GarminConnect"
if ($RepoRoot -ne $ExpectedRoot) {
    Write-Host "Hinweis: Repo liegt in '$RepoRoot', vorgesehen ist '$ExpectedRoot' (siehe CLAUDE.md)." -ForegroundColor Yellow
}
$TokenDir = Join-Path $env:USERPROFILE ".garminconnect"
$DataDir  = Join-Path $RepoRoot "data\garmin"
$Server   = Join-Path $RepoRoot "scripts\garmin_mcp_server.py"

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "FEHLT: '$cmd'. $hint" -ForegroundColor Red
        exit 1
    }
}
function ShowToken {
    Step "Token fuer Cloud-Sessions (Smartphone, claude.ai/code)"
    $env:GARMINTOKENS = $TokenDir
    $blob = (uv run (Join-Path $RepoRoot "scripts\garmin_login.py") --show-token)
    if ($LASTEXITCODE -ne 0) { Write-Host "Keine Tokens vorhanden - erst anmelden." -ForegroundColor Red; return }
    Write-Host "In claude.ai/code -> Cloud-Umgebung bearbeiten -> Umgebungsvariablen eintragen:"
    Write-Host ""
    Write-Host "GARMIN_EMAIL=$Email"
    Write-Host "GARMIN_TOKENS_B64=$blob"
    Write-Host ""
    Write-Host "Netzwerkzugriff der Umgebung auf 'Custom' stellen und '*.garmin.com' als erlaubte Domain eintragen."
    try { Set-Clipboard -Value "GARMIN_TOKENS_B64=$blob"; Write-Host "(GARMIN_TOKENS_B64=... liegt in der Zwischenablage)" } catch {}
}

Step "Voraussetzungen pruefen"
Need uv     "Installieren mit:  winget install --id astral-sh.uv -e   (danach neues Terminal oeffnen)"
Need claude "Claude Code CLI nicht gefunden. Installation: https://code.claude.com/docs"
Write-Host ("uv:     " + (uv --version))
Write-Host ("claude: " + (claude --version))

if ($ShowTokenOnly) { ShowToken; exit 0 }

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
    Step "MCP-Server 'garmin' im User-Scope registrieren (Abhaengigkeiten vorinstallieren)"
    uv run $Server --warmup
    & claude mcp remove garmin -s user 2>$null | Out-Null
    & claude mcp add garmin -s user -e "GARMINTOKENS=$TokenDir" -e "LAUFANALYSE_DATA_DIR=$DataDir" -- uv run $Server
    Write-Host "Hinweis: GARMIN_EMAIL/GARMIN_PASSWORD kommen aus den Benutzer-Umgebungsvariablen."
    Write-Host "         Claude Code aus einem NEUEN Terminal starten, damit es sie sieht."
    & claude mcp list
}

if (-not $SkipSkill) {
    Step "Skill 'laufanalyse' in den User-Scope kopieren"
    $SkillDst = Join-Path $env:USERPROFILE ".claude\skills\laufanalyse"
    New-Item -ItemType Directory -Force -Path (Join-Path $SkillDst "scripts") | Out-Null
    Copy-Item -Force (Join-Path $RepoRoot ".claude\skills\laufanalyse\SKILL.md") $SkillDst
    foreach ($f in "garmin_auth.py", "garmin_export.py", "garmin_login.py", "garmin_mcp_server.py") {
        Copy-Item -Force (Join-Path $RepoRoot "scripts\$f") (Join-Path $SkillDst "scripts")
    }
    Write-Host "Skill liegt in: $SkillDst  (Aufruf in Claude Code: /laufanalyse)"
}

ShowToken

Step "Fertig"
Write-Host "PC:         neues Terminal, 'claude' starten, /mcp pruefen ('garmin' connected), /laufanalyse"
Write-Host "Smartphone: Cloud-Umgebung mit den oben ausgegebenen Variablen + Netzwerk '*.garmin.com', dann Session auf diesem Repo starten"
Write-Host "Rohdaten:   $DataDir"
