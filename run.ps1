param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
$taskMarker = Join-Path $PSScriptRoot '.venv/.pooltrace-installed'
$taskNeedsInstall = -not (Test-Path -LiteralPath $taskMarker)
if (-not $taskNeedsInstall) {
    $taskInstalledAt = (Get-Item -LiteralPath $taskMarker).LastWriteTimeUtc
    $taskNeedsInstall = (Get-Item -LiteralPath 'pyproject.toml').LastWriteTimeUtc -gt $taskInstalledAt -or (Get-Item -LiteralPath 'requirements-lock.txt').LastWriteTimeUtc -gt $taskInstalledAt
}
if ($taskNeedsInstall) {
    & $taskPython -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $taskPython -m pip install -e '.[test]' --no-deps
    if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }
    New-Item -ItemType File -Path $taskMarker -Force | Out-Null
}
& $taskPython -m pooltrace demo
if ($LASTEXITCODE -ne 0) { throw 'Demo initialization failed.' }
Write-Host "PoolTrace is available at http://127.0.0.1:$Port"
& $taskPython -m pooltrace serve --port $Port
