param(
    [string]$DraftRoot = "D:\JianyingPro Drafts",
    [string]$Draft,
    [string]$AiDir,
    [string]$BrollMd,
    [string]$OutputRoot = $env:IMAGE_ALIGNER_RUNTIME_DIR,
    [double]$Confidence = 0.56,
    [switch]$Overwrite,
    [switch]$NoOverlayVideo,
    [switch]$DryRunOnly,
    [switch]$ConfirmWrite
)

$ErrorActionPreference = "Stop"
if (-not $OutputRoot) {
    $OutputRoot = "D:\auto_clip_runtime\image_aligner\runs"
}
if ([string]::IsNullOrWhiteSpace($Draft) -or [string]::IsNullOrWhiteSpace($AiDir) -or [string]::IsNullOrWhiteSpace($BrollMd)) {
    throw "必须显式传入 -Draft、-AiDir、-BrollMd；禁止使用旧项目默认值。"
}

Write-Host "DEPRECATED_COMPAT_ENTRY"
Write-Host "旧 align/overlay 入口已废弃。本入口现在只走剪映草稿直写路线。"

$DraftDir = Join-Path $DraftRoot $Draft
if ($DryRunOnly -or !$ConfirmWrite) {
    & (Join-Path $PSScriptRoot "run_pipeline_contract_check.ps1") -DraftDir $DraftDir -BrollMd $BrollMd -ImageDir $AiDir
    exit $LASTEXITCODE
}

& (Join-Path $PSScriptRoot "run_direct_draft_write.ps1") -DraftDir $DraftDir -BrollMd $BrollMd -ImageDir $AiDir -ConfirmWrite
exit $LASTEXITCODE
