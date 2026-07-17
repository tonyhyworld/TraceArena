 param([switch]$SkipFrontend)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "需要先安装 Python 3.10+" }
if (-not $SkipFrontend -and -not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "需要先安装 Node.js 18+" }

if (-not (Test-Path .venv)) { python -m venv .venv }
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -e ".[dev]"

if (-not $SkipFrontend) {
  npm ci --prefix frontend
  if (-not (Test-Path frontend\.env.local) -and (Test-Path frontend\.env.example)) {
    Copy-Item frontend\.env.example frontend\.env.local
  }
}
Write-Host "TraceArena 安装完成。详细启动方式见 frontend/README.md。"
