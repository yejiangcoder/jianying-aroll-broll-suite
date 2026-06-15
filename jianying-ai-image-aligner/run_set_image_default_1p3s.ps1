$ErrorActionPreference = "Stop"

Write-Host "DEPRECATED_COMPAT_ENTRY"
Write-Host "剪映默认图片时长设置入口已废弃。草稿直写工具会把每张 AI 图强制写成 1.3 秒。"

& (Join-Path $PSScriptRoot "run_pipeline_contract_check.ps1")
exit $LASTEXITCODE
