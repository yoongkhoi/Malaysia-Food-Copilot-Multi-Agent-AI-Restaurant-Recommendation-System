# Local verification. This is not a deployment pipeline.
$ErrorActionPreference = "Stop"
$Python = "d:\project1\final-project\.python\python.exe"
$Node = "d:\project1\malaysia-food-copilot\.node-src\node-v22.21.0-win-x64"
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONUTF8 = "1"
& $Python -m pytest tests -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python scripts\copilot.py review-check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python scripts\copilot.py evidence-check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python scripts\copilot.py validate
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python scripts\copilot.py evaluate
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$env:PATH = "$Node;" + $env:PATH
Set-Location frontend
npm test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run build
exit $LASTEXITCODE
