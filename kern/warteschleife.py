"""Warteschleifen-Wache (W-WARTESCHLEIFE 14.09.2026 — Thaler 9311a9e2 / e2badc4c).

Chef 14.09.2026 zu Anruf e2badc4c: "da kommen so sachen vor plötzlich:
Übrigens, online finden Sie uns rund um die Uhr, ganz ohne Wartezeiten, unter
www.zahnarztpraxis-mainburg.de … ich weiss nicht woher das kommt".

Befund: Die Sätze kommen NICHT von Bianca — sie HÖRT sie. Es sind die
Ansagen der Praxis-Telefonanlage ("Einen kleinen Augenblick noch bitte, wir
sind gleich persönlich für Sie da."). Die Anlage hat den Anrufer in ihre
Warteschleife zurückgeholt; am anderen Ende von Biancas Leitung spricht kein
Mensch mehr. Live wurden die Ansagen als ANRUFER-Sätze behandelt:

- das Modell bedankte sich für den "wichtigen Hinweis" und "notierte" die
  Web-Adresse (9311a9e2, Zug 15),
- "…einen Termin zu vereinbaren" startete die Buchungsmaschine
  (e2badc4c, Zug 4: anrufer_check auf eine Ansage),
- der Anruf lief 141 s bzw. 331 s mit "Sind Sie noch dran?" / "Meine Frage
  war …" gegen die Schleife, bis die Notleine (W-STUPS-GESAMT) griff.

Regel — deterministisch, 0 ms, kein Modell:

- `ist_ansage(satz)`: Anlagen-Sätze sprechen aus PRAXIS-Perspektive ZUM
  Anrufer ("wir sind gleich für Sie da", "online finden Sie uns", "Ihr Anruf
  ist uns wichtig", "alle Leitungen sind besetzt", "bleiben Sie in der
  Leitung", "unter www.…", "dort haben Sie die Möglichkeit …"). So spricht
  kein Anrufer mit Bianca. Ein "Einen Moment bitte" des Anrufers (er sucht
  den Kalender) trägt diese Perspektive NICHT und ist keine Ansage.
- `zerlegen(text)`: trennt Ansage-Sätze vom echten Anrufer-Rest. Live
  e2badc4c Zug 4: "Ja, ich wurde angerufen, von wem? Keine Ahnung. Übrigens,
  online finden Sie uns …" — der Anfang ist Anrufer-Sprache und wird normal
  verarbeitet. Rest OHNE Sprecher-Marker (kein ich/mir/Termin/ja/nein …)
  neben einer erkannten Ansage gilt als Teil der Ansage (unbekannter
  Ansagesatz wie "Herzlich willkommen bei …").
- `bewerten(sit, text)` zählt die Ansagen im Anruf und liefert die Aktion:
  "weiter" (keine Ansage), "rest" (gemischt — Rest normal verarbeiten),
  "warte" (reine Ansage: still bleiben — kein Ton, kein Fluss, kein Modell,
  nichts ins Protokoll), "auflegen" (Schleife erkannt).
  Aufgelegt wird nur auf einen REINEN Ansage-Zug — nie mitten in einem Zug
  mit Anrufer-Sprache — und erst ab der `AUFLEGEN_AB`-ten Ansage, wenn der
  Anrufer im Anruf schon gesprochen hat. Hat noch niemand gesprochen (eine
  Begrüßungsansage VOR dem Durchstellen wäre denkbar), erst ab
  `AUFLEGEN_AB_OHNE_SPRACHE`: eine einmalige Ansage darf einen echten
  Anruf nie beenden.

Nie angefasst: Sätze ohne Praxis-Perspektive, Fragen des Anrufers,
Ziffern-Diktate. Ein übersehener Ansagesatz kostet nur einen unnötigen
Zug (wie bisher); ein fälschlich als Ansage gewerteter Anrufersatz wäre
der teurere Fehler — deshalb nur Muster, die live oder in Anlagen-Ansagen
typisch sind und die ein Anrufer nicht sagt.

Notaus: `WARTESCHLEIFE=0` => Verhalten wie vor dem Patch.
Tests: `tests/test_warteschleife.py`
"""

from __future__ import annotations

import os
import re
from typing import Any

# Ab der wievielten Ansage wird aufgelegt (Anrufer hatte schon gesprochen)?
AUFLEGEN_AB = 2
# … und wenn im Anruf noch kein Anrufer-Wort gefallen ist?
AUFLEGEN_AB_OHNE_SPRACHE = 3
# Ruhe-Schwelle, die das Dock/die Bruecke nach einer stillen Ansage bekommt.
WARTE_MS = 1500

_SATZ_ENDE_RE = re.compile(r"(?<=[.!?…])\s+")

_UE = r"(?:ü|ue)"
_OE = r"(?:ö|oe)"
_AE = r"(?:ä|ae)"

# Praxis-Perspektive zum Anrufer — je Muster reicht EIN Treffer im Satz.
_ANSAGE_RE = re.compile(
    "|".join(
        [
            # "…, wir sind gleich (persönlich) für Sie da"
            rf"\bwir\s+sind\s+(?:gleich|sofort|in\s+k{_UE}rze|umgehend)\s+(?:wieder\s+)?"
            rf"(?:pers{_OE}nlich\s+)?f{_UE}r\s+sie\s+da\b",
            # "Sie werden gleich verbunden" / "wir verbinden Sie gleich/mit dem nächsten …"
            r"\bsie\s+werden\s+(?:gleich|sofort|in\s+k(?:ü|ue)rze|umgehend)\s+(?:weiter)?verbunden\b",
            rf"\bwir\s+verbinden\s+sie\s+(?:gleich|sofort|in\s+k{_UE}rze|umgehend|mit\s+dem\s+n{_AE}chsten)\b",
            # "alle Leitungen/Mitarbeiter sind (derzeit) besetzt/im Gespräch"
            rf"\b(?:alle|unsere|s{_AE}mtliche)\s+(?:leitungen|mitarbeiter(?:innen)?|pl{_AE}tze|"
            rf"anschl{_UE}sse|arbeitspl{_AE}tze)\s+sind\s+(?:derzeit\s+|momentan\s+|zur\s*zeit\s+|"
            rf"gerade\s+|leider\s+|noch\s+|im\s+moment\s+)*(?:besetzt|belegt|im\s+gespr{_AE}ch)\b",
            # "der nächste freie Mitarbeiter …"
            rf"\b(?:der|die)\s+n{_AE}chste\s+freie\s+(?:mitarbeiter(?:in)?|leitung|platz)\b",
            # "Ihr Anruf ist uns (sehr) wichtig"
            r"\bihr\s+anruf\s+ist\s+uns\s+(?:sehr\s+)?wichtig\b",
            # "bleiben Sie (bitte) dran / am Apparat / in der Leitung"
            r"\b(?:ver)?bleiben\s+sie\s+(?:bitte\s+)?(?:dran|am\s+apparat|in\s+der\s+leitung)\b",
            # "wir bitten (Sie) um einen Moment Geduld / um Verständnis"
            rf"\bwir\s+bitten\s+(?:sie\s+)?um\s+(?:einen\s+(?:kleinen\s+|kurzen\s+)?(?:moment|augenblick)|"
            rf"etwas|ein\s+wenig|noch\s+etwas)\s+geduld\b|\bwir\s+bitten\s+(?:sie\s+)?um\s+(?:ihr\s+)?verst{_AE}ndnis\b",
            # "(Übrigens,) online finden Sie uns …" / "finden Sie uns auch im Internet"
            r"\bonline\s+finden\s+sie\s+uns\b|\bfinden\s+sie\s+uns\s+(?:auch\s+)?(?:online|im\s+internet)\b",
            # "besuchen Sie (auch) unsere Homepage/Webseite"
            r"\bbesuchen\s+sie\s+(?:uns\s+)?(?:auch\s+)?(?:auf\s+)?unsere[rn]?\s+(?:homepage|webseite|website|internetseite)\b",
            # gesprochene Web-Adresse
            r"\bunter\s+www\.|\bwww\.[a-z0-9\-]+\.(?:de|com|at|ch|eu|info|net)\b",
            # "Dort haben Sie (auch) (jederzeit) die Möglichkeit …" / "dort können Sie …"
            rf"\bdort\s+haben\s+sie\s+(?:auch\s+)?(?:jederzeit\s+|rund\s+um\s+die\s+uhr\s+)?die\s+m{_OE}glichkeit\b",
            rf"\bdort\s+k{_OE}nnen\s+sie\s+(?:auch\s+)?(?:jederzeit\s+|rund\s+um\s+die\s+uhr\s+)?(?:einen\s+termin|online|bequem)\b",
            # Begrüßungs-/Mailbox-Ansagen der Anlage
            rf"\b(?:vielen\s+)?dank(?:e)?\s+f{_UE}r\s+ihren\s+anruf\b",
            r"\bsie\s+haben\s+(?:die|unsere)\s+(?:zahnarzt|hautarzt|gemeinschafts|kinderarzt)?praxis\b[^.!?]{0,60}\b(?:erreicht|angerufen)\b",
            # BEWUSST NICHT: "außerhalb der Sprechzeiten" — das fragt auch ein
            # Anrufer ("Kann ich auch außerhalb der Sprechzeiten kommen?").
            rf"\bunsere\s+(?:sprech|{_OE}ffnungs|praxis)zeiten\s+sind\b",
            r"\bhinterlassen\s+sie\s+(?:bitte\s+)?(?:uns\s+)?(?:eine\s+nachricht|ihren\s+namen|ihre\s+(?:telefon|ruf)?nummer)\b",
            r"\bnach\s+dem\s+(?:signal)?ton\b|\bsprechen\s+sie\s+(?:bitte\s+)?(?:nach\s+dem\s+|auf\s+(?:den|das)\s+)",
        ]
    ),
    re.I,
)

# Ein Rest neben einer erkannten Ansage ist nur dann Anrufer-Sprache, wenn er
# klingt, als spräche jemand MIT Bianca: erste Person Singular, Zustimmung/
# Ablehnung, Anliegen-Wörter. Ohne so einen Marker ("Herzlich willkommen bei
# …", "Bitte warten Sie.", "Wir bitten um Geduld.") gehört er zur Ansage —
# "wir/uns" ist deshalb bewusst KEIN Sprecher-Marker (Anlagen sprechen so).
_SPRECHER_RE = re.compile(
    r"\b(?:ich|mir|mich|mein(?:e[nrs]?)?|ja|nein|jawohl|hallo|"
    r"guten\s+(?:tag|morgen|abend)|termin\w*|absag\w*|verschieb\w*|stornier\w*|"
    r"frage|danke|dankesch(?:ö|oe)n|okay|ok|genau|richtig|stimmt|wann|wie|wer|"
    r"welche[rsn]?|k(?:ö|oe)nnen|k(?:ö|oe)nnte|m(?:ö|oe)chte|h(?:ä|ae)tte|brauche|will)\b",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def an() -> bool:
    """Notaus WARTESCHLEIFE=0 => keine Erkennung, Verhalten wie vorher."""
    return (os.environ.get("WARTESCHLEIFE") or "1").strip() != "0"


def ist_ansage(satz: str) -> bool:
    """Klingt dieser (Teil-)Satz wie eine Ansage der Praxis-Telefonanlage?"""
    t = _s(satz)
    if not t:
        return False
    return bool(_ANSAGE_RE.search(t))


def saetze(text: str) -> list[str]:
    return [s for s in _SATZ_ENDE_RE.split(_s(text)) if s.strip()]


def zerlegen(text: str) -> tuple[str, str]:
    """(Ansage-Teil, Anrufer-Rest). Beides leer => keine Ansage im Text."""
    teile = saetze(text)
    ansage = [s for s in teile if ist_ansage(s)]
    if not ansage:
        return "", ""
    rest = [s for s in teile if not ist_ansage(s)]
    rest_text = " ".join(rest).strip()
    if rest_text and not _SPRECHER_RE.search(rest_text):
        # Unbekannter Ansagesatz neben bekannten: alles Ansage.
        ansage = teile
        rest_text = ""
    return " ".join(ansage).strip(), rest_text


def stand(sit: dict) -> dict:
    st = sit.get("warteschleife")
    if not isinstance(st, dict):
        st = {}
        sit["warteschleife"] = st
    st.setdefault("n", 0)
    st.setdefault("rein", 0)
    st.setdefault("texte", [])
    st.setdefault("aufgelegt", False)
    return st


def anrufer_hat_gesprochen(sit: dict) -> bool:
    """Steht schon ein echter Anrufer-Satz im Gesprächsverlauf?"""
    for m in sit.get("messages") or []:
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        inhalt = _s(m.get("content"))
        if inhalt and not inhalt.startswith("("):
            return True
    return False


def bewerten(sit: dict, text: str) -> dict[str, Any]:
    """Ansage im gehörten Text? Liefert die Aktion für den Zug.

    {"aktion": "weiter"}                       keine Ansage
    {"aktion": "rest", "text": …, "ansage": …} gemischt — Rest normal verarbeiten
    {"aktion": "warte", "ansage": …}           reine Ansage — still bleiben
    {"aktion": "auflegen", "ansage": …}        Warteschleife erkannt
    """
    if not an():
        return {"aktion": "weiter"}
    ansage, rest = zerlegen(text)
    if not ansage:
        return {"aktion": "weiter"}
    st = stand(sit)
    st["n"] = int(st.get("n") or 0) + 1
    texte = st.setdefault("texte", [])
    if len(texte) < 6:
        texte.append(ansage[:160])
    if rest:
        return {"aktion": "rest", "text": rest, "ansage": ansage}
    st["rein"] = int(st.get("rein") or 0) + 1
    schwelle = AUFLEGEN_AB if anrufer_hat_gesprochen(sit) else AUFLEGEN_AB_OHNE_SPRACHE
    if st["n"] >= schwelle:
        st["aufgelegt"] = True
        return {"aktion": "auflegen", "ansage": ansage}
    return {"aktion": "warte", "ansage": ansage}


def aufgelegt(sit: dict) -> bool:
    """Hat die Wache diesen Anruf beendet? (Report, Portal-Zusammenfassung)"""
    st = sit.get("warteschleife")
    return bool(isinstance(st, dict) and st.get("aufgelegt"))


def zusammenfassung_zeile(sit: dict) -> str:
    """Eine Zeile für Gedächtnis-Report/CallR — nur wenn die Wache eingriff."""
    st = sit.get("warteschleife")
    if not isinstance(st, dict) or not int(st.get("n") or 0):
        return ""
    n = int(st.get("n") or 0)
    if st.get("aufgelegt"):
        return (f"Anruf endete in der Warteschleife der Praxis-Telefonanlage "
                f"({n} Ansagen gehört, kein Anrufer mehr in der Leitung — Bianca hat aufgelegt)")
    return f"Ansage der Praxis-Telefonanlage gehört ({n}x, nicht als Anrufer gewertet)"
