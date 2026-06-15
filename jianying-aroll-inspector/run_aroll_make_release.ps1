param(
  [string]$Version = "v0.1.0",
  [string]$ReleaseDir = "D:\auto_clip_runtime\packages\release"
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
  (Join-Path $PSScriptRoot "src\aroll_make_release.py"),
  "--version", $Version,
  "--release-dir", $ReleaseDir
)

& $Python @ArgsList
