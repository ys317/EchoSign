# Build in a staging folder so PyInstaller never deletes a user's configuration.
param([switch]$StageOnly)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$buildPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$stageRoot = Join-Path $projectRoot 'build\ui-dist'
$targetRoot = Join-Path $projectRoot 'dist\EchoSign'
$specPath = Join-Path $projectRoot 'EchoSign.spec'

if (-not (Test-Path -LiteralPath $buildPython)) {
    throw 'The project .venv is missing. Install the development dependencies first.'
}

$previousCache = $env:PYINSTALLER_CONFIG_DIR
$env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot 'build\pyinstaller-cache'
Push-Location $projectRoot
try {
    & $buildPython -m PyInstaller --noconfirm --distpath $stageRoot --workpath (Join-Path $projectRoot 'build') $specPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    $stagedApp = Join-Path $stageRoot 'EchoSign'
    foreach ($supportFile in @('install_browser.bat', 'README.md')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot $supportFile) -Destination (Join-Path $stagedApp $supportFile) -Force
    }
    $stagedAssets = Join-Path $stagedApp 'assets'
    New-Item -ItemType Directory -Path $stagedAssets -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot 'assets\screenshots') -Destination $stagedAssets -Recurse -Force
    if ($StageOnly) {
        Write-Output "Staged: $(Join-Path $stagedApp 'EchoSign.exe')"
        return
    }
    New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
    # Merge runtime files; config.yaml, credentials, profiles and models stay in place.
    Copy-Item -LiteralPath (Join-Path $stagedApp '_internal') -Destination $targetRoot -Recurse -Force
    foreach ($programFile in @('EchoSign.exe', 'install_browser.bat', 'README.md')) {
        Copy-Item -LiteralPath (Join-Path $stagedApp $programFile) -Destination (Join-Path $targetRoot $programFile) -Force
    }
    $targetAssets = Join-Path $targetRoot 'assets'
    New-Item -ItemType Directory -Path $targetAssets -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $stagedAssets 'screenshots') -Destination $targetAssets -Recurse -Force
    Write-Output "Built: $(Join-Path $targetRoot 'EchoSign.exe')"
}
finally {
    Pop-Location
    if ($null -eq $previousCache) {
        Remove-Item Env:\PYINSTALLER_CONFIG_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:PYINSTALLER_CONFIG_DIR = $previousCache
    }
}
