# Bianca Telefon-KI (eingehend) — nur dieser Ordner, nur Port 8096.
# Startet KEINE fremden Worker und beendet KEINE Clara/Demo/Lisa-Prozesse.
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath ".\.venv\Scripts\python.exe")) {
    Write-Host "lege .venv an..."
    py -3 -m venv .venv
}
& ".\.venv\Scripts\python.exe" -m pip install -q -r requirements.txt
$env:PYTHONPATH = $PSScriptRoot
Write-Host "Bianca auf http://127.0.0.1:8096  (Lisa 8095 und Clara/Demo bleiben unangetastet)"
& ".\.venv\Scripts\python.exe" -m uvicorn bianca.server:app --host 0.0.0.0 --port 8096
