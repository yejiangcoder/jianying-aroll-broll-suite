param(
  [string]$DraftDir,
  [string]$BrollMd,
  [string]$ImageDir,
  [string]$VisualSlotPlan,
  [string]$JyDraftc = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "pipeline_current_draft.ps1")
$DraftDir = Resolve-ImageAlignerDraftDir -DraftDir $DraftDir
if ([string]::IsNullOrWhiteSpace($BrollMd) -or [string]::IsNullOrWhiteSpace($ImageDir) -or [string]::IsNullOrWhiteSpace($VisualSlotPlan)) {
  throw "Explicit -BrollMd, -ImageDir, and -VisualSlotPlan are required."
}
foreach ($PathToCheck in @($DraftDir, $BrollMd, $ImageDir, $VisualSlotPlan)) {
  if (!(Test-Path -LiteralPath $PathToCheck)) {
    throw "Path does not exist: $PathToCheck"
  }
}
if ([string]::IsNullOrWhiteSpace($JyDraftc)) {
  if (![string]::IsNullOrWhiteSpace($env:JY_DRAFTC_EXE)) {
    $JyDraftc = $env:JY_DRAFTC_EXE
  } elseif (![string]::IsNullOrWhiteSpace($env:JY_DRAFTC)) {
    $JyDraftc = $env:JY_DRAFTC
  }
}
if ([string]::IsNullOrWhiteSpace($JyDraftc) -or !(Test-Path -LiteralPath $JyDraftc)) {
  throw "jy-draftc path does not exist. Pass -JyDraftc or set JY_DRAFTC_EXE/JY_DRAFTC."
}

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RuntimeRoot = $env:IMAGE_ALIGNER_RUNTIME_DIR
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
  $AutoClipRuntime = $env:AUTO_CLIP_RUNTIME_DIR
  if ([string]::IsNullOrWhiteSpace($AutoClipRuntime)) {
    $AutoClipRuntime = Join-Path $HOME ".auto_clip_runtime"
  }
  $RuntimeRoot = Join-Path $AutoClipRuntime "image_aligner"
}
$OutRoot = Join-Path $RuntimeRoot "preproduction_checks\preproduction_$Stamp"
New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null

Write-Host "PREPRODUCTION_DRAFT_DIR=$DraftDir"
Write-Host "PREPRODUCTION_BROLL_MD=$BrollMd"
Write-Host "PREPRODUCTION_IMAGE_DIR=$ImageDir"
Write-Host "PREPRODUCTION_VISUAL_SLOT_PLAN=$VisualSlotPlan"
Write-Host "PREPRODUCTION_OUT_DIR=$OutRoot"

$PreflightLog = Join-Path $OutRoot "preflight_only.log"
$NegativeLog = Join-Path $OutRoot "negative_tests.log"

$PreflightArgs = @(
  "-NoProfile", "-ExecutionPolicy", "Bypass",
  "-File", (Join-Path $PSScriptRoot "run_direct_draft_write.ps1"),
  "-DraftDir", $DraftDir,
  "-BrollMd", $BrollMd,
  "-ImageDir", $ImageDir,
  "-VisualSlotPlan", $VisualSlotPlan,
  "-JyDraftc", $JyDraftc
)
& powershell @PreflightArgs *> $PreflightLog
$PreflightExit = $LASTEXITCODE
Get-Content -LiteralPath $PreflightLog
if ($PreflightExit -ne 0) {
  throw "Preproduction preflight failed. Log: $PreflightLog"
}

$NegativeArgs = @(
  "-NoProfile", "-ExecutionPolicy", "Bypass",
  "-File", (Join-Path $PSScriptRoot "run_negative_tests.ps1"),
  "-DraftDir", $DraftDir,
  "-BrollMd", $BrollMd,
  "-ImageDir", $ImageDir,
  "-VisualSlotPlan", $VisualSlotPlan,
  "-JyDraftc", $JyDraftc
)
& powershell @NegativeArgs *> $NegativeLog
$NegativeExit = $LASTEXITCODE
Get-Content -LiteralPath $NegativeLog
if ($NegativeExit -ne 0) {
  throw "Preproduction negative tests failed. Log: $NegativeLog"
}

$RunsDir = Join-Path $RuntimeRoot "runs"
$NegativeTestsDir = Join-Path $RuntimeRoot "negative_tests"
$LatestPreflight = if (Test-Path -LiteralPath $RunsDir) {
  Get-ChildItem -LiteralPath $RunsDir -Directory |
    Where-Object { $_.Name -like "direct_write_*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
} else { $null }
$LatestNegative = if (Test-Path -LiteralPath $NegativeTestsDir) {
  Get-ChildItem -LiteralPath $NegativeTestsDir -Directory |
    Where-Object { $_.Name -like "negative_tests_*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
} else { $null }

$Summary = [ordered]@{
  status = "ready"
  draft_dir = $DraftDir
  broll_md = $BrollMd
  image_dir = $ImageDir
  visual_slot_plan = $VisualSlotPlan
  jy_draftc = $JyDraftc
  preflight_log = $PreflightLog
  negative_log = $NegativeLog
  latest_preflight_report = if ($LatestPreflight) { Join-Path $LatestPreflight.FullName "broll_exec_plan.csv" } else { "" }
  latest_negative_report = if ($LatestNegative) { Join-Path $LatestNegative.FullName "negative_test_report.json" } else { "" }
}
$SummaryPath = Join-Path $OutRoot "preproduction_summary.json"
$Summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $SummaryPath -Encoding UTF8
Write-Host "PREPRODUCTION_STATUS=ready"
Write-Host "PREPRODUCTION_SUMMARY=$SummaryPath"
exit 0
