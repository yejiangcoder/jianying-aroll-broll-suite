param(
  [string]$DraftDir = "",
  [string]$BackupDir = "",
  [string]$ScriptPath = "",
  [ValidateSet("production", "debug")]
  [string]$RuntimeMode = "production",
  [bool]$AllowConstantSpeed = $true,
  [double]$MaxAllowedSpeed = 1.25,
  [switch]$KeepDebugDecJson,
  [switch]$KeepAudioPcm,
  [bool]$RunCleanupBefore = $true,
  [bool]$RunCleanupAfter = $true,
  [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $DraftDir)) {
  throw "草稿目录不存在：$DraftDir"
}

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  throw "Codex Python 不存在：$Python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_uat_full.py"),
  "--draft-dir", $DraftDir,
  "--runtime-mode", $RuntimeMode,
  "--max-allowed-speed", $MaxAllowedSpeed
)
if ($BackupDir -ne "") { $ArgsList += @("--backup-dir", $BackupDir) }
if ($ScriptPath -ne "") { $ArgsList += @("--script-path", $ScriptPath) }
if ($AllowConstantSpeed) { $ArgsList += "--allow-constant-speed" } else { $ArgsList += "--no-allow-constant-speed" }
if ($KeepDebugDecJson) { $ArgsList += "--keep-debug-dec-json" }
if ($KeepAudioPcm) { $ArgsList += "--keep-audio-pcm" }
if (-not $RunCleanupBefore) { $ArgsList += "--no-run-cleanup-before" }
if (-not $RunCleanupAfter) { $ArgsList += "--no-run-cleanup-after" }
if ($PreflightOnly) { $ArgsList += "--preflight-only" }

Write-Host "MODE=AROLL_UAT_FULL"
Write-Host "DRAFT_DIR=$DraftDir"
Write-Host "RUNTIME_MODE=$RuntimeMode"
Write-Host "ALLOW_CONSTANT_SPEED=$AllowConstantSpeed"
Write-Host "MAX_ALLOWED_SPEED=$MaxAllowedSpeed"
Write-Host "SEMANTIC_DEEPSEEK_ARBITER=enabled_for_RunFull"
Write-Host "REFUSE_WRITE_IF_JIANYING_RUNNING=1"

& $Python @ArgsList
