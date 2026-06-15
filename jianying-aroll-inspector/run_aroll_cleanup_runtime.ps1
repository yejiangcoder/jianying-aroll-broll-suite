param(
  [string]$OutputDir = "D:\auto_clip_runtime\arll\runs\cleanup_manual_$(Get-Date -Format 'yyyyMMdd_HHmmss')",
  [int]$KeepLatestEngine = 2,
  [int]$KeepLatestPhase6B = 3,
  [int]$KeepLatestOperator = 3,
  [int]$KeepLatestUat = 3,
  [int]$KeepLatestInspect = 1,
  [switch]$PruneOldRuntimeDirs,
  [switch]$DeleteTempAudio,
  [switch]$DeleteDebugDraftJson,
  [switch]$KeepCurrentRun,
  [switch]$DryRun,
  [switch]$Execute
)

$ErrorActionPreference = "Stop"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  throw "Codex Python 不存在：$Python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_cleanup_runtime.py"),
  "--output-dir", $OutputDir,
  "--runtime-dir", "D:\auto_clip_runtime\arll\runs",
  "--keep-latest-engine", $KeepLatestEngine,
  "--keep-latest-phase6b", $KeepLatestPhase6B,
  "--keep-latest-operator", $KeepLatestOperator,
  "--keep-latest-uat", $KeepLatestUat,
  "--keep-latest-inspect", $KeepLatestInspect
)
if ($PruneOldRuntimeDirs) { $ArgsList += "--prune-old-runtime-dirs" }
if ($KeepCurrentRun -or $Execute) { $ArgsList += "--keep-current-run" }
if ($DeleteTempAudio -or $Execute) { $ArgsList += "--delete-temp-audio" }
if ($DeleteDebugDraftJson -or $Execute) { $ArgsList += "--delete-debug-draft-json" }
if ($Execute) {
  $ArgsList += "--execute"
} else {
  $ArgsList += "--dry-run"
}

& $Python @ArgsList
