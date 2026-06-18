param(
  [string]$DraftDir,
  [string]$JyDraftc = "",
  [string]$StatePath = "",
  [string]$Stage = "aroll_qc_passed"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "pipeline_current_draft.ps1")
if ([string]::IsNullOrWhiteSpace($DraftDir)) {
  throw "Explicit -DraftDir is required when binding the QC-passed draft."
}
if (!(Test-Path -LiteralPath $DraftDir)) {
  throw "DraftDir does not exist: $DraftDir"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\bind_current_draft.py"),
  "--draft-dir", $DraftDir,
  "--stage", $Stage
)
if (![string]::IsNullOrWhiteSpace($JyDraftc)) {
  if (!(Test-Path -LiteralPath $JyDraftc)) {
    throw "jy-draftc path does not exist: $JyDraftc"
  }
  $ArgsList += @("--jy-draftc", $JyDraftc)
}
if (![string]::IsNullOrWhiteSpace($StatePath)) {
  $ArgsList += @("--state-path", $StatePath)
}

$ExitCode = Invoke-ImageAlignerPython -Arguments $ArgsList
exit $ExitCode
