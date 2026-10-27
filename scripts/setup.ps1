# Windows setup:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
Write-Host "== Crystal setup ==" -ForegroundColor Cyan
foreach ($t in @("node","npm")) { if (-not (Get-Command $t -ErrorAction SilentlyContinue)) { throw "$t not found. Install Node.js 20+ from nodejs.org" } }
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py -3" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { throw "Python 3.11+ not found" }
Write-Host "[1/3] npm install"; npm install
Write-Host "[2/3] Python virtual environment in backend\.venv"
if (-not (Test-Path "backend\.venv")) { Invoke-Expression "$py -m venv backend\.venv" }
& "backend\.venv\Scripts\python.exe" -m pip install --upgrade pip
Write-Host "[3/3] Python packages (torch is large; this takes a while)"
& "backend\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
Write-Host "`nDone. Next:  ollama pull phi ; ollama pull mistral ; hf auth login ; npm start" -ForegroundColor Green
