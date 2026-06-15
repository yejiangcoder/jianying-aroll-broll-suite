param(
    [string]$StartId = "",
    [switch]$ConfirmedSetup,
    [switch]$ConfirmedLocked,
    [switch]$DryRunOnly
)

$ErrorActionPreference = "Stop"

Write-Host "DEPRECATED_COMPAT_ENTRY"
Write-Host "旧 UI drag 执行器已废弃。本入口现在转到草稿直写工具。"

if ($DryRunOnly) {
    & "D:\video tools\jianying-ai-image-aligner\run_pipeline_contract_check.ps1"
    exit $LASTEXITCODE
}

& "D:\video tools\jianying-ai-image-aligner\run_direct_draft_write.ps1"
exit $LASTEXITCODE
