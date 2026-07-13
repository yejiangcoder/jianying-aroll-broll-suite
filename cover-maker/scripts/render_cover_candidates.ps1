param(
  [Parameter(Mandatory=$true)][string]$CoverJobPath,
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "render_cover_candidates.py"
$py = Get-Command py.exe -ErrorAction SilentlyContinue
$python = if ($py) { @($py.Source, "-3") } else { @((Get-Command python.exe -ErrorAction Stop).Source) }
$arguments = @($scriptPath, "--job", $CoverJobPath)
if ($Force) { $arguments += "--force" }

if ($python.Count -gt 1) {
  & $python[0] $python[1..($python.Count - 1)] $arguments
} else {
  & $python[0] $arguments
}
if ($LASTEXITCODE -ne 0) {
  throw "Deterministic cover rendering failed with exit code $LASTEXITCODE."
}
