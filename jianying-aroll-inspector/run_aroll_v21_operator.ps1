param(
    [string]$InputJson = "",

    [string]$DraftDir = "",

    [string]$JyDraftc = "",

    [string]$WordTimelineJson = "",

    [string]$SemanticDecisionsJson = "",

    [string]$PostwriteMaterialsJson = "",

    [string]$RunDir = "",

    [string]$ReadyRunDir = "",

    [string]$OutputDir = "",

    [ValidateSet("dry-run", "write", "verify-only")]
    [string]$Mode = "dry-run",

    [ValidateSet("deterministic-baseline", "semantic-requests-only", "deepseek", "fail-closed", "default")]
    [string]$SemanticMode = "semantic-requests-only",

    [switch]$SimulateWrite,

    [switch]$Commit,

    [switch]$AllowSacrificialWriteWithoutPostwriteDecrypt
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Resolve-Python {
    if ($env:PYTHON) { return $env:PYTHON }
    if ($env:PYTHON_EXE) { return $env:PYTHON_EXE }
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) { return "py -3" }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    throw "PYTHON_NOT_FOUND: set PYTHON or PYTHON_EXE, or install Python on PATH"
}

$python = Resolve-Python
$env:PYTHONPATH = "src"
Set-Location $RepoRoot

$EffectiveRunDir = if ($RunDir) { $RunDir } elseif ($OutputDir) { $OutputDir } else { "" }
if (-not $EffectiveRunDir) {
    throw "RUN_DIR_REQUIRED: pass -RunDir or -OutputDir"
}

$ArgsList = @("-m", "aroll_v21.cli", "--output-dir", $EffectiveRunDir, "--mode", $Mode, "--semantic-mode", $SemanticMode)
if ($InputJson) { $ArgsList += @("--input-json", $InputJson) }
if ($DraftDir) { $ArgsList += @("--draft-dir", $DraftDir) }
if ($JyDraftc) { $ArgsList += @("--jy-draftc", $JyDraftc) }
if ($WordTimelineJson) { $ArgsList += @("--word-timeline-json", $WordTimelineJson) }
if ($SemanticDecisionsJson) { $ArgsList += @("--semantic-decisions-json", $SemanticDecisionsJson) }
if ($PostwriteMaterialsJson) { $ArgsList += @("--postwrite-materials-json", $PostwriteMaterialsJson) }
if ($ReadyRunDir) { $ArgsList += @("--ready-run-dir", $ReadyRunDir) }
if ($SimulateWrite) { $ArgsList += "--simulate-write" }
if ($Commit) { $ArgsList += "--commit" }
if ($AllowSacrificialWriteWithoutPostwriteDecrypt) { $ArgsList += "--allow-sacrificial-write-without-postwrite-decrypt" }

if ($python -eq "py -3") {
    & py -3 @ArgsList
} else {
    & $python @ArgsList
}
