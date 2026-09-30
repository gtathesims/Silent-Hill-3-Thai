$ErrorActionPreference = 'Stop'

$installerRoot = Split-Path -Parent $PSScriptRoot
$compiler = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
$script = Join-Path $installerRoot 'inno\SilentHill3ThaiModInstaller.iss'

if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    throw "Inno Setup compiler not found: $compiler"
}
if (-not (Test-Path -LiteralPath (Join-Path $installerRoot 'build\windows_bundle\SilentHill3ThaiModInstaller\ModPatcher.exe') -PathType Leaf)) {
    throw 'Patch engine bundle is missing. Run build_windows_bundle.ps1 first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $installerRoot 'inno\assets\welcome.bmp') -PathType Leaf)) {
    throw 'Welcome image is missing: inno\assets\welcome.bmp'
}

& $compiler $script
if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed with exit code $LASTEXITCODE" }
