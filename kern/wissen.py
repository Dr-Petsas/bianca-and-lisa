"""Praxiswissen aus dem Mandanten in den Systemprompt (Chef 27.08.2026).

Eine Quelle für beide Stimmen (Bianca und Lisa): Zahnmedizin-Grundwissen in
ein bis zwei Sätzen erlauben, Preise NUR aus der Mandanten-Liste nennen —
alles andere ehrlich an den Zahnarzt verweisen. Kein Erfinden, kein Schätzen
(Vorfall 27.08.2026: „feste Zahnarztschönheit" auf die Kontroll-Preisfrage).
"""

from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any

from kern import motive, pzr_kassen

VERWEIS_SATZ = "Das müssen Sie direkt mit Ihrem Zahnarzt besprechen."
VERWEIS_PRAXIS = "Das müssen Sie direkt mit der Praxis besprechen."

# Anfahrts-/Wegfragen sind die EINE erlaubte Langtext-Antwort: der volle
# Anfahrtstext (~110 Tokens) riss am Standard-Antwortlimit (max_tokens=90)
# mitten im Wort ab ("in die zweite Et", E2E 27.08.2026). Die Agenten heben
# das Limit NUR fuer solche Zuege an.
LANGTEXT_MAX_TOKENS = 260
_LANGTEXT_RE = re.compile(
    r"anfahrt|anreise|adresse|wegbeschreibung|hinkommen|"
    r"wie\s+komm\w*\s+(?:ich|man|wir)|"
    r"wie.{0,40}(?:praxis|praktisch|dorthin|dort).{0,24}erreich\w*|"
    r"wie\s+erreich\w*\s+(?:ich|man|wir)\s+(?:die\s+praxis|sie|ihnen|euch)|"
    r"wo\s+(?:genau\s+)?(?:sind\s+sie|finde\s+ich|liegt|ist\s+die\s+praxis)",
    re.I,
)


def braucht_langtext(text: str) -> bool:
    """True, wenn der Anrufer nach Weg/Adresse fragt — dann darf die Antwort
    laenger sein als die ueblichen ein bis zwei Saetze."""
    return bool(_LANGTEXT_RE.search(text or ""))


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _norm(v: Any) -> str:
    text = str(v or "").casefold().replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text)
    return " ".join(re.findall(r"[a-z0-9]+", text.encode("ascii", "ignore").decode("ascii")))


def _oeffnungszeiten_thema(text: str) -> bool:
    """Auch robuste STT-Verhörer wie „Pflungszeiten“ erkennen.

    Der Fuzzy-Vergleich bleibt absichtlich auf lange Einzelwörter und eine
    hohe Schwelle begrenzt; „Behandlungszeiten“ oder „Vorstellungszeiten“
    dürfen nicht versehentlich als Öffnungszeiten gelten.
    """
    low = _norm(text)
    if re.search(r"\b(?:offnungs?zeiten?|oeffnungs?zeiten?|sprechzeiten?)\b", low):
        return True
    if re.search(r"\bwann\b.{0,30}\b(?:offen|geoffnet)\b", low):
        return True
    for token in low.split():
        if len(token) >= 9 and SequenceMatcher(None, token, "offnungszeiten").ratio() >= 0.78:
            return True
    return False


def _anfahrt_thema(text: str) -> bool:
    return bool(_LANGTEXT_RE.search(text or ""))


def auskunft_themen(text: str) -> set[str]:
    """Praxis-Fakten, nach denen der Zug fragt."""
    out: set[str] = set()
    if _oeffnungszeiten_thema(text):
        out.add("oeffnungszeiten")
    if _anfahrt_thema(text):
        out.add("anfahrt")
    return out


def _prompt_oeffnungszeiten(prompt: str) -> str:
    for zeile in str(prompt or "").splitlines():
        sauber = re.sub(r"^\s*[-*]\s*", "", zeile).strip()
        m = re.match(r"(?:öffnungs|oeffnungs|sprech)zeiten?\s*:\s*(.+)", sauber, re.I)
        if m and _s(m.group(1)):
            return _s(m.group(1))
    return ""


def _prompt_anfahrt(prompt: str) -> str:
    """Den ausdrücklich diktierten Weg-Abschnitt aus einem DB-Prompt lesen."""
    zeilen = str(prompt or "").splitlines()
    start = -1
    for i, zeile in enumerate(zeilen):
        low = _norm(zeile)
        if ("nach dem weg fragt" in low and "sagst du" in low) or low in {
            "anfahrt", "wegbeschreibung",
        }:
            start = i + 1
            break
    if start < 0:
        return ""
    teile: list[str] = []
    for zeile in zeilen[start:]:
        low = _norm(zeile)
        if low.startswith(("offentliche verkehrsmittel", "oepnv")):
            break
        if zeile.lstrip().startswith("#"):
            break
        sauber = re.sub(r"^\s*[-*]\s*", "", zeile).strip()
        sauber = sauber.strip(' "\'„“”')
        if sauber:
            teile.append(sauber)
    return _s(" ".join(teile))


def _sprechbare_zeiten(raw: str) -> str:
    text = _s(raw).strip(" .")
    text = re.sub(
        r"\bMo(?:ntag)?\s*[-–—]\s*Do(?:nnerstag)?\s*:\s*",
        "montags bis donnerstags von ",
        text,
        flags=re.I,
    )
    text = re.sub(r"\bFr(?:eitag)?\s*:\s*", "freitags von ", text, flags=re.I)
    text = re.sub(
        r"(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})\s*Uhr",
        r"\1 bis \2 Uhr",
        text,
    )
    return text


def praxis_antwort(tenant: dict | None, text: str) -> tuple[str, set[str]]:
    """Öffnungszeiten/Weg ausschließlich aus Mandanten-Fakten beantworten.

    DB-Prompt gewinnt; ``wissen`` ist der lokale Rückfall. Fehlt ein Fakt,
    übernimmt weiterhin der normale Gesprächspfad, statt etwas zu erfinden.
    """
    themen = auskunft_themen(text)
    if not themen:
        return "", set()
    t = tenant if isinstance(tenant, dict) else {}
    w = t.get("wissen") if isinstance(t.get("wissen"), dict) else {}
    prompt = str(t.get("dbPrompt") or "")
    teile: list[str] = []
    bedient: set[str] = set()
    if "oeffnungszeiten" in themen:
        zeiten = (
            _prompt_oeffnungszeiten(prompt)
            or _s(w.get("oeffnungszeiten"))
            or _s(t.get("oeffnungszeiten"))
        )
        if zeiten:
            teile.append(f"Unsere Öffnungszeiten sind {_sprechbare_zeiten(zeiten)}.")
            bedient.add("oeffnungszeiten")
    if "anfahrt" in themen:
        anfahrt = _prompt_anfahrt(prompt) or _s(w.get("anfahrt")) or _s(t.get("anfahrt"))
        if anfahrt:
            teile.append(anfahrt.rstrip(" .") + ".")
            bedient.add("anfahrt")
    return " ".join(teile), bedient


def wissen_block(wissen: dict | None, sit: dict | None = None) -> str:
    """Kompakter Prompt-Abschnitt aus tenant['wissen'] — bewusst klein (Token-Budget).

    sit=None: bisheriges Zahn-Verhalten (Unit-Tests ohne Sitzung).
    sit mit Nicht-Zahn-Katalog: kein Zahnarzt-Verweis, keine PZR-Tabelle."""
    w = wissen if isinstance(wissen, dict) else {}
    zahn = True if sit is None else motive.ist_zahn(sit)
    preise = [_s(p) for p in (w.get("preise") or []) if _s(p)]
    hinweise = [_s(h) for h in (w.get("hinweise") or []) if _s(h)]
    verweis = _s(w.get("preiseSonst")) or (VERWEIS_SATZ if zahn else VERWEIS_PRAXIS)
    anfahrt = _s(w.get("anfahrt"))
    oepnv = _s(w.get("oepnv"))

    zeilen = [
        "ZAHNMEDIZIN UND PREISE" if zahn else "PREISE",
    ]
    if zahn:
        zeilen.append(
            "Allgemeine Zahnmedizinfragen (Was ist eine Wurzelbehandlung? Tut ein Implantat weh? "
            "Wie lange dauert eine Zahnreinigung?) beantwortest du in ein bis zwei "
            "allgemeinverständlichen Sätzen — keine Diagnosen, keine individuellen Heilaussagen."
        )
    else:
        zeilen.append(
            "Keine Diagnosen, keine individuellen Heilaussagen. Fachfremde Leistungen "
            "(Zahnreinigung, Bleaching, Implantate) bietest du NICHT an und nennst dafür keine Preise."
        )
    if preise:
        zeilen.append("PREISE (ungefähr, circa — NUR diese nennen):")
        zeilen.extend(f"- {p}" for p in preise)
        zeilen.append(
            f"Alle anderen Preise kennst du NICHT: nie schätzen, nichts erfinden, sondern wörtlich: „{verweis}“"
        )
    else:
        zeilen.append(f"Preise kennst du KEINE: nie schätzen, sondern wörtlich: „{verweis}“")
    pzr = pzr_kassen.fuer_wissen(w) if zahn else ""
    if pzr:
        zeilen.append(pzr)
    if anfahrt:
        zeilen.append(
            "ANFAHRT — fragt jemand nach dem Weg, der Adresse oder „wie komme ich zu Ihnen“, "
            "sprich AUSNAHMSWEISE diesen vollen Text (nichts weglassen, nichts dazuerfinden, "
            "KEINE Parkplatz-Aussagen — Parken kennst du nicht):"
        )
        zeilen.append(anfahrt)
    if oepnv:
        zeilen.append(
            "ÖPNV — bei Fragen nach Bahn oder Bus; Linien-Nummern GENAU so in Worten lassen: "
            + oepnv
        )
    zeilen.extend(hinweise)
    return "\n".join(zeilen)
