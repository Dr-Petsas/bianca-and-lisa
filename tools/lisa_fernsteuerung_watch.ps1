# Lisa-Draht: nur Grok, nur F:\Bianca&Lisa TelefonKI, nur Port 8095.
# Nicht starten: MAS-Waechter, Clara, DemoClara, Lena.
param(
  [string]$LisaBase = "http://127.0.0.1:8095",
  [string]$Workspace = "F:\Bianca&Lisa TelefonKI",
  [string]$Model = "cursor-grok-4.6-high-fast",
  [int]$IntervalSeconds = 6,
  [int]$AgentTimeoutMin = 20,
  [int]$OrphanMaxAgeMin = 30
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$CursorAgent = "C:\Users\Anmeldung2\AppData\Local\cursor-agent\cursor-agent.cmd"
$RunDir = Join-Path $Workspace ".run"
$SessionFile = Join-Path $RunDir "lisa_draht_session.txt"
$LogFile = Join-Path $RunDir "lisa_draht_watch.log"
$HeartbeatFile = Join-Path $RunDir "lisa_draht_watch.hb"
$AuthFile = Join-Path $RunDir "lisa_draht_auth_block.txt"
$TokenFile = Join-Path $Workspace ".data\remote_token.txt"

if (-not (Test-Path -LiteralPath $RunDir)) {
  [System.IO.Directory]::CreateDirectory($RunDir) | Out-Null
}

function Peek-EnvLine([string]$path, [string]$name) {
  if (-not (Test-Path -LiteralPath $path)) { return "" }
  $zeile = Get-Content -LiteralPath $path | Where-Object { $_ -match ("^" + [regex]::Escape($name) + "=") } | Select-Object -First 1
  if (-not $zeile) { return "" }
  return (($zeile -split "=", 2)[1]).Trim().Trim('"').Trim("'")
}

$Token = ""
if (Test-Path -LiteralPath $TokenFile) {
  $Token = (Get-Content -LiteralPath $TokenFile -Raw).Trim()
}

if (-not $env:CURSOR_API_KEY) {
  foreach ($quelle in @(
      (Join-Path $Workspace ".env"),
      "F:\MAS-2\backend\.env"
    )) {
    foreach ($name in @("CURSOR_API_KEY", "CURSOR_AGENT_API_KEY")) {
      $wert = Peek-EnvLine $quelle $name
      if ($wert) { $env:CURSOR_API_KEY = $wert; break }
    }
    if ($env:CURSOR_API_KEY) { break }
  }
}

if (-not (Test-Path -LiteralPath $CursorAgent)) {
  Write-Host "ABBRUCH: cursor-agent fehlt ($CursorAgent)"
  exit 1
}

function Beat() {
  try { Set-Content -LiteralPath $HeartbeatFile -Value ((Get-Date).ToString("o")) -Encoding ASCII -NoNewline } catch {}
}

function Log([string]$msg) {
  $line = ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss") + "  " + $msg)
  Write-Host $line
  Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

function Api-Get([string]$path) {
  $join = if ($path.Contains("?")) { "&" } else { "?" }
  $uri = $LisaBase + $path
  if ($Token) { $uri = $uri + $join + "token=" + [uri]::EscapeDataString($Token) }
  return Invoke-RestMethod -Uri $uri -TimeoutSec 20
}

function Api-Post([string]$path, [hashtable]$body) {
  if ($Token) { $body["token"] = $Token }
  return Invoke-RestMethod -Uri ($LisaBase + $path) -Method Post -ContentType "application/json; charset=utf-8" -Body ($body | ConvertTo-Json -Depth 6) -TimeoutSec 20
}

function Say([string]$text) {
  $rumpf = "[Grok]`n" + [string]$text
  try { Api-Post "/remote/message" @{ role = "agent"; text = $rumpf; speaker = "grok" } | Out-Null }
  catch { Log ("FEHLER beim Zurueckschreiben: " + $_.Exception.Message) }
}

function Get-Session() {
  if (Test-Path -LiteralPath $SessionFile) { return (Get-Content -LiteralPath $SessionFile -Raw).Trim() }
  return ""
}
function Set-Session([string]$id) {
  if ($id) { Set-Content -LiteralPath $SessionFile -Value $id -Encoding ASCII -NoNewline }
}

function Build-Prompt([string]$userText) {
  return @"
[SYSTEM] Du bist Grok. Du arbeitest AUSSCHLIESSLICH im Ordner F:\Bianca&Lisa TelefonKI (Lisa Telefon-KI).

HARTE GRENZEN:
- Du darfst Clara-Voice, Clara live (8091), Clara-dev (8093), DemoClara (8094), MAS-2, Lena-Voice und pickadoc-live-base NICHT oeffnen, aendern, neu starten oder deren Ports anfassen.
- Lisa laeuft nur auf Port 8095. WRITE_LIVE bleibt 0, solange der Chef das nicht ausdruecklich verlangt.
- Kein git push, kein --force, keine fremden .env Dateien schreiben.
- Kein move_agent_to_root / Workspace-Wechsel. Dieser Chat bleibt in diesem Ordner.

AUFTRAG VOM HANDY (Dr. Petsas):
$userText

Antworte AUSSCHLIESSLICH auf Deutsch, 2 bis 6 Saetze, ohne Code-Bloecke und ohne Tool-Namen. Sag was du wirklich geaendert oder geprueft hast.
"@
}

function Test-AuthError([string]$t) {
  if (-not $t) { return $false }
  return ($t -match "(?i)(authentication required|agent login|CURSOR_API_KEY|not (logged|signed) in|unauthorized|401)")
}

function Run-Agent([string]$prompt, [string]$sessionId) {
  $outFile = Join-Path $RunDir ("agent-out-{0}.json" -f ([guid]::NewGuid().ToString("N").Substring(0, 8)))
  $errFile = "$outFile.err"
  $inFile = "$outFile.in"
  $agentArgs = @(
    "-p", "--output-format", "json", "--force", "--trust",
    "--workspace", $Workspace,
    "--model", $Model
  )
  if ($sessionId) { $agentArgs += @("--resume", $sessionId) }
  try {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($inFile, $prompt, $enc)
    $p = Start-Process -FilePath $CursorAgent -ArgumentList $agentArgs `
      -RedirectStandardInput $inFile -RedirectStandardOutput $outFile -RedirectStandardError $errFile `
      -NoNewWindow -PassThru
    $deadline = (Get-Date).AddMinutes($AgentTimeoutMin)
    while (-not $p.HasExited) {
      Beat
      Start-Sleep -Seconds 4
      if ((Get-Date) -gt $deadline) {
        try { Start-Process taskkill -ArgumentList "/PID", $p.Id, "/T", "/F" -NoNewWindow -Wait -ErrorAction SilentlyContinue } catch {}
        Start-Sleep -Seconds 1
        Remove-Item $inFile, $outFile, $errFile -ErrorAction SilentlyContinue
        return @{ ok = $false; session = $sessionId; text = "Diese Aufgabe hat laenger als $AgentTimeoutMin Minuten gebraucht und wurde abgebrochen." }
      }
    }
    $raw = (Get-Content $outFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue)
    $err = (Get-Content $errFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue)
    Remove-Item $inFile, $outFile, $errFile -ErrorAction SilentlyContinue
    if (-not $raw) { return @{ ok = $false; text = ("(keine Ausgabe vom Agenten) " + $err); session = $sessionId } }
    $jsonLine = ($raw -split "`n" | Where-Object { $_.Trim() -like "{*}" } | Select-Object -Last 1)
    if (-not $jsonLine) { return @{ ok = $false; text = ("Unerwartete Agent-Ausgabe"); session = $sessionId } }
    $obj = $jsonLine | ConvertFrom-Json
    $text = if ($obj.result) { [string]$obj.result } else { "(leere Antwort)" }
    $sid = if ($obj.session_id) { [string]$obj.session_id } else { $sessionId }
    $isErr = ($obj.is_error -eq $true)
    return @{ ok = (-not $isErr); text = $text; session = $sid }
  } catch {
    Remove-Item $inFile, $outFile, $errFile -ErrorAction SilentlyContinue
    return @{ ok = $false; text = ("Agent-Fehler: " + $_.Exception.Message); session = $sessionId }
  }
}

function Requeue-Orphans() {
  try {
    $st = Api-Get "/remote/state?limit=200"
    $orphans = @($st.messages | Where-Object { $_.role -eq "user" -and $_.status -eq "in_arbeit" })
    $now = [double](([DateTimeOffset](Get-Date)).ToUnixTimeMilliseconds())
    $fresh = @($orphans | Where-Object { ($now - [double]($_.createdAt)) -le ($OrphanMaxAgeMin * 60000) })
    $stale = @($orphans | Where-Object { ($now - [double]($_.createdAt)) -gt ($OrphanMaxAgeMin * 60000) })
    if ($fresh.Count -gt 0) {
      Api-Post "/remote/ack" @{ ids = @($fresh | ForEach-Object { [string]$_.id }); status = "neu" } | Out-Null
    }
    if ($stale.Count -gt 0) {
      Api-Post "/remote/ack" @{ ids = @($stale | ForEach-Object { [string]$_.id }); status = "fertig" } | Out-Null
    }
  } catch { Log ("Waisen-Pruefung: " + $_.Exception.Message) }
}

Beat
Log "Lisa-Draht gestartet. Base=$LisaBase Workspace=$Workspace Modell=$Model"
Requeue-Orphans
try {
  Api-Post "/remote/board" @{ text = ("Lisa-Draht online seit " + (Get-Date).ToString("HH:mm") + " - nur Grok, nur dieses Projekt.") } | Out-Null
} catch { Log ("Board-Start: " + $_.Exception.Message) }

while ($true) {
  Beat
  try {
    $pending = Api-Get "/remote/pending"
    foreach ($m in @($pending.messages)) {
      $id = [string]$m.id
      $text = [string]$m.text
      if (-not $id -or -not $text) { continue }
      Log ("Neue Nachricht " + $id + ": " + $text.Substring(0, [Math]::Min(80, $text.Length)))
      try { Api-Post "/remote/ack" @{ ids = @($id); status = "in_arbeit" } | Out-Null } catch {}
      try { Api-Post "/remote/board" @{ text = ("Grok arbeitet seit " + (Get-Date).ToString("HH:mm") + ":`n" + $text.Substring(0, [Math]::Min(200, $text.Length))) } | Out-Null } catch {}

      $res = Run-Agent (Build-Prompt $text) (Get-Session)
      if ($res.session) { Set-Session $res.session }

      if ((-not $res.ok) -and (Test-AuthError $res.text)) {
        try { Set-Content -LiteralPath $AuthFile -Value ((Get-Date).ToString("o")) -Encoding ASCII } catch {}
        try { Api-Post "/remote/ack" @{ ids = @($id); status = "neu" } | Out-Null } catch {}
        Say "Ich habe die Nachricht, kann sie aber nicht bearbeiten: dem Hintergrund-Agenten fehlt der Zugangsschluessel. Nachricht bleibt liegen."
        try { Api-Post "/remote/board" @{ text = "ANMELDUNG FEHLT: CURSOR_API_KEY. Nachricht bleibt liegen." } | Out-Null } catch {}
        Log "ANMELDUNG FEHLT - Nachricht bleibt liegen"
        break
      }

      $reply = [string]$res.text
      if (-not $reply.Trim()) { $reply = "(keine Textantwort)" }
      Say $reply
      try { Api-Post "/remote/ack" @{ ids = @($id); status = "fertig" } | Out-Null } catch {}
      try { Api-Post "/remote/board" @{ text = ("Zuletzt " + (Get-Date).ToString("HH:mm") + " (Grok)`n" + $reply.Substring(0, [Math]::Min(280, $reply.Length))) } | Out-Null } catch {}
      Log ("Beantwortet " + $id + " ok=" + $res.ok)
    }
  } catch {
    Log ("Schleifen-Fehler: " + $_.Exception.Message)
  }
  Start-Sleep -Seconds $IntervalSeconds
}
