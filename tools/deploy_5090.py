"""Deployt TTS-Container UND App-Stack auf die 5090, sobald der SSH-Schluessel
dieses Rechners dort eingetragen ist (Chef traegt ihn per Remote-Sitzung ein).

Ablauf:
  1. Alle 3 min uebliche Benutzernamen per Key-Login probieren (BatchMode,
     keine Passwort-Prompts). Der Chef muss den Usernamen so nicht mal nennen.
  2. Bei Erfolg: tts_serve-5090.zip nach ~/telefonki/tts_serve entpacken
     (python3 -m zipfile — unzip koennte fehlen) und
     `docker compose --profile chatterbox up -d --build` starten.
  3. App-Stack (der stabile Umschlag fuer SIP/Zaluma): app-5090.zip nach
     ~/telefonki/app, .env vor Ort erzeugen (Key aus MAS-.env gelesen,
     TTS_BASE auf den Chatterbox-Container) und `docker compose up -d --build`
     — Lisa 8095 + Bianca 8096 laufen dann AUF der 5090.
  4. Umschalten der LOKALEN Lisa/Bianca + SMS an den Chef erledigt der
     bereits laufende tools/tts_umschalter.py, sobald der Container warm ist.

Start:  .venv\\Scripts\\python tools\\deploy_5090.py
Log:    .run/tts-umschalt/deploy.log
"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "100.77.30.98"
USER_KANDIDATEN = ("root", "pickadoc", "pickadoc1", "ubuntu", "admin", "anmeldung2", "petsas", "kirri")
ZIP = ROOT / "tts_serve-5090.zip"
APP_ZIP = ROOT / "app-5090.zip"
MAS_ENV = Path(r"F:\MAS-2\backend\.env")
POLL_S = 180
MAX_WARTEN_S = 24 * 3600
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=accept-new"]

LOG_DIR = ROOT / ".run" / "tts-umschalt"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG = LOG_DIR / "deploy.log"


def log(msg: str) -> None:
    zeile = f"{datetime.now():%H:%M:%S} {msg}"
    print(zeile, flush=True)
    with _LOG.open("a", encoding="utf-8") as f:
        f.write(zeile + "\n")


def ssh(user: str, cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", *SSH_OPTS, f"{user}@{HOST}", cmd],
        capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
    )


def scp(lokal: Path, ziel: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["scp", *SSH_OPTS, str(lokal), ziel],
        capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
    )


def _peek(name: str) -> str:
    try:
        for line in MAS_ENV.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if raw.startswith(f"{name}="):
                return raw.partition("=")[2].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def user_finden() -> str:
    for user in USER_KANDIDATEN:
        try:
            r = ssh(user, "echo zugang-ok && hostname", timeout=15)
        except subprocess.TimeoutExpired:
            continue
        if r.returncode == 0 and "zugang-ok" in (r.stdout or ""):
            log(f"Zugang als {user}@{HOST} ({(r.stdout or '').strip().splitlines()[-1]})")
            return user
    return ""


def compose_finden(user: str) -> str:
    # docker compose (neu) zuerst, docker-compose (alt) als zweiter Versuch;
    # falls der User nicht in der docker-Gruppe ist, jeweils mit sudo -n.
    for compose in ("docker compose", "docker-compose", "sudo -n docker compose", "sudo -n docker-compose"):
        probe = ssh(user, f"{compose} version", timeout=30)
        if probe.returncode == 0:
            return compose
    return ""


def deploy_tts(user: str, compose: str) -> bool:
    ziel = f"{user}@{HOST}"
    log(f"kopiere {ZIP.name} ({ZIP.stat().st_size // 1024} KB) nach {ziel}:/tmp/")
    r = scp(ZIP, f"{ziel}:/tmp/tts_serve-5090.zip")
    if r.returncode != 0:
        log(f"DEPLOY_FEHLER scp: {r.stderr[:400]}")
        return False

    r = ssh(user, "mkdir -p ~/telefonki/tts_serve && cd ~/telefonki/tts_serve && "
                  "python3 -m zipfile -e /tmp/tts_serve-5090.zip . && ls", timeout=60)
    if r.returncode != 0:
        log(f"DEPLOY_FEHLER entpacken: {r.stderr[:400]}")
        return False
    log(f"entpackt: {' '.join((r.stdout or '').split())}")

    log("baue + starte Chatterbox (kann 10-20 min dauern: Image-Build + Modell-Download) ...")
    r = ssh(user, f"cd ~/telefonki/tts_serve && {compose} --profile chatterbox up -d --build 2>&1 | tail -n 30",
            timeout=2400)
    log((r.stdout or "").strip()[-1500:] or "(keine Ausgabe)")
    if r.returncode != 0:
        log(f"DEPLOY_FEHLER compose: rc={r.returncode} {(r.stderr or '')[:400]}")
        return False

    r = ssh(user, f"cd ~/telefonki/tts_serve && {compose} --profile chatterbox ps", timeout=30)
    log((r.stdout or "").strip())
    log("DEPLOY_OK: TTS-Container gestartet — tts_umschalter uebernimmt (Warmlauf laeuft).")
    return True


def deploy_app(user: str, compose: str) -> bool:
    """Lisa+Bianca als Container auf der 5090 — der Umschlag fuer SIP/Zaluma."""
    ziel = f"{user}@{HOST}"
    log(f"kopiere {APP_ZIP.name} ({APP_ZIP.stat().st_size // 1024} KB) nach {ziel}:/tmp/")
    r = scp(APP_ZIP, f"{ziel}:/tmp/app-5090.zip")
    if r.returncode != 0:
        log(f"APP_FEHLER scp: {r.stderr[:400]}")
        return False
    r = ssh(user, "mkdir -p ~/telefonki/app && cd ~/telefonki/app && "
                  "python3 -m zipfile -e /tmp/app-5090.zip . && ls", timeout=60)
    if r.returncode != 0:
        log(f"APP_FEHLER entpacken: {r.stderr[:400]}")
        return False

    # .env vor Ort erzeugen: Secrets reisen nur per scp, nie durchs Git.
    key = _peek("ELEVENLABS_API_KEY")
    if not key:
        log("APP_FEHLER: ELEVENLABS_API_KEY nicht in MAS-.env gefunden (STT braucht ihn)")
        return False
    env_text = (
        "# 5090-App — vom Deploy-Waechter erzeugt\n"
        "WRITE_LIVE=1\n"
        "DEFAULT_TENANT=meddent\n"
        "LLM_BASE=http://host.docker.internal:8000/v1\n"
        "TTS_BASE=http://host.docker.internal:8210\n"
        f"ELEVENLABS_API_KEY={key}\n"
    )
    tmp_env = LOG_DIR / "app.env"
    tmp_env.write_text(env_text, encoding="utf-8")
    try:
        r = scp(tmp_env, f"{ziel}:~/telefonki/app/.env", timeout=60)
    finally:
        tmp_env.unlink(missing_ok=True)
    if r.returncode != 0:
        log(f"APP_FEHLER .env: {r.stderr[:400]}")
        return False

    log("baue + starte App-Container (Lisa 8095, Bianca 8096) ...")
    r = ssh(user, f"cd ~/telefonki/app && {compose} up -d --build 2>&1 | tail -n 25", timeout=1200)
    log((r.stdout or "").strip()[-1200:] or "(keine Ausgabe)")
    if r.returncode != 0:
        log(f"APP_FEHLER compose: rc={r.returncode} {(r.stderr or '')[:400]}")
        return False

    for port in (8095, 8096):
        url = f"http://127.0.0.1:{port}/health"
        r = ssh(user, "for i in 1 2 3 4 5 6 7 8 9 10; do "
                      f"(curl -s -m 3 {url} 2>/dev/null || wget -qO- -T 3 {url} 2>/dev/null) "
                      "&& break; sleep 3; done", timeout=90)
        kurz = " ".join((r.stdout or "").split())[:220]
        log(f"app health {port}: {kurz or 'KEINE ANTWORT'}")
        if not kurz:
            log(f"APP_FEHLER: Dienst auf {port} antwortet nicht")
            return False
    log("APP_OK: Lisa+Bianca laufen als Container auf der 5090.")
    return True


def deploy(user: str) -> bool:
    compose = compose_finden(user)
    if not compose:
        log("DEPLOY_FEHLER: kein lauffaehiges docker compose gefunden")
        return False
    log(f"nutze: {compose}")
    ok_tts = deploy_tts(user, compose)
    # App-Stack auch bei TTS-Problemen versuchen — der SIP-Kollege haengt nur
    # am HTTP-Umschlag; ohne TTS-Container spricht die 5090-App eben noch nicht.
    deploy_app(user, compose)
    return ok_tts


def main() -> int:
    if not ZIP.is_file():
        log("DEPLOY_FEHLER: tts_serve-5090.zip fehlt")
        return 1
    if not APP_ZIP.is_file():
        log("DEPLOY_FEHLER: app-5090.zip fehlt (git archive -o app-5090.zip HEAD)")
        return 1
    log(f"warte auf SSH-Zugang zu {HOST} (Schluessel muss dort eingetragen werden)")
    t0 = time.time()
    n = 0
    while True:
        user = user_finden()
        if user:
            return 0 if deploy(user) else 1
        n += 1
        if n % 5 == 1:
            log(f"noch kein Zugang (Runde {n})")
        if time.time() - t0 > MAX_WARTEN_S:
            log("DEPLOY_FEHLER: Frist abgelaufen — Schluessel wurde nie eingetragen.")
            return 1
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
