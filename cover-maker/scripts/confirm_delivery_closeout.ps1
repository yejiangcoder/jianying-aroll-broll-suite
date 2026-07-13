param(
  [string]$CurrentDraftPath = $(if ($env:AUTO_CLIP_RUNTIME_DIR) { Join-Path $env:AUTO_CLIP_RUNTIME_DIR "video_pipeline\current_draft.json" } else { Join-Path $HOME ".auto_clip_runtime\video_pipeline\current_draft.json" }),
  [string]$CompletionAssertScript = "",
  [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

if (-not $CompletionAssertScript) {
  $RepoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
  $CompletionAssertScript = Join-Path $RepoRoot "assert_clipping_factory_completion.ps1"
}

function Set-JsonProperty {
  param(
    [Parameter(Mandatory=$true)]$Object,
    [Parameter(Mandatory=$true)][string]$Name,
    $Value
  )
  if ($Object.PSObject.Properties.Name -contains $Name) {
    $Object.$Name = $Value
  } else {
    $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
  }
}

function Get-FirstExistingValue {
  param($Values)
  foreach ($value in $Values) {
    if ($value) { return [string]$value }
  }
  return ""
}

if (-not (Test-Path -LiteralPath $CurrentDraftPath)) {
  throw "CurrentDraftPath not found: $CurrentDraftPath"
}
if (-not (Test-Path -LiteralPath $CompletionAssertScript)) {
  throw "CompletionAssertScript not found: $CompletionAssertScript"
}

$state = Get-Content -LiteralPath $CurrentDraftPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$state.cover_qc_passed) {
  throw "DELIVERY_CLOSEOUT_BLOCKED: cover_qc_passed is not true."
}

$generationMode = Get-FirstExistingValue @($state.cover_generation_mode, $state.cover.generation_mode)
if ($generationMode -like "local_agent*") {
  $manifestPath = Get-FirstExistingValue @($state.cover_generation_manifest_path, $state.cover.generation_manifest_path)
  if (-not $manifestPath -or -not (Test-Path -LiteralPath $manifestPath)) {
    throw "DELIVERY_CLOSEOUT_BLOCKED: strict local cover generation manifest not found: $manifestPath"
  }
  $localManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([string]$localManifest.schema_version -eq "cover_generation_manifest.v2") {
    $validatorScript = Join-Path $PSScriptRoot "validate_cover_package.ps1"
    & $validatorScript -CoverGenerationManifestPath $manifestPath -CurrentDraftPath $CurrentDraftPath
  } elseif ([string]$state.stage -eq "closed_loop_complete" -and [string]$state.commander_closeout_status -eq "passed_closed_loop_complete") {
    Write-Warning "Legacy local cover manifest is accepted only because this delivery was already closed before cover_generation_manifest.v2. New promotion/closeout is blocked for legacy manifests."
  } else {
    throw "DELIVERY_CLOSEOUT_BLOCKED: local cover manifest must use cover_generation_manifest.v2."
  }
} elseif ($generationMode -eq "commander_web_llm_external_import") {
  $manifestPath = Get-FirstExistingValue @($state.cover_generation_manifest_path, $state.cover.generation_manifest_path)
  if (-not $manifestPath -or -not (Test-Path -LiteralPath $manifestPath)) {
    throw "DELIVERY_CLOSEOUT_BLOCKED: external cover import manifest not found: $manifestPath"
  }
  $importManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([string]$importManifest.schema_version -ne "official_cover_import.v1") {
    throw "DELIVERY_CLOSEOUT_BLOCKED: unsupported external cover manifest schema: $($importManifest.schema_version)"
  }
  if ([string]$importManifest.status -ne "commander_qc_passed") {
    throw "DELIVERY_CLOSEOUT_BLOCKED: external cover import has not passed commander QC."
  }
  if (-not $importManifest.expected_draft_name -or [string]$importManifest.expected_draft_name -ne [string]$state.draft_name) {
    throw "DELIVERY_CLOSEOUT_BLOCKED: external cover import draft binding mismatch."
  }
} else {
  throw "DELIVERY_CLOSEOUT_BLOCKED: unsupported cover generation mode: $generationMode"
}

$cover16 = Get-FirstExistingValue @($state.cover_16x9_path, $state.cover.cover_16x9_path, $state.cover.project_cover_16x9_path)
$cover9 = Get-FirstExistingValue @($state.cover_9x16_path, $state.cover.cover_9x16_path, $state.cover.project_cover_9x16_path)
if (-not $cover16 -or -not (Test-Path -LiteralPath $cover16)) {
  throw "DELIVERY_CLOSEOUT_BLOCKED: official 16:9 cover not found: $cover16"
}
if (-not $cover9 -or -not (Test-Path -LiteralPath $cover9)) {
  throw "DELIVERY_CLOSEOUT_BLOCKED: official 9:16 cover not found: $cover9"
}

$finalVideoPath = if ($state.final_export -and $state.final_export.video_path) { [string]$state.final_export.video_path } else { "" }
if (-not $finalVideoPath) {
  throw "DELIVERY_CLOSEOUT_BLOCKED: final_export.video_path is required."
}
if (-not (Test-Path -LiteralPath $finalVideoPath)) {
  throw "DELIVERY_CLOSEOUT_BLOCKED: final exported video not found: $finalVideoPath"
}

$closedAt = Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz"
if (-not $ValidateOnly) {
  Set-JsonProperty -Object $state -Name "stage" -Value "closed_loop_complete"
  Set-JsonProperty -Object $state -Name "delivery_status" -Value "closed_loop_complete"
  Set-JsonProperty -Object $state -Name "next_stage" -Value "none"
  Set-JsonProperty -Object $state -Name "factory_chain_complete" -Value $true
  Set-JsonProperty -Object $state -Name "commander_closeout_status" -Value "passed_closed_loop_complete"
  Set-JsonProperty -Object $state -Name "commander_closeout_confirmed_at" -Value $closedAt
  Set-JsonProperty -Object $state -Name "updated_at" -Value $closedAt
  $state | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $CurrentDraftPath -Encoding UTF8
}

$assertArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $CompletionAssertScript, "-CurrentDraftPath", $CurrentDraftPath, "-AssertComplete", "-RequireCoverFiles")
$assertArgs += "-RequireFinalExport"
$assertJson = & powershell @assertArgs
if ($LASTEXITCODE -ne 0) {
  throw "Completion assertion failed."
}

[PSCustomObject]@{
  status = if ($ValidateOnly) { "validated_closed_loop_ready" } else { "closed_loop_complete" }
  current_draft_path = $CurrentDraftPath
  cover_16x9_path = $cover16
  cover_9x16_path = $cover9
  final_video_path = $finalVideoPath
  completion_assertion = ($assertJson | ConvertFrom-Json)
} | ConvertTo-Json -Depth 12
