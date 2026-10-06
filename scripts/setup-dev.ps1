param([string]$PythonCommand = 'python')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot)
if ([Environment]::Is64BitOperatingSystem -ne $true) { throw 'Windows x64 is required.' }
$NodeMajor = & node -p "process.versions.node.split('.')[0]"
if ($LASTEXITCODE -or [int]$NodeMajor -ne 24) { throw 'Install Node.js 24 x64 before running setup.' }
$PythonVersion = & $PythonCommand -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($LASTEXITCODE -or $PythonVersion -ne '3.13') { throw 'Install Python 3.13 x64, or supply -PythonCommand with its executable path.' }
$PythonBits = & $PythonCommand -c "import struct; print(struct.calcsize('P') * 8)"
if ($LASTEXITCODE -or $PythonBits -ne '64') { throw 'Python must be 64-bit.' }
$DevPython = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $DevPython)) {
    & $PythonCommand -m venv .venv
    if ($LASTEXITCODE) { throw 'Python virtual environment creation failed.' }
}
$DevVersion = & $DevPython -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($LASTEXITCODE -or $DevVersion -ne '3.13') { throw 'Existing .venv uses another Python version. Rename it and rerun setup.' }
& $DevPython -m pip install -r requirements-build.txt
if ($LASTEXITCODE) { throw 'Python dependency installation failed.' }
& npm.cmd ci --ignore-scripts
if ($LASTEXITCODE) { throw 'Desktop dependency installation failed.' }
& $DevPython scripts/download_electron.py
if ($LASTEXITCODE) { throw 'Electron download or checksum verification failed.' }
& npm.cmd --prefix frontend ci
if ($LASTEXITCODE) { throw 'Frontend dependency installation failed.' }
& node scripts/prepare-assets.cjs
if ($LASTEXITCODE) { throw 'PDF.js asset preparation failed.' }
& npm.cmd --prefix frontend run build
if ($LASTEXITCODE) { throw 'Frontend build failed.' }
if (-not (Get-Command xelatex -ErrorAction SilentlyContinue)) {
    Write-Warning 'XeLaTeX not found. Browsing works; editing, preview and PDF export require XeLaTeX. Configure it in application settings.'
}
Write-Output 'Setup complete. Run npm start. API keys are optional and entered only in your local application settings.'
