$ErrorActionPreference = 'Stop'

$installerRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $installerRoot
$buildRoot = Join-Path $installerRoot 'build\windows_bundle'
$stageRoot = Join-Path $buildRoot 'stage'
$bundleRoot = Join-Path $buildRoot 'SilentHill3ThaiModInstaller'
$pyInstaller = (Get-Command pyinstaller -ErrorAction Stop).Source

New-Item -ItemType Directory -Force -Path $buildRoot, $stageRoot, $bundleRoot | Out-Null

& $pyInstaller --noconfirm --clean --onefile --name ModPatcher `
  --paths (Join-Path $workspaceRoot 'tools') `
  --add-data "$(Join-Path $installerRoot 'payload');payload" `
  --add-data "$(Join-Path $installerRoot 'games\silent_hill_3\profile.json');games\silent_hill_3" `
  --distpath $stageRoot `
  --workpath (Join-Path $buildRoot 'pyinstaller-engine') `
  --specpath $buildRoot `
  (Join-Path $installerRoot 'mod_patcher.py')
if ($LASTEXITCODE -ne 0) { throw "ModPatcher build failed with exit code $LASTEXITCODE" }

Copy-Item -Force (Join-Path $stageRoot 'ModPatcher.exe') (Join-Path $bundleRoot 'ModPatcher.exe')

Write-Host "Bundle created: $bundleRoot"
