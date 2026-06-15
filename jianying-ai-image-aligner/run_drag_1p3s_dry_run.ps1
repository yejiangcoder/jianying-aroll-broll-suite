$ErrorActionPreference = "Stop"

Write-Host "DEPRECATED_COMPAT_ENTRY"
Write-Host "旧拖拽 dry-run 已废弃。本入口现在执行三件套契约检测。"

& (Join-Path $PSScriptRoot "run_pipeline_contract_check.ps1")
exit $LASTEXITCODE
