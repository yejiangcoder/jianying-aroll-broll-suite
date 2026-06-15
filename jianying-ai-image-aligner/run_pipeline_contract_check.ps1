param(
  [string]$DraftDir,
  [string]$BrollMd,
  [string]$ImageDir
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($DraftDir) -or [string]::IsNullOrWhiteSpace($BrollMd) -or [string]::IsNullOrWhiteSpace($ImageDir)) {
  throw "必须显式传入 -DraftDir、-BrollMd、-ImageDir；禁止使用旧项目默认值。"
}
foreach ($PathToCheck in @($DraftDir, $BrollMd, $ImageDir)) {
  if (!(Test-Path -LiteralPath $PathToCheck)) {
    throw "路径不存在：$PathToCheck"
  }
}
$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  $Python = "python"
}

& (Join-Path $PSScriptRoot "cleanup_runtime.ps1") -KeepLatest 5 -ConfirmDelete

& $Python "D:\video tools\jianying-ai-image-aligner\src\pipeline_contract_check.py" `
  --draft-dir $DraftDir `
  --broll $BrollMd `
  --image-dir $ImageDir
