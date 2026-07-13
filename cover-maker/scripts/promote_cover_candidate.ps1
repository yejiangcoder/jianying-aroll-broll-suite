param(
  [Parameter(Mandatory=$true)]
  [string]$CoverGenerationManifestPath,

  [Parameter(Mandatory=$true)]
  [string]$CandidateSetId,

  [string]$ProjectCoverDir = "",
  [string]$CurrentDraftPath = $(if ($env:AUTO_CLIP_RUNTIME_DIR) { Join-Path $env:AUTO_CLIP_RUNTIME_DIR "video_pipeline\current_draft.json" } else { Join-Path $HOME ".auto_clip_runtime\video_pipeline\current_draft.json" }),
  [switch]$UpdateCurrentDraft,
  [switch]$CommanderQcPassed,
  [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

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

function Copy-WithBackup {
  param([string]$Source, [string]$Target)
  if (Test-Path -LiteralPath $Target) {
    $backup = "$Target.previous_$(Get-Date -Format 'yyyyMMdd_HHmmss').bak"
    Move-Item -LiteralPath $Target -Destination $backup
  }
  Copy-Item -LiteralPath $Source -Destination $Target
}

if (-not (Test-Path -LiteralPath $CoverGenerationManifestPath)) {
  throw "CoverGenerationManifestPath not found: $CoverGenerationManifestPath"
}
if ($UpdateCurrentDraft -and -not $CommanderQcPassed) {
  throw "Use -CommanderQcPassed with -UpdateCurrentDraft. Candidate promotion must reflect commander cover QC."
}

$manifestPath = [System.IO.Path]::GetFullPath($CoverGenerationManifestPath)
$validatorScript = Join-Path $PSScriptRoot "validate_cover_package.ps1"
if (-not (Test-Path -LiteralPath $validatorScript)) {
  throw "Cover package validator not found: $validatorScript"
}
if ($UpdateCurrentDraft) {
  & $validatorScript -CoverGenerationManifestPath $manifestPath -CurrentDraftPath $CurrentDraftPath
} else {
  & $validatorScript -CoverGenerationManifestPath $manifestPath
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$candidate = @($manifest.cover_candidate_sets | Where-Object { $_.candidate_set_id -eq $CandidateSetId })[0]
if (-not $candidate) {
  throw "CandidateSetId not found in manifest: $CandidateSetId"
}
if (-not (Test-Path -LiteralPath $candidate.cover_16x9_path)) {
  throw "Candidate 16:9 cover not found: $($candidate.cover_16x9_path)"
}
if (-not (Test-Path -LiteralPath $candidate.cover_9x16_path)) {
  throw "Candidate 9:16 cover not found: $($candidate.cover_9x16_path)"
}

$outputRoot = if ($manifest.output_root) { [string]$manifest.output_root } else { Split-Path -Parent $manifestPath }
$officialDir = Join-Path $outputRoot "official"
$draftName = if ($manifest.draft_name) { [string]$manifest.draft_name } else { Split-Path -Leaf $outputRoot }
$safeDraftName = ($draftName -replace '[\\/:*?"<>|]', '_')
$official16 = Join-Path $officialDir ("{0}_cover_16x9_official.png" -f $safeDraftName)
$official9 = Join-Path $officialDir ("{0}_cover_9x16_official.png" -f $safeDraftName)

$project16 = ""
$project9 = ""
if ($ProjectCoverDir) {
  $resolvedProjectCoverDir = [System.IO.Path]::GetFullPath($ProjectCoverDir)
  $project16 = Join-Path $resolvedProjectCoverDir ("{0}_cover_16x9_official.png" -f $safeDraftName)
  $project9 = Join-Path $resolvedProjectCoverDir ("{0}_cover_9x16_official.png" -f $safeDraftName)
}

$passedAt = Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz"

if (-not $ValidateOnly) {
  New-Item -ItemType Directory -Path $officialDir -Force | Out-Null
  Copy-WithBackup -Source $candidate.cover_16x9_path -Target $official16
  Copy-WithBackup -Source $candidate.cover_9x16_path -Target $official9

  if ($ProjectCoverDir) {
    New-Item -ItemType Directory -Path $ProjectCoverDir -Force | Out-Null
    Copy-WithBackup -Source $official16 -Target $project16
    Copy-WithBackup -Source $official9 -Target $project9
  }

  foreach ($set in $manifest.cover_candidate_sets) {
    Set-JsonProperty -Object $set -Name "selected_as_official" -Value ([string]$set.candidate_set_id -eq $CandidateSetId)
  }
  Set-JsonProperty -Object $manifest -Name "selected_candidate_set_id" -Value $CandidateSetId
  Set-JsonProperty -Object $manifest -Name "cover_16x9_path" -Value $official16
  Set-JsonProperty -Object $manifest -Name "cover_9x16_path" -Value $official9
  Set-JsonProperty -Object $manifest -Name "official_output_dir" -Value $officialDir
  Set-JsonProperty -Object $manifest -Name "status" -Value "commander_qc_passed"
  Set-JsonProperty -Object $manifest -Name "manual_qc_status" -Value "commander_qc_passed"
  Set-JsonProperty -Object $manifest -Name "cover_qc_passed" -Value $true
  Set-JsonProperty -Object $manifest -Name "commander_qc_passed_at" -Value $passedAt
  if ($ProjectCoverDir) {
    Set-JsonProperty -Object $manifest -Name "project_cover_16x9_path" -Value $project16
    Set-JsonProperty -Object $manifest -Name "project_cover_9x16_path" -Value $project9
  }
  $manifest | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

  if ($UpdateCurrentDraft) {
    if (-not (Test-Path -LiteralPath $CurrentDraftPath)) {
      throw "CurrentDraftPath not found: $CurrentDraftPath"
    }
    $state = Get-Content -LiteralPath $CurrentDraftPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $cover = [PSCustomObject]@{
      status = "commander_qc_passed"
      generated_at = if ($manifest.created_at) { $manifest.created_at } else { $passedAt }
      output_dir = $outputRoot
      generation_mode = if ($manifest.cover_generation_mode) { $manifest.cover_generation_mode } else { "local_agent_deterministic_3_candidate_sets" }
      video_title = $manifest.video_title
      cover_title = $manifest.cover_title
      project_id = $manifest.project_id
      cover_job_id = $manifest.job_id
      cover_type = $manifest.cover_type
      template_set_id = $manifest.template_set_id
      subject_sha256 = $manifest.subject_sha256
      generation_manifest_path = $manifestPath
      selected_candidate_set_id = $CandidateSetId
      cover_16x9_path = $official16
      cover_9x16_path = $official9
      project_cover_16x9_path = $project16
      project_cover_9x16_path = $project9
      official_output_dir = $officialDir
      manual_qc_status = "commander_qc_passed"
      commander_qc_passed_at = $passedAt
      note = "$CandidateSetId selected by commander and promoted as official cover set."
    }
    Set-JsonProperty -Object $state -Name "cover" -Value $cover
    Set-JsonProperty -Object $state -Name "cover_generation_mode" -Value $manifest.cover_generation_mode
    Set-JsonProperty -Object $state -Name "cover_project_id" -Value $manifest.project_id
    Set-JsonProperty -Object $state -Name "cover_job_id" -Value $manifest.job_id
    Set-JsonProperty -Object $state -Name "cover_generation_manifest_path" -Value $manifestPath
    Set-JsonProperty -Object $state -Name "cover_candidate_sets_path" -Value $manifestPath
    Set-JsonProperty -Object $state -Name "cover_16x9_path" -Value $official16
    Set-JsonProperty -Object $state -Name "cover_9x16_path" -Value $official9
    Set-JsonProperty -Object $state -Name "cover_qc_passed" -Value $true
    Set-JsonProperty -Object $state -Name "factory_chain_complete" -Value $true
    Set-JsonProperty -Object $state -Name "stage" -Value "cover_qc_passed"
    Set-JsonProperty -Object $state -Name "delivery_status" -Value "cover_qc_passed"
    Set-JsonProperty -Object $state -Name "next_stage" -Value "delivery_closeout"
    Set-JsonProperty -Object $state -Name "updated_at" -Value $passedAt
    $state | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $CurrentDraftPath -Encoding UTF8
  }
}

[PSCustomObject]@{
  status = if ($ValidateOnly) { "validated_only" } else { "candidate_promoted" }
  selected_candidate_set_id = $CandidateSetId
  official_cover_16x9_path = $official16
  official_cover_9x16_path = $official9
  project_cover_16x9_path = $project16
  project_cover_9x16_path = $project9
  current_draft_updated = [bool]($UpdateCurrentDraft -and -not $ValidateOnly)
} | ConvertTo-Json -Depth 12
