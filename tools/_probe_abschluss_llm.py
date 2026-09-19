"""Abschluss-Probe: traegt der Kern MIT echtem LLM bis zum Schreibvorgang?

Warum diese Probe ueberhaupt gebraucht wird
-------------------------------------------
Das Anruf-Replay (``tools/kern_audit.py``) spielt historische Anrufersaetze
gegen den Kern. Sobald der Kern eine ANDERE Frage stellt als die Live-Bianca
damals, passt die naechste historische Antwort nicht mehr auf die gestellte
Frage (off-policy). Schleifen-, Absturz- und Stille-Zahlen sind dadurch sogar
haerter als echt - Abschluss- und Buchungsquoten aber NICHT messbar: auf
"Soll ich das so eintragen?" kam im Korpus nie ein Ja, weil der Anrufer damals
auf etwas anderes geantwortet hat.

Diese Probe schliesst genau diese Luecke: ein Anrufer-Bot antwortet auf die
Frage, die der Kern WIRKLICH gestellt hat. Verstanden wird mit dem echten
LLM (ueber ``hirn.deuten``), geschrieben wird gegen ``ToolGatewaySim`` -
kein echter Kalender, keine SMS, kein Mandanten-Schreibweg.

Aufruf:
    python tools/_probe_abschluss_llm.py --llm-base http://127.0.0.1:18000/v1
    python tools/_probe_abschluss_llm.py --ohne-llm   # regelbasiert zum Vergleich
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bianca.controller import policy as policy_mod  # noqa: E402
from bianca.controller.gateway_sim import Szenario  # noqa: E402
from bianca.controller.orchestrator import TestGespraech  # noqa: E402

_MAX_ZUEGE = 24


# --------------------------------------------------------------------------- #
# Der Anrufer-Bot: antwortet auf die Frage, die wirklich gestellt wurde.
# Bewusst KEINE feste Zugliste - sonst messen wir wieder off-policy.
# --------------------------------------------------------------------------- #
def _antwort(frage: str, satz: str, ziel: dict[str, str]) -> str:
    f = (frage or "").strip()
    fest = {
        "schonmal": "Ja, ich war schon bei Ihnen.",
        "nachname": ziel["nachname"] + ".",
        "vorname": ziel["vorname"] + ".",
        "besuchsgrund": ziel["grund"] + ".",
        "behandler": "Das ist mir egal.",
        "wunschzeit": "Naechste Woche vormittags waere gut.",
        "versicherung": "Gesetzlich.",
        "telefon": "Meine Nummer ist 0176 60893095.",
        "fuer_wen": "Fuer mich selbst.",
        "auswahl": "Der erste.",
        "terminwahl": "Der erste passt.",
        "aenderung": "Nein, alles richtig.",
        "sonst_noch": "Nein, danke, das war alles.",
        "rueckruf_ja": "Nein, danke.",
        "absage_grund": "Ich bin im Urlaub.",
        "anzahl": "Nur den einen.",
        "uebertragen": "Nein.",
        "suche_weiter": "Ja, bitte schauen Sie weiter.",
        "auskunft_art": "Wann der Termin ist.",
        "termin_hinweis": "Der im Oktober.",
    }
    if f in fest:
        return fest[f]

    # Keine registrierte Frage: am Satz entscheiden (Rueckfrage/Rueecklesen/Angebot).
    s = (satz or "").lower()
    if "soll ich" in s or "stimmt das" in s or "richtig?" in s or "eintragen" in s:
        return "Ja, genau so."
    if "anbieten" in s or "ich habe 1." in s or "1." in s and "uhr" in s:
        return "Der erste passt mir."
    if "?" in s:
        return "Ja."
    return ziel["wunsch"]


def _lauf(name: str, ziel: dict[str, str], sz: Szenario, llm, pol) -> dict:
    g = TestGespraech(pol, sz, llm=llm)
    letzte = ""
    print(f"\n{'=' * 72}\n {name}\n{'=' * 72}")
    zug = ziel["wunsch"]
    for i in range(_MAX_ZUEGE):
        a = g.eingabe(zug)
        dbg = a.debug or {}
        akt = str(dbg.get("speak_akt") or "")
        frage = str(dbg.get("frage_id") or "") if akt == "frage" else ""
        print(f"{i + 1:2d} A: {zug[:66]}")
        print(f"   B: {(a.antwort or '(still)')[:104]}  [{akt}/{frage or '-'}]")
        if a.uebergeben:
            print("   -> ABGABE an Legacy")
            break
        if a.hangup:
            print("   -> aufgelegt")
            break
        # Erledigt/Abschied: der Anrufer hat sein Anliegen durch, nicht
        # weiterreden (sonst messen wir kuenstliche Folgeschleifen).
        if akt in {"erfolg", "abschied", "erledigt"}:
            print("   -> Anliegen abgeschlossen")
            break
        if a.antwort == letzte and i:
            print("   -> WORTGLEICH, abgebrochen")
            break
        letzte = a.antwort
        zug = _antwort(frage, a.antwort, ziel)

    ledger = [e for e in g.state.ledger if getattr(e, "committed", False)]
    namen = sorted({getattr(e, "name", "?") for e in ledger})
    tasks = {t.typ: t.phase.value for t in g.state.tasks}
    print(f"   Schreibvorgaenge: {namen or 'KEINE'}   Aufgaben: {tasks}")
    return {"name": name, "writes": namen, "tasks": tasks, "zuege": len(g.verlauf)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--llm-base", default="http://127.0.0.1:18000/v1")
    p.add_argument("--ohne-llm", action="store_true")
    args = p.parse_args(argv)

    llm = None
    if not args.ohne_llm:
        os.environ["LLM_BASE"] = args.llm_base
        from bianca.controller import hirn

        def llm(text, lage=None):  # noqa: E731
            return hirn.deuten(text, lage=lage)

    pol = policy_mod.default()
    modus = "regelbasiert" if args.ohne_llm else f"LLM {args.llm_base}"
    print(f"Abschluss-Probe ({modus}) - Gateway ist die Simulation, kein echter Kalender.")

    faelle = [
        (
            "BUCHEN - Bestandspatient, Kontrolle",
            {
                "wunsch": "Guten Tag, ich braeuchte einen Termin zur Kontrolle.",
                "nachname": "Mack",
                "vorname": "Annemarie",
                "grund": "Kontrolle",
            },
            Szenario(anrufer_nachname="Mack", anrufer_vorname="Annemarie",
                     anrufer_telefon="+4917660893095", letzter_arzt="Dr. Petsas",
                     letzter_grund="Kontrolle", letzter_wann="2026-05-12"),
        ),
        (
            "BUCHEN - Neupatient ohne Akte",
            {
                "wunsch": "Hallo, ich moechte einen Termin vereinbaren.",
                "nachname": "Gavranides",
                "vorname": "Petros",
                "grund": "Zahnreinigung",
            },
            Szenario(),
        ),
        (
            "ABSAGEN - ein Bestandstermin",
            {
                "wunsch": "Ich moechte meinen Termin absagen.",
                "nachname": "Mack",
                "vorname": "Annemarie",
                "grund": "Kontrolle",
            },
            Szenario(anrufer_nachname="Mack", anrufer_vorname="Annemarie",
                     anrufer_telefon="+4917660893095"),
        ),
        (
            "VERSCHIEBEN - Bestandstermin",
            {
                "wunsch": "Ich muss meinen Termin verschieben.",
                "nachname": "Mack",
                "vorname": "Annemarie",
                "grund": "Kontrolle",
            },
            Szenario(anrufer_nachname="Mack", anrufer_vorname="Annemarie",
                     anrufer_telefon="+4917660893095"),
        ),
    ]

    ergebnis = [_lauf(n, z, sz, llm, pol) for n, z, sz in faelle]

    print(f"\n{'=' * 72}\n ERGEBNIS\n{'=' * 72}")
    for e in ergebnis:
        marke = "OK " if e["writes"] else "-- "
        print(f" {marke} {e['name']:42s} {', '.join(e['writes']) or 'kein Schreibvorgang'}")
    mit = sum(1 for e in ergebnis if e["writes"])
    print(f"\n {mit} von {len(ergebnis)} Anliegen bis zum Schreibvorgang getragen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
