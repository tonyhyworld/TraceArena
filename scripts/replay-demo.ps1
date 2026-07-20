$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (Test-Path ".venv/Scripts/python.exe") {
    $Python = ".venv/Scripts/python.exe"
} elseif ($env:PYTHON_BIN) {
    $Python = $env:PYTHON_BIN
} else {
    $Python = "python"
}

if (-not (Get-Command $Python -ErrorAction SilentlyContinue) -and -not (Test-Path $Python)) {
    throw "TraceArena requires Python 3.10+. Run .\scripts\install.ps1 first or set PYTHON_BIN."
}

$env:PYTHONPATH = "backend"
$python_args = @(
    "backend/scripts/market_replay.py",
    "--fixture", "examples/market_replay/fixture.json",
    "--scenario", "backend/scenarios/capital_market",
    "--output", "runs/market_replay_demo"
) + $args
& $Python @python_args

Write-Host ""
Write-Host "Replay artifacts written to runs/market_replay_demo"
Write-Host "Read runs/market_replay_demo/summary.md and compare deterministic_replay_sha256 in run_manifest.json."
