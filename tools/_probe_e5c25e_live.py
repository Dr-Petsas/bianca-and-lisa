"""Live-Probe der vier Befunde aus Anruf e5c25e25 (13.09.2026).

Laeuft IM bianca-Container (`docker exec -w /app telefonki-bianca-1 python
tools/_probe_e5c25e_live.py`) gegen den wirklich deployten Code. Nur lesend:
kein Kalender-Schreiben, keine Notiz, kein Anruf.
"""

from __future__ import annotations

from bianca import flow, gehirn
from kern import abschweifen, unterbrechung
from kern.tenants import laden

fehler: list[str] = []


def pruef(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK   ' if ok else 'ROT  '} {name}{'  ' + detail if detail else ''}")
    if not ok:
        fehler.append(name)


def sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


def buchung(**felder):
    s_ = sit()
    s = gehirn.sammler(s_)
    s["modus"] = "buchen"
    s["warSchonMal"] = True
    s.update(felder)
    return s_, s


# 1) Die 100-Prozent-Wiederholung: echte Live-Werte (Ansage 4570 ms, "Gut."
#    endet bei 720 ms, Bruecke meldete `bruecke-ohr-barge ms=4020`).
KURZ = "Gut."
FRAGE = ("Ich will nichts falsch schreiben: Buchstabieren Sie mir "
         "den Nachnamen bitte einmal kurz?")
URL = "/api/audio-stream/c38306ad2e1f.wav"


def sprech_sit() -> dict:
    st = {"messages": [{"role": "user", "content": "Vormittags."},
                       {"role": "assistant", "content": f"{KURZ} {FRAGE}"}]}
    unterbrechung.merken(st, url=URL,
                         karte={"saetze": [KURZ, FRAGE], "endenMs": [720, 4570]},
                         text=f"{KURZ} {FRAGE}")
    return st


st = sprech_sit()
pruef("Wiederholung: Knacks bei 88 % -> kein Rest",
      not unterbrechung.eingang(st, URL, 4020) and "unterbrochen" not in st)

st2 = sprech_sit()
pruef("Gegenprobe: Knacks in der Satzmitte bleibt Rest",
      bool(unterbrechung.eingang(st2, URL, 2000))
      and st2["unterbrochen"]["rest"] == [FRAGE])

# 2) Der ueberhoerte Einwand gegen den verhoerten Nachnamen.
s_, s = buchung(nachname="Thomas", frage="vorname",
                arzt={"typ": "genannt", "calendarName": "Dr. Petsas"})
neu = gehirn.einsammeln(s_, "Nein, nein, nein, nicht Thomas, Thannes ist mein Nachname.")
q = flow._quittung(s, neu)
pruef("Einwand: Korrektur wird quittiert",
      s["nachname"] == "Thannes" and "Thomas" in q and "Thannes" in q, q.strip())
pruef("Einwand: Nachname wird SOFORT geklaert",
      gehirn.naechste_frage(s_)[0] == "buchstabieren")

s_, s = buchung(frage="buchstabieren", buchstabenTeil="th")
gehirn.einsammeln(s_, "Mein Nachname ist Thannes.")
pruef("Einwand: ausdrueckliche Zuweisung ist keine Buchstabierkette",
      s["nachname"] == "Thannes" and not s["buchstabenTeil"],
      f"nachname={s['nachname']!r} teil={s['buchstabenTeil']!r}")

# 3) "mein Sohn" schlaegt die Vornamen-Schaetzung.
s_, s = buchung()
gehirn.einsammeln(s_, "Der Termin ist für meinen Sohn Levy.")
pruef("Sohn: Geschlecht maennlich, Quelle rolle",
      s["geschlecht"] == "m" and s["geschlechtQuelle"] == "rolle",
      f"{s['geschlecht']}/{s['geschlechtQuelle']} fuerWen={s['fuerWen']!r}")
s["nachname"] = "Tzannis"
pruef("Sohn: Anrede ist nicht 'Frau Tzannis'",
      "Frau" not in gehirn.anrede(s), gehirn.anrede(s))

# 4) "der fruehere" / "der spaetere" relativ zur Liste.
angebot = [
    {"iso": "2026-09-18T09:00:00", "spoken": "Freitag, neun Uhr"},
    {"iso": "2026-09-18T15:30:00", "spoken": "Freitag, halb vier"},
]
pruef("Relativ: 'Der frühere.' waehlt den ersten Slot",
      flow._slot_wahl("Der frühere.", angebot) == angebot[0]["iso"])
pruef("Relativ: 'Den frühesten bitte.' ebenso",
      flow._slot_wahl("Den frühesten bitte.", angebot) == angebot[0]["iso"])
pruef("Relativ: 'Der spätere.' waehlt den letzten Slot",
      flow._slot_wahl("Der spätere.", angebot) == angebot[1]["iso"])
pruef("Gegenprobe: eigener Zeitwunsch ist keine Wahl",
      flow._slot_wahl("Geht es später, gegen vierzehn Uhr?", angebot) != angebot[1]["iso"])

# 5) Talk-Floor und Rezeption (aus Anruf 48673eca).
pruef("Abschweifen: zaehlt von 1 bis 4",
      abschweifen.antwort("Zähl mal von 1 bis 4.") == "Gerne: eins, zwei, drei, vier.")
pruef("Abschweifen: buchstabiert Abdullah",
      abschweifen.antwort("Buchstabiere meinen Namen Abdullah.").startswith("Gerne: A wie Anton, B wie Berta"))
pruef("Abschweifen: eigenes Diktat bleibt unberuehrt",
      abschweifen.antwort("Ich buchstabiere: Tzannis.") == "")
z = flow.zug(sit(), "Ich möchte bitte zur Rezeption.")
pruef("Rezeption ist kein Rezept", bool(z) and "Rezept" not in z["text"])

print()
print("probe-e5c25e: ALLE GRUEN" if not fehler else f"probe-e5c25e: ROT -> {fehler}")
raise SystemExit(1 if fehler else 0)
