"""Praxiswissen aus dem Mandanten in den Systemprompt (Chef 27.08.2026).

Eine Quelle für beide Stimmen (Bianca und Lisa): Zahnmedizin-Grundwissen in
ein bis zwei Sätzen erlauben, Preise NUR aus der Mandanten-Liste nennen —
alles andere ehrlich an den Zahnarzt verweisen. Kein Erfinden, kein Schätzen
(Vorfall 27.08.2026: „feste Zahnarztschönheit" auf die Kontroll-Preisfrage).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from kern.sprech import TZ, heute_ansage

VERWEIS_SATZ = "Das müssen Sie direkt mit Ihrem Zahnarzt besprechen."

# Anfahrts-/Wegfragen sind die EINE erlaubte Langtext-Antwort: der volle
# Anfahrtstext (~110 Tokens) riss am Standard-Antwortlimit (max_tokens=90)
# mitten im Wort ab ("in die zweite Et", E2E 27.08.2026). Die Agenten heben
# das Limit NUR fuer solche Zuege an.
LANGTEXT_MAX_TOKENS = 260
_LANGTEXT_RE = re.compile(
    r"anfahrt|anreise|adresse|wegbeschreibung|hinkommen|"
    r"parken|parkplatz|parkhaus|tiefgarage|stellplatz|"
    r"oeffnungszeit|öffnungszeit|wann\s+(?:habt|haben)\s+(?:ihr|sie)\s+auf|"
    r"telefonnummer|e-?mail|website|homepage|"
    r"wie\s+komm\w*\s+(?:ich|man|wir)|wo\s+(?:genau\s+)?(?:sind\s+sie|finde\s+ich|liegt|ist\s+die\s+praxis)",
    re.I,
)


def braucht_langtext(text: str) -> bool:
    """True, wenn der Anrufer nach Weg/Adresse fragt — dann darf die Antwort
    laenger sein als die ueblichen ein bis zwei Saetze."""
    return bool(_LANGTEXT_RE.search(text or ""))


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def wissen_block(wissen: dict | None) -> str:
    """Kompakter Prompt-Abschnitt aus tenant['wissen'] — bewusst klein (Token-Budget)."""
    w = wissen if isinstance(wissen, dict) else {}
    preise = [_s(p) for p in (w.get("preise") or []) if _s(p)]
    hinweise = [_s(h) for h in (w.get("hinweise") or []) if _s(h)]
    verweis = _s(w.get("preiseSonst")) or VERWEIS_SATZ
    adresse = _s(w.get("adresse"))
    anfahrt = _s(w.get("anfahrt"))
    oepnv = _s(w.get("oepnv"))
    parken = _s(w.get("parken"))
    kontakt = _s(w.get("kontakt"))
    oeffnung = _s(w.get("oeffnung"))

    zeilen = [
        "ZAHNMEDIZIN UND PREISE",
        "Allgemeine Zahnmedizinfragen (Was ist eine Wurzelbehandlung? Tut ein Implantat weh? Wie lange dauert eine Zahnreinigung?) beantwortest du in ein bis zwei allgemeinverständlichen Sätzen — keine Diagnosen, keine individuellen Heilaussagen.",
    ]
    if preise:
        zeilen.append("PREISE (grob, circa — NUR diese nennen):")
        zeilen.extend(f"- {p}" for p in preise)
        zeilen.append(
            f"Alle anderen Preise kennst du NICHT: nie schätzen, nichts erfinden, sondern wörtlich: „{verweis}“"
        )
    else:
        zeilen.append(f"Preise kennst du KEINE: nie schätzen, sondern wörtlich: „{verweis}“")
    if adresse:
        zeilen.append("ADRESSE — bei „wo seid ihr“ / Anschrift, nichts dazuerfinden:")
        zeilen.append(adresse)
    if anfahrt:
        park_warnung = (
            "" if parken else
            " KEINE Parkplatz-Aussagen — Parken kennst du nicht."
        )
        zeilen.append(
            "ANFAHRT — fragt jemand nach dem Weg oder „wie komme ich zu Ihnen“, "
            "sprich AUSNAHMSWEISE diesen vollen Text (nichts weglassen, nichts dazuerfinden)."
            + park_warnung
        )
        zeilen.append(anfahrt)
    if oepnv:
        zeilen.append(
            "ÖPNV — bei Fragen nach Bahn oder Bus; Linien-Nummern GENAU so in Worten lassen: "
            + oepnv
        )
    if parken:
        zeilen.append("PARKEN — nur diesen Text, nichts dazuerfinden:")
        zeilen.append(parken)
    if kontakt:
        zeilen.append("KONTAKT — Telefon, E-Mail, Website; nichts anderes erfinden:")
        zeilen.append(kontakt)
    if oeffnung:
        zeilen.append("ÖFFNUNGSZEITEN — nur diesen Text:")
        zeilen.append(oeffnung)
    zeilen.extend(hinweise)
    return "\n".join(zeilen)


# --- Harte Fakten (Vorfall 28.08.2026: erfundenes Datum + erfundene Ärzte) --

# "welcher Tacken" = STT fuer "welcher Tag" (live 28.08.2026). Nicht
# treffen, wenn ein Buchungs-Tag gemeint ist ("welcher Tag passt").
_HEUTE_FRAGE_RE = re.compile(
    r"(welcher\s+ta(?:g|cken|gen|ck|ggen)\b.{0,24}\bheute\b|"
    r"\bheute\b.{0,16}welcher\s+ta(?:g|cken|gen|ck|ggen)\b|"
    r"welcher\s+ta(?:g|cken|gen|ck|ggen)\b(?!.{0,24}(?:passt|frei|termin|"
    r"nächste|naechste|woche|montag|dienstag|mittwoch|donnerstag|freitag))|"
    r"welches\s+datum|"
    r"was\s+(?:ist|haben\s+wir)\s+heute(?:\s+(?:fuer|für)\s+ein\s+(?:tag|datum))?|"
    r"der\s+wievielte\s+ist|"
    r"welchen\s+wochentag)",
    re.I,
)


def ist_heute_frage(text: str) -> bool:
    """Reine Datumsfrage — nicht 'heute Nachmittag passt es'."""
    t = _s(text)
    if not t:
        return False
    return bool(_HEUTE_FRAGE_RE.search(t))


def heute_antwort(*, heute: date | None = None) -> str:
    return f"Heute ist {heute_ansage(heute=heute)}."


def aerzte_zeile(tenant: dict | None) -> str:
    """Alle Kalender-Namen des Mandanten — nicht nur der Default-Behandler."""
    t = tenant if isinstance(tenant, dict) else {}
    namen: list[str] = []
    for c in t.get("calendars") or []:
        n = _s((c or {}).get("name"))
        if n and n not in namen:
            namen.append(n)
    if not namen:
        n = _s(t.get("behandler"))
        return n
    return ", ".join(namen)


def fakten_block(tenant: dict | None = None, *, heute: date | None = None) -> str:
    """Kalendertag + Ärzte-Liste — Tatsachen, kein Modell-Ratefeld."""
    d = heute or datetime.now(TZ).date()
    aerzte = aerzte_zeile(tenant)
    zeilen = [
        f"HEUTE IST {heute_ansage(heute=d)} (ISO {d.isoformat()}). "
        "Das ist eine Tatsache — kein anderes Datum und kein anderes Jahr nennen.",
    ]
    if aerzte:
        zeilen.append(
            f"ÄRZTE IN DIESER PRAXIS: {aerzte}. Das sind DREI gleichgestellte Zahnärzte — "
            "es gibt keinen Chefarzt und NICHT nur einen einzigen Arzt. "
            "Nenne die Namen NUR, wenn ausdrücklich danach gefragt wird "
            "(„welche Ärzte gibt es?“). Beim Terminwunsch nach dem Zahnarzt fragen, "
            "OHNE die Liste vorzulesen. Einen Arzt von dieser Liste niemals als unbekannt abtun."
        )
    zeilen.append(
        "SPERRZEITEN: Samstag, Sonntag, gesetzliche Feiertage in NRW und "
        "Zeiten außerhalb der Sprechzeiten (Montag bis Donnerstag acht bis achtzehn Uhr, "
        "Freitag acht bis sechzehn Uhr) sind geschlossen — dort weder Termine "
        "anbieten noch zusagen. Abwesende Zahnärzte nicht belegen."
    )
    return "\n".join(zeilen)
