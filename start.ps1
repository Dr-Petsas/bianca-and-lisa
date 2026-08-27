# Lisa Telefon-KI — nur dieser Ordner, nur Port 8095.
# Startet KEINE fremden Worker und beendet KEINE Clara/Demo-Prozesse.
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath ".\.venv\Scripts\python.exe")) {
    Write-Host "lege .venv an..."
    py -3 -m venv .venv
}
& ".\.venv\Scripts\python.exe" -m pip install -q -r requirements.txt
$env:PYTHONPATH = $PSScriptRoot
Write-Host "Lisa auf http://127.0.0.1:8095  (Clara/Demo bleiben unangetastet)"
& ".\.venv\Scripts\python.exe" -m uvicorn lisa.server:app --host 0.0.0.0 --port 8095
