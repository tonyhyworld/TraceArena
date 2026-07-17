$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
& $Python -c "import sys; assert sys.version_info >= (3,10), 'TraceArena requires Python 3.10 or newer.'"

if (-not (Test-Path ".venv")) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "TraceArena could not create a Python virtual environment. Install Python 3.10+ with venv/ensurepip, then retry."
    }
}

& ".venv\Scripts\python.exe" -m pip install -e ".[dev]"

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm is required to install the Vue frontend."
}

Push-Location frontend
npm ci
Pop-Location

if ((-not (Test-Path "frontend\.env.local")) -and (Test-Path "frontend\.env.example")) {
    Copy-Item "frontend\.env.example" "frontend\.env.local"
}

Write-Host "TraceArena is installed."
Write-Host "Next: .\.venv\Scripts\Activate.ps1; cd frontend; npm run dev"
