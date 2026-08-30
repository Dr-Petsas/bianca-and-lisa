# Start-Protokoll Bianca & Lisa: startet die eigenen Dienste und ueberwacht sie.
# Start / Neustart: Lisa 8095, Bianca 8096, Teststudio 8097, Test-Bianca 8098.
# Nur pruefen, nie starten/toeten: Clara, MAS, Lena, pickadoc-live-base, TTS/STT/LLM.
# WRITE_LIVE kommt aus .env - dieses Skript setzt ihn nicht.
param(
  [int]$IntervalSeconds = 8,
  [switch]$Once,
  [switch]$Status
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = $PSScriptRoot
$RunDir = Join-Path $Root ".run"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogFile = Join-Path $RunDir "wachter.log"
$StandFile = Join-Path $RunDir "wachter-stand.txt"
$PidFile = Join-Path $RunDir "wachter.pid"
$HbFile = Join-Path $RunDir "wachter.hb"

if (-not (Test-Path -LiteralPath $RunDir)) {
  [System.IO.Directory]::CreateDirectory($RunDir) | Out-Null
}

function Peek-Env([string]$name, [string]$default = "") {
  $p = Join-Path $Root ".env"
  if (-not (Test-Path -LiteralPath $p)) { return $default }
  $zeile = Get-Content -LiteralPath $p -Encoding UTF8 | Where-Object {
    $_ -match ("^\s*" + [regex]::Escape($name) + "\s*=")
  } | Select-Object -First 1
  if (-not $zeile) { return $default }
  $v = (($zeile -split "=", 2)[1]).Trim().Trim('"').Trim("'")
  if ($v) { return $v }
  return $default
}

function Log([string]$msg) {
  $line = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss") + "  " + $msg
  Write-Host $line
  try { Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8 } catch {}
}

function Beat {
  try { Set-Content -LiteralPath $HbFile -Value ((Get-Date).ToString("o")) -Encoding ASCII } catch {}
}

function Http-Ok([string]$url, [int]$timeoutSec = 3) {
  if (-not $url) { return $false }
  try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $timeoutSec
    return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
  } catch {
    return $false
  }
}

function Get-ListenPid([int]$Port) {
  try {
    $x = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
      Select-Object -First 1 -ExpandProperty OwningProcess
    if ($x) { return [int]$x }
  } catch {}
  foreach ($line in (netstat -ano 2>$null)) {
    if ($line -match (":$Port\s+") -and $line -match "(LISTENING|ABH\S*)\s+(\d+)\s*$") {
      return [int]$Matches[2]
    }
  }
  return $null
}

function Get-Cmd([int]$procId) {
  if (-not $procId) { return "" }
  try {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction Stop
    return [string]$p.CommandLine
  } catch { return "" }
}

function Test-Ours([int]$procId, [string]$needle) {
  $cmd = Get-Cmd $procId
  if (-not $cmd) { return $false }
  if ($cmd -match "clara|lena-voice|pickadoc-live|mas-2|8091|8092|8093|8094") { return $false }
  return ($cmd -match [regex]::Escape($needle))
}

function Stop-Ours([int]$procId, [int]$port, [string]$needle) {
  $ids = @()
  if ($procId) { $ids += $procId }
  $listen = Get-ListenPid $port
  if ($listen) { $ids += $listen }
  $ids = $ids | Select-Object -Unique
  foreach ($id in $ids) {
    if (-not (Test-Ours $id $needle)) {
      Log "lasse PID $id auf Port $port (nicht unser Dienst)"
      continue
    }
    try {
      Stop-Process -Id $id -Force -ErrorAction Stop
      Log "gestoppt PID $id ($needle :$port)"
    } catch {
      Log "stop fehlgeschlagen PID $id"
    }
  }
  Start-Sleep -Milliseconds 700
}

$Dienste = @(
  @{
    Name = "Lisa"
    Port = 8095
    Health = "http://127.0.0.1:8095/health"
    Needle = "lisa.server:app"
    Args = @("-m", "uvicorn", "lisa.server:app", "--host", "0.0.0.0", "--port", "8095")
  },
  @{
    Name = "Bianca"
    Port = 8096
    Health = "http://127.0.0.1:8096/health"
    Needle = "--port 8096"
    Args = @("-m", "uvicorn", "bianca.server:app", "--host", "0.0.0.0", "--port", "8096")
  },
  @{
    Name = "Studio"
    Port = 8097
    Health = "http://127.0.0.1:8097/api/katalog"
    Needle = "editor.py"
    Args = @((Join-Path $Root "tests\baukasten\editor.py"))
  },
  @{
    Name = "Test-Bianca"
    Port = 8098
    Health = "http://127.0.0.1:8098/health"
    Needle = "--port 8098"
    Args = @("-m", "uvicorn", "bianca.server:app", "--host", "127.0.0.1", "--port", "8098")
  }
)

$masUrl = (Peek-Env "MAS_URL" "http://127.0.0.1:4000").TrimEnd("/")
$llmBase = Peek-Env "LLM_BASE" "http://100.77.30.98:8000/v1"
$llmHealth = ($llmBase -replace "/v1$", "") + "/v1/models"
$ttsBase = (Peek-Env "TTS_BASE" "").TrimEnd("/")
$sttBase = (Peek-Env "STT_BASE" "").TrimEnd("/")
$Fremd = @(
  @{ Name = "MAS"; Health = "$masUrl/health" },
  @{ Name = "LLM"; Health = $llmHealth },
  @{ Name = "TTS"; Health = $(if ($ttsBase) { "$ttsBase/health" } else { "" }) },
  @{ Name = "STT"; Health = $(if ($sttBase) { "$sttBase/health" } else { "" }) }
)

$State = @{}
foreach ($d in $Dienste) {
  $State[$d.Name] = @{
    Pid = $null
    LastStart = [datetime]::MinValue
    Restarts = 0
    Ok = $false
  }
}

function Write-Stand([object[]]$zeilen) {
  $wl = Peek-Env "WRITE_LIVE" "?"
  $kopf = @(
    ("Start-Protokoll  " + (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")),
    ("WRITE_LIVE aus .env = " + $wl),
    ""
  )
  $text = ($kopf + $zeilen) -join [Environment]::NewLine
  try { Set-Content -LiteralPath $StandFile -Value $text -Encoding UTF8 } catch {}
  foreach ($z in $zeilen) { Write-Host $z }
}

function Start-Dienst($d) {
  $st = $State[$d.Name]
  $seit = (Get-Date) - $st.LastStart
  if ($st.LastStart -gt [datetime]::MinValue -and $seit.TotalSeconds -lt 20) {
    Log ($d.Name + ": Neustart-Pause")
    return
  }
  if ($st.Restarts -ge 8) {
    $st.LastStart = Get-Date
    $st.Restarts = 0
    Log ($d.Name + ": zu viele Neustarts, Pause")
    return
  }
  if (-not (Test-Path -LiteralPath $Python)) {
    Log ("ABBRUCH: Python fehlt: " + $Python)
    return
  }
  $env:PYTHONPATH = $Root
  $out = Join-Path $RunDir ($d.Name.ToLower() + ".out.log")
  $err = Join-Path $RunDir ($d.Name.ToLower() + ".err.log")
  try {
    $p = Start-Process -FilePath $Python -ArgumentList $d.Args -WorkingDirectory $Root -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
    $st.Pid = $p.Id
    $st.LastStart = Get-Date
    $st.Restarts++
    Log ($d.Name + ": gestartet PID " + $p.Id + " :" + $d.Port)
  } catch {
    Log ($d.Name + ": Start fehlgeschlagen")
  }
}

function Pflege-Dienst($d) {
  $st = $State[$d.Name]
  $listen = Get-ListenPid $d.Port
  $ok = Http-Ok $d.Health
  if ($ok) {
    $st.Ok = $true
    if ($listen) { $st.Pid = $listen }
    return "ok"
  }
  $st.Ok = $false
  if ($listen) {
    if (Test-Ours $listen $d.Needle) {
      Log ($d.Name + ": lauscht, Health tot - Neustart")
      Stop-Ours $st.Pid $d.Port $d.Needle
      Start-Dienst $d
      return "neustart"
    }
    Log ($d.Name + ": Port " + $d.Port + " fremd PID " + $listen + " - nicht anfassen")
    return "fremd"
  }
  Log ($d.Name + ": tot - starte")
  Start-Dienst $d
  return "start"
}

function Sammle-Stand {
  $zeilen = @()
  foreach ($d in $Dienste) {
    $st = $State[$d.Name]
    $listen = Get-ListenPid $d.Port
    $ok = Http-Ok $d.Health
    if ($ok) { $marke = "AN " } else { $marke = "AUS" }
    if ($listen) { $pidText = [string]$listen } else { $pidText = "-" }
    $zeilen += ("  {0,-12} :{1}  {2}  pid={3}" -f $d.Name, $d.Port, $marke, $pidText)
    $st.Ok = $ok
    if ($listen) { $st.Pid = $listen }
  }
  $zeilen += ""
  $zeilen += "Abhaengigkeiten (nur beobachten):"
  foreach ($f in $Fremd) {
    if (-not $f.Health) {
      $zeilen += ("  {0,-12} nicht gesetzt" -f $f.Name)
      continue
    }
    $ok = Http-Ok $f.Health 4
    if ($ok) { $marke = "AN " } else { $marke = "AUS" }
    $zeilen += ("  {0,-12} {1}  {2}" -f $f.Name, $marke, $f.Health)
  }
  $zeilen += ""
  $zeilen += "Nicht anfassen: Clara 8091-8094, MAS-Prozess, Lena, pickadoc-live-base."
  return $zeilen
}

if ($Status) {
  Write-Stand (Sammle-Stand)
  exit 0
}

if (-not (Test-Path -LiteralPath $Python)) {
  Write-Host "lege .venv an..."
  py -3 -m venv (Join-Path $Root ".venv")
  & $Python -m pip install -q -r (Join-Path $Root "requirements.txt")
}

$alt = $null
if (Test-Path -LiteralPath $PidFile) {
  try { $alt = [int](Get-Content -LiteralPath $PidFile -Raw) } catch { $alt = $null }
}
if ($alt -and $alt -ne $PID) {
  $lebt = Get-Process -Id $alt -ErrorAction SilentlyContinue
  if ($lebt) {
    Write-Host ("Waechter laeuft schon (PID " + $alt + "). Stand:")
    Write-Stand (Sammle-Stand)
    exit 0
  }
}
Set-Content -LiteralPath $PidFile -Value $PID -Encoding ASCII

$wl = Peek-Env "WRITE_LIVE" "?"
Log ("Start-Protokoll an WRITE_LIVE=" + $wl + " - eigene Dienste, kein Clara/MAS-Kill")
foreach ($d in $Dienste) { [void](Pflege-Dienst $d) }
Write-Stand (Sammle-Stand)

if ($Once) {
  Log "Once - kein Waechter-Loop"
  exit 0
}

Log ("Waechter-Loop alle " + $IntervalSeconds + " s")
while ($true) {
  Beat
  foreach ($d in $Dienste) { [void](Pflege-Dienst $d) }
  Write-Stand (Sammle-Stand)
  Start-Sleep -Seconds $IntervalSeconds
}
