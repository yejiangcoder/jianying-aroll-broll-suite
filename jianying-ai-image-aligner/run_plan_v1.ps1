param(
    [string]$SrtPath = "",
    [switch]$DryRun,
    [switch]$StrictReady
)

$ErrorActionPreference = "Stop"

Write-Host "DEPRECATED_COMPAT_ENTRY"
Write-Host "旧 plan_v1/SRT 入口已废弃。当前只读取剪映草稿明文字幕轨和 B-ROLL 设计稿。"

if ($DryRun -or $StrictReady -or $SrtPath -ne "") {
    & (Join-Path $PSScriptRoot "run_pipeline_contract_check.ps1")
    exit $LASTEXITCODE
}

& (Join-Path $PSScriptRoot "run_direct_draft_write.ps1")
exit $LASTEXITCODE
