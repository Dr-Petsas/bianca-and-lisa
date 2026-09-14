"""Nachstellung des MedDent-Anrufs e7191c7e (14.09.2026, 06:56) gegen den
aktuellen Code — offline (LLM gestubbt, Kalender gemockt, kein Netz).

Chef 14.09.2026 07:00 (woertlich): "es gab bei der Erkennung des Patienten
dopplungen die ueberfluessig sind / biancas reihenfolge der datenabfrage ist
schlecht . sie fragt zu frueh nach der handy nummer, bevor der termin
ueberhaupt steht! die handynummer sollte das letzte vor Versand der sms
sein, das abgefragt wird."

Live lief es so (Anrufer per Rufnummer als Michael Petsas erkannt):

  Zug 2  "Hallo, ich habe gerne einen Termin."  -> "Ah, Herr Petsas, wie geht es Ihnen?"
  Zug 3  "Danke, gut."   -> "Das freut mich. Guten Tag, hier ist Bianca von den
                            Zahnaerzten im Medical Center. Wie kann ich Ihnen helfen?"
  Zug 4  "Ich brauche einen Termin."  -> "Gerne. Habe ich Sie richtig erkannt?"
  Zug 7  STT-Muell        -> LLM: "… also eine Routinekontrolle. Haben Sie denn eine
                            Vorstellung, wann es Ihnen am besten passt?"
  Zug 8  "Eine Kontrolle bitte." -> "Wann passt es Ihnen am besten — vormittags oder
                            nachmittags?"                       (Zeitfrage doppelt)
  Zug 9  "Vormittag, morgen Vormittag, bitte." -> "Soll ich die Bestaetigungs-SMS an
                            die 0177 … schicken?"               (Nummer VOR dem Slot)
  Zug 10 "Ja."            -> PZR-Frage;  Zug 11 -> erst jetzt Slots …

Laeuft lokal (`python tools/_probe_e7191c7e.py`) und im Container
(`docker exec -w /app telefonki-bianca-1 python tools/_probe_e7191c7e.py`).
Nur lesend: kein Kalender-Schreiben, keine Notiz, kein Anruf.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ.setdefault("MAS_GEDAECHTNIS", "0")
os.environ.setdefault("INTENT_NACHZUG", "0")

from bianca import agent, flow, gehirn  # noqa: E402
from kern import llm  # noqa: E402
from kern.tenants import laden  # noqa: E402

fehler: list[str] = []


def pruef(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK   ' if ok else 'ROT  '} {name}{'  ' + detail if detail else ''}")
    if not ok:
        fehler.append(name)


def _slot(tage: int, h: int, m: int) -> str:
    d = datetime.now(ZoneInfo("Europe/Berlin")).replace(
        hour=h, minute=m, second=0, microsecond=0) + timedelta(days=tage)
    return d.isoformat(timespec="seconds")


# --- Stubs: kein Netz, kein Modell -----------------------------------------
gebucht: list[dict] = []
llm_zuege: list[str] = []


def _find(*a, **k):
    return {"ok": True, "slots": [_slot(2, 10, 30), _slot(2, 11, 0), _slot(2, 11, 30)],
            "doctorName": "Dr. Petsas"}


def _book(tenant, ctx, slot_iso=""):
    gebucht.append(dict(ctx))
    return {"ok": True, "booked": True, "slotIso": slot_iso, "appointmentId": "probe",
            "patientId": ctx.get("patientId") or "", "spoken": "Der Termin ist fest eingetragen."}


def _llm(msgs, tools=None, **kw):
    # Das Modell antwortet wie live in Zug 3/7: Re-Greeting bzw. erfundene
    # Zeitfrage — beides muss von den Wachen gestrichen werden.
    letzter = next((m.get("content") for m in reversed(msgs) if m.get("role") == "user"), "")
    llm_zuege.append(letzter or "")
    if "wenn man das noch" in (letzter or ""):
        text = ("Verstehe, also eine Routinekontrolle. Haben Sie denn eine Vorstellung, "
                "wann es Ihnen am besten passt?")
    else:
        text = ("Das freut mich. Guten Tag, hier ist Bianca von den Zahnärzten im "
                "Medical Center. Wie kann ich Ihnen helfen?")
    es = kw.get("erster_satz")
    if es:
        for satz in text.split(". "):
            es(satz if satz.endswith((".", "?", "!")) else satz + ".")
    return {"ok": True, "text": text, "tool_calls": []}


echt = (flow.hintergrund.anstossen, flow.kal.find_slots, flow.kal.find_slots_behandler,
        flow.kal.book_slot, flow.kal.note_appointment, llm.chat_stream, llm.chat)
flow.hintergrund.anstossen = lambda sit: None
flow.kal.find_slots = _find
flow.kal.find_slots_behandler = _find
flow.kal.book_slot = _book
flow.kal.note_appointment = lambda *a, **k: {"ok": True, "spoken": "Die Notiz ist am Termin."}
llm.chat_stream = _llm
llm.chat = _llm


def sitzung() -> dict:
    sit = {"tenant": laden("meddent"), "messages": []}
    sit["anrufer"] = {
        "vorname": "Michael", "nachname": "Petsas", "patientId": "74NAKbsQzgRw6NpXd0Sp",
        "geschlecht": "male", "telefon": "+491776004600",
    }
    # Kartei-Treffer wie live (hintergrund.kartei_von_anrufer): letzter Besuch
    # bei Doktor Petsas -> Behandler wird nach dem Identitaets-Ja uebernommen.
    sit["anruferKartei"] = {"letzterBesuch": "2026-08-20T10:00:00", "letzterGrund": "Kontrolle",
                            "calendarId": "zex5bmv5jfIHWVW6zHbg",
                            "calendarName": "Doktor Michael Petsas", "doctorName": "Petsas",
                            "gesperrt": False, "nextAppointment": {}}
    sit["halloVariante"] = 0  # live: die Frage-Variante ("wie geht es Ihnen?")
    agent.start_reply(sit)
    return sit


def zug(sit: dict, gesagt: str) -> str:
    hits: list[str] = []
    r = agent.user_turn(sit, gesagt, vorab=hits.append) or {}
    text = " ".join(x for x in [*hits, (r.get("text") or "")] if x).strip()
    # Vorab-Saetze stehen im Endtext meist noch einmal — fuer die Anzeige
    # reicht der Endtext, wenn er die Vorab-Saetze schon enthaelt.
    if hits and all(h in (r.get("text") or "") for h in hits):
        text = (r.get("text") or "").strip()
    print(f"  ANRUFER: {gesagt}\n  BIANCA : {text}")
    return text


try:
    print("--- Nachstellung e7191c7e (MedDent, Anrufer erkannt: Michael Petsas)")
    sit = sitzung()
    s = gehirn.sammler(sit)

    a = zug(sit, "Hallo, ich habe gerne einen Termin.")
    pruef("Zug 2: keine Wohlseinsfrage, wenn das Anliegen im Satz steht",
          "wie geht" not in a.lower() and not sit.get("anruferHalloFrageOffen"))
    pruef("Zug 2: Identitaets-Check kommt sofort", "richtig erkannt" in a.lower())
    pruef("Zug 2: Buchung erkannt (modus=buchen)", s.get("modus") == "buchen", f"modus={s.get('modus')!r}")

    b = zug(sit, "Ja.")
    pruef("Zug 3: kein Re-Greeting, keine zweite Begruessung",
          "hier ist bianca" not in b.lower() and "guten tag" not in b.lower()
          and "wie kann ich ihnen helfen" not in b.lower())
    pruef("Zug 3: eigener Schritt 'fuer Sie selbst?'", "für sie selbst" in b.lower())

    c = zug(sit, "Ja.")
    pruef("Zug 4: Grund-Frage, keine Nummer", "worum" in c.lower() and "nummer" not in c.lower())

    d = zug(sit, "Alles gut, wenn man das noch.")
    pruef("Zug 5: erfundene Zeitfrage des Modells gestrichen (Frage-Gate)",
          "wann" not in d.lower() or s.get("frage") == "grund", f"frage={s.get('frage')!r}")
    pruef("Zug 5: Maschine bleibt beim Grund", s.get("frage") == "grund")

    e = zug(sit, "Eine Kontrolle bitte.")
    pruef("Zug 6: Zeitfrage genau einmal", e.lower().count("wann") <= 1 and "nummer" not in e.lower())

    f = zug(sit, "Vormittag, morgen Vormittag, bitte.")
    pruef("Zug 7: KEINE Nummernfrage vor dem Slot", "sms" not in f.lower() and "nummer" not in f.lower())
    pruef("Zug 7: Slots werden angeboten", "frei" in f.lower() and bool(sit.get("offered")))

    g = zug(sit, "Ja, übermorgen um 10.30 Uhr.")
    pruef("Zug 8: Readback des Termins", "halte ich fest" in g.lower() and "nummer" not in g.lower())

    h = zug(sit, "Ja, bitte.")
    pruef("Zug 9: nach dem Ja kommt das PZR-Angebot, nicht die Nummer",
          "zahnreinigung" in h.lower() and "nummer" not in h.lower())

    i = zug(sit, "Ähm nein.")
    pruef("Zug 10: Doktor-Notiz-Frage, noch keine Nummer",
          "notiz" in i.lower() and "nummer" not in i.lower())

    j = zug(sit, "Nein.")
    pruef("Zug 11: JETZT die hinterlegte Nummer als SMS-Ziel — letzter Schritt vor dem Eintragen",
          "sms" in j.lower() and "null eins sieben sieben" in j.lower() and not gebucht)

    k = zug(sit, "Ja.")
    pruef("Zug 12: Buchung direkt nach dem Nummern-Ja (kein neues Angebot)",
          bool(gebucht) and "eingetragen" in k.lower() and "welcher" not in k.lower())
    pruef("Zug 12: Nummer im Buchungs-Kontext",
          bool(gebucht) and (gebucht[0].get("phone") or "").endswith("1776004600"),
          str(gebucht[0].get("phone") if gebucht else None))
    pruef("LLM lief nur fuer den STT-Muell-Zug",
          llm_zuege == ["Alles gut, wenn man das noch."], str(llm_zuege))
finally:
    (flow.hintergrund.anstossen, flow.kal.find_slots, flow.kal.find_slots_behandler,
     flow.kal.book_slot, flow.kal.note_appointment, llm.chat_stream, llm.chat) = echt

print()
print("probe-e7191c7e: ALLE GRUEN" if not fehler else f"probe-e7191c7e: ROT -> {fehler}")
raise SystemExit(1 if fehler else 0)
