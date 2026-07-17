$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .venv\Scripts\python.exe)) { throw "请先运行 .\scripts\install.ps1" }
if (-not (Test-Path frontend\node_modules\.bin\vite.cmd)) { throw "请先运行 .\scripts\install.ps1" }
if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }

$env:AIWORLD_CONFIG = "./framework.public.yaml"
$env:PYTHONPATH = "."
$backend = Start-Process -PassThru -NoNewWindow -WorkingDirectory backend `
  -FilePath "..\.venv\Scripts\python.exe" `
  -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8001"
$frontend = Start-Process -PassThru -NoNewWindow -WorkingDirectory frontend `
  -FilePath "node_modules\.bin\vite.cmd" -ArgumentList "--host 127.0.0.1"
Write-Host "AI World OS: http://127.0.0.1:8001"
Write-Host "完整前端: http://127.0.0.1:5173"
Write-Host "创建账号：cd backend; ..\.venv\Scripts\python.exe scripts\create_user.py"
try { Wait-Process -Id $backend.Id, $frontend.Id } finally {
  Stop-Process -Id $backend.Id, $frontend.Id -ErrorAction SilentlyContinue
}
