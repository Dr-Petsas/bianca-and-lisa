"""Wartet auf den Chatterbox-Container der 5090, schaltet Lisa+Bianca auf
lokales TTS um und meldet den Vollzug per SMS an den Chef (01776004600).

Ablauf (Chef 27.08.2026: "SMS wenn Bianca und Lisa mit Chatterbox verbunden
sind und ich ohne ElevenLabs testen kann"):
  1. Poll http://100.77.30.98:8210/health bis ok+warm mit bianca+lisa.
  2. Probe /speak fuer BEIDE Stimmen (deutsches PCM, plausible Laenge).
  3. .env: TTS_BASE setzen -> ab jetzt spricht NUR der Container (kein
     ElevenLabs-Rueckfall, kern/tts.py).
  4. Lisa (8095) + Bianca (8096) neu starten, warten bis /health kommt.
  5. Beweis "ohne ElevenLabs": health zeigt tts=lokal UND alle Fueller sind
     beim Start uebers LOKALE TTS gerendert worden (filler voll).
  6. Erfolgs-SMS via Twilio (Zugang aus F:\\MAS-2\\backend\\.env gelesen —
     dasselbe Peek-Muster wie kern/config.py; MAS bleibt unangetastet).
  Scheitert 5. nach der Umschaltung, wird auf ElevenLabs zurueckgerollt und
  eine Fehler-SMS geschickt — der Chef soll nicht vergeblich testen.

Start:  .venv\\Scripts\\python tools\\tts_umschalter.py
Log:    .run/tts-umschalt/wachter.log (+ je Dienst ein Startlog)
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHATTERBOX = "http://100.77.30.98:8210"
CHEF_NUMMER = "+491776004600"
MAS_ENV = Path(r"F:\MAS-2\backend\.env")
ENV_PFAD = ROOT / ".env"
LOG_DIR = ROOT / ".run" / "tts-umschalt"
POLL_S = 60
MAX_WARTEN_S = 24 * 3600
DIENSTE = (
    ("lisa", 8095, "start.ps1"),
    ("bianca", 8096, "start-bianca.ps1"),
)

LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG = LOG_DIR / "wachter.log"


def log(msg: str) -> None:
    zeile = f"{datetime.now():%H:%M:%S} {msg}"
    print(zeile, flush=True)
    with _LOG.open("a", encoding="utf-8") as f:
        f.write(zeile + "\n")


def _peek(name: str) -> str:
    for line in MAS_ENV.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if raw.startswith(f"{name}="):
            return raw.partition("=")[2].strip().strip('"').strip("'")
    return ""


def sms(text: str) -> bool:
    sid, token, sender = _peek("TWILIO_ACCOUNT_SID"), _peek("TWILIO_AUTH_TOKEN"), _peek("LISA_SMS_SENDER")
    if not (sid and token and sender):
        log("SMS unmoeglich: Twilio-Zugang fehlt in MAS-.env")
        return False
    r = httpx.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        auth=(sid, token),
        data={"To": CHEF_NUMMER, "From": sender, "Body": text[:640]},
        timeout=20.0,
    )
    ok = r.status_code in (200, 201)
    log(f"SMS an {CHEF_NUMMER}: http {r.status_code}" + ("" if ok else f" {r.text[:200]}"))
    return ok


def container_bereit() -> bool:
    try:
        r = httpx.get(f"{CHATTERBOX}/health", timeout=5.0)
        if r.status_code != 200:
            return False
        h = r.json()
        stimmen = {s.lower() for s in (h.get("voices") or [])}
        return bool(h.get("ok")) and bool(h.get("warm")) and {"bianca", "lisa"} <= stimmen
    except Exception:
        return False


def probe_speak(voice: str) -> bool:
    try:
        r = httpx.post(
            f"{CHATTERBOX}/speak",
            json={"text": "Guten Tag, hier spricht die Umschalt-Probe. Passt alles?", "voice": voice},
            timeout=60.0,
        )
        # kurzer Satz => deutlich ueber 0,5 s Audio (24 kHz PCM16 = 48 kB/s)
        ok = r.status_code == 200 and len(r.content) > 24000
        log(f"probe {voice}: http {r.status_code}, {len(r.content)} bytes -> {'ok' if ok else 'ZU WENIG'}")
        return ok
    except Exception as e:
        log(f"probe {voice}: FEHLER {e}")
        return False


def env_setzen(base: str) -> None:
    zeilen = ENV_PFAD.read_text(encoding="utf-8").splitlines() if ENV_PFAD.is_file() else []
    neu = f"TTS_BASE={base}"
    for i, z in enumerate(zeilen):
        if re.match(r"^\s*(#\s*)?TTS_BASE=", z):
            zeilen[i] = neu
            break
    else:
        zeilen.append(neu)
    ENV_PFAD.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    log(f".env: {neu}")


def dienst_neustart(name: str, port: int, skript: str) -> None:
    kill = (
        f"$p = (Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue "
        f"| Select-Object -First 1 -ExpandProperty OwningProcess); "
        f"if ($p) {{ Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }}"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", kill], capture_output=True, timeout=30)
    time.sleep(2)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = (LOG_DIR / f"{name}-{stamp}.log").open("w", encoding="utf-8", errors="replace")
    err = (LOG_DIR / f"{name}-{stamp}.err.log").open("w", encoding="utf-8", errors="replace")
    # Streams getrennt lassen (AGENTS: gemergte Streams erschlagen den Start).
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / skript)],
        cwd=str(ROOT), stdout=out, stderr=err,
    )
    log(f"{name}: neu gestartet ({skript})")


def dienst_health(port: int, versuche: int = 60) -> dict:
    for _ in range(versuche):
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=3.0)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(2)
    return {}


def filler_voll(h: dict) -> bool:
    """Fueller werden beim Start durch die AKTIVE Engine gerendert — voll =
    das lokale TTS hat wirklich gesprochen (Lisa: '18/18', Bianca: 18)."""
    f = h.get("filler")
    if isinstance(f, str):
        teile = f.split("/")
        return len(teile) == 2 and teile[0] == teile[1] and teile[0] != "0"
    return isinstance(f, int) and f > 0


def umschalten() -> tuple[bool, str]:
    env_setzen(CHATTERBOX)
    for name, port, skript in DIENSTE:
        dienst_neustart(name, port, skript)
    # Fueller-Rendern (18 Saetze x ~1 s Synthese) braucht nach dem /health-Start
    # noch einen Moment — erst health abwarten, dann auf volle Fueller pollen.
    for name, port, _ in DIENSTE:
        h = dienst_health(port)
        if not h:
            return False, f"{name}: /health antwortet nicht"
        if h.get("tts") != "lokal":
            return False, f"{name}: tts={h.get('tts')!r} statt 'lokal'"
    for _ in range(90):  # bis ~3 min fuer beide Filler-Saetze-Laeufe
        staende = [(name, dienst_health(port, versuche=1)) for name, port, _ in DIENSTE]
        if all(filler_voll(h) for _, h in staende):
            log("beide Dienste: tts=lokal, alle Fueller lokal gerendert")
            return True, ""
        time.sleep(2)
    fehlend = ", ".join(f"{name}={h.get('filler')!r}" for name, h in staende if not filler_voll(h))
    return False, f"Fueller nicht vollstaendig lokal gerendert ({fehlend})"


def zurueckrollen() -> None:
    log("ROLLBACK auf ElevenLabs")
    env_setzen("")
    for name, port, skript in DIENSTE:
        dienst_neustart(name, port, skript)
    for name, port, _ in DIENSTE:
        h = dienst_health(port)
        log(f"{name}: nach Rollback tts={h.get('tts')!r}")


def main() -> int:
    log(f"warte auf Chatterbox unter {CHATTERBOX} (Poll {POLL_S}s, max. {MAX_WARTEN_S // 3600}h)")
    t0 = time.time()
    n = 0
    while not container_bereit():
        n += 1
        if n % 10 == 1:
            log(f"noch nicht da (Versuch {n})")
        if time.time() - t0 > MAX_WARTEN_S:
            log("WAECHTER_FEHLER: Frist abgelaufen, Container kam nie hoch — keine SMS.")
            return 1
        time.sleep(POLL_S)
    log("Container ist da und warm — Probe beider Stimmen")

    if not (probe_speak("bianca") and probe_speak("lisa")):
        log("WAECHTER_FEHLER: /speak-Probe fehlgeschlagen — NICHT umgeschaltet, keine SMS.")
        return 1

    ok, grund = umschalten()
    if ok:
        sms(
            "Chatterbox laeuft: Lisa und Bianca sprechen jetzt LOKAL von der 5090 "
            "(deutsch), ElevenLabs ist AUS - kein Rueckfall. Testen im Dock: "
            "Lisa 8095, Bianca 8096. Wenn was klemmt: TTS_BASE in der .env "
            "leeren und neu starten."
        )
        log("SMS_GESENDET: Umschaltung fertig.")
        return 0

    log(f"WAECHTER_FEHLER nach Umschaltung: {grund}")
    zurueckrollen()
    sms(
        f"Chatterbox-Umschaltung FEHLGESCHLAGEN ({grund}). Ich habe auf "
        "ElevenLabs zurueckgerollt - Lisa/Bianca laufen normal weiter. "
        "Details: .run/tts-umschalt/wachter.log"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
