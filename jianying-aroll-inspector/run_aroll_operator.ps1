param(
  [ValidateSet("RunFull", "PreflightOnly", "Cleanup")]
  [string]$Intent = "RunFull",
  [string]$DraftName = "",
  [string]$DraftDir = "",
  [switch]$AutoCloseJianying
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  throw "Codex Python 不存在：$Python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_operator.py"),
  "--intent", $Intent
)
if ($DraftName -ne "") { $ArgsList += @("--draft-name", $DraftName) }
if ($DraftDir -ne "") { $ArgsList += @("--draft-dir", $DraftDir) }
if ($AutoCloseJianying) { $ArgsList += "--auto-close-jianying" }

Write-Host "MODE=AROLL_OPERATOR"
Write-Host "INTENT=$Intent"
if ($DraftName -ne "") { Write-Host "DRAFT_NAME=$DraftName" }
if ($DraftDir -ne "") { Write-Host "DRAFT_DIR=$DraftDir" }
Write-Host "SEMANTIC_DEEPSEEK_ARBITER=enabled_for_RunFull"

& $Python @ArgsList
