"""W-QWEN-KORREKTOR (13.09.2026): Qwen3-ASR als asynchrones Zweit-Ohr.

Parakeet bleibt das Live-Ohr (0,2-0,4 s je Zug). Qwen (RTX 3060) braucht
fuer denselben Zug 0,4-2,6 s und verliert den Live-Wettlauf fast immer —
sein Ergebnis wurde bis heute WEGGEWORFEN, obwohl es auf den echten
Thaler-Clips vom 11.09.2026 jeden Roentgen-Verhoerer richtig hatte
("Brent Campbellt" / "Rueckenbild" / "Rentenbild" -> "Roentgenbild").
Chef: "das gespraech laeuft ueber parakeet die ganze zeit weiter ...
qwens transkript liegt vor und hat jetzt vorrang und llm versteht im
vergleich zum aktuellen parakeet turn und vorherigen qwen turn das
richtige ... qwen darf nicht live ohr sein um die latenz nicht nach
oben zu treiben."

Zwei Haelften, beide ohne Netz, ohne Modell, ohne Wartezeit im Zug:

1. `nachtrag` (Callback aus `kern.stt`, laeuft im Qwen-Thread): das
   spaete/abgelehnte Qwen-Ergebnis je Zug in der Sitzung merken
   (`qwenSpaet`), Woerterbuch Parakeet-Verhoerer -> Qwen-Wort lernen
   (`qwenWoerter`) und Qwens Inhaltswoerter als Hotwords fuer die
   Parakeet-Nachkorrektur der FOLGE-Zuege bereitstellen (`qwenHotwords`).
2. `anwenden` (VOR Fluss/LLM des naechsten Zugs, im Arbeits-Thread):
   a) Woerterbuch: ein Wort des neuen Zugs, das einem gelernten Verhoerer
      aehnelt, wird durch das Qwen-Wort ersetzt ("Rentenbild" -> "Roentgenbild").
   b) Wiederholung/Widerspruch: sagt der Anrufer (fast) dasselbe noch einmal
      oder widerspricht ("Nein, ..."), und Qwens Text zum VORIGEN Zug ist
      autoritativ und weicht deutlich von Parakeet ab, dann wird der vorige
      Anrufer-Satz im LLM-Verlauf (`sit["messages"]`) auf Qwens Fassung
      umgeschrieben, eine Wiederholung des Verhoerers gilt als Qwens Text,
      und ein einmaliger Prompt-Hinweis nennt die Korrektur.

Nie: Ziffernfolgen aendern (Nummern gehoeren dem Readback-Waechter),
Woerter aus dem Mandanten-Vokabular ueberschreiben (Behandler-Namen sind
Parakeets Hotwords), ohne Signal in den Verlauf schreiben, Zahlwoerter
oder Strukturwoerter lernen, den EIGENEN Zug umschreiben (kommt Qwen
ausnahmsweise noch vor dem Korrektor an, bleibt die Live-Entscheidung des
Ohrs stehen — Qwens Fassung gilt erst ab dem Folgezug).
Notaus: `QWEN_KORREKTOR=0`.
"""

from __future__ import annotations

import os
import re
import time
from difflib import SequenceMatcher
from typing import Any

from kern import spur

# Sitzungs-Deckel: kein unbegrenztes Wachstum in langen Gespraechen.
_MAX_SPAET = 8
_MAX_WOERTER = 24
_MAX_HOTWORDS = 24
# Ab hier gilt ein Qwen-Text als "deutlich anders" als Parakeets Fassung.
_ANDERS_MAX_RATIO = 0.80
# Wiederholung: der neue Zug aehnelt dem vorigen Zug (Parakeet ODER Qwen).
_WIEDERHOLUNG_MIN_RATIO = 0.60
# Woerterbuch-Treffer: unscharfer Wortvergleich gegen gelernte Verhoerer.
_TREFFER_MIN_RATIO = 0.80
_MIN_WORT = 4
_MAX_PHRASE = 3

_ZAHLWORT = {
    "null", "eins", "ein", "eine", "einen", "zwei", "zwo", "drei", "vier",
    "fünf", "fuenf", "sechs", "sieben", "acht", "neun", "zehn", "elf",
    "zwölf", "zwoelf", "hundert", "tausend",
}
_STRUKTUR = {
    "aber", "also", "bitte", "brauche", "bräuchte", "danke", "das", "dass",
    "dem", "den", "der", "die", "doch", "du", "ein", "eine", "einen",
    "für", "gerne", "gern", "habe", "haben", "hat", "hatte", "heute", "ich",
    "ist", "ja", "kann", "kein", "keine", "mein", "meine", "meinen",
    "möchte", "morgen", "nein", "nicht", "noch", "oder", "sie", "sind",
    "termin", "uhr", "um", "und", "uns", "was", "wir", "zu", "zum", "zur",
    "hallo", "guten", "tag", "hier", "dann", "wenn", "wie", "wo", "wann",
    "mit", "von", "vom", "bei", "beim", "auf", "aus", "an", "am", "im", "in",
    "es", "er", "wird", "werden", "würde", "wäre", "sein", "auch", "nur",
    "mal", "schon", "sehr", "bin", "sind", "hab", "einmal", "jetzt", "gut",
    "okay", "genau", "richtig", "falsch", "so", "man", "mir", "mich", "ihnen",
    "ihr", "ihre", "ihren", "sondern", "eigentlich", "vielleicht", "gleich",
    "leider", "wieder", "nochmal", "noch",
}
# Widerspruch/Nachdruck am Satzanfang oder im Satz — der Anrufer korrigiert.
_WIDERSPRUCH_RE = re.compile(
    r"^\W*(?:nein|nee|nö|näh|falsch|nicht|quatsch|ich\s+(?:sagte|habe\s+gesagt|hab\s+gesagt|meinte|meine)|"
    r"noch\s*mal|nochmals|verstehen\s+sie|hören\s+sie)\b"
    r"|\b(?:falsch\s+verstanden|nicht\s+verstanden|meinte\s+ich\s+nicht|sagte\s+ich\s+doch|"
    r"hab(?:e)?\s+ich\s+(?:doch\s+)?gesagt|ich\s+sag(?:e|te)\s+doch|sondern)\b",
    re.I,
)
_WORT_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def an() -> bool:
    return os.environ.get("QWEN_KORREKTOR", "1").strip().lower() not in {"0", "off", "aus", "false"}


def _s(v: Any) -> str:
    return str(v or "").strip()


def _woerter(text: str) -> list[str]:
    return _WORT_RE.findall(_s(text))


def _vergleich(text: str) -> str:
    return " ".join(re.findall(r"\d+|[^\W\d_]+", _s(text).casefold(), re.UNICODE))


def _ziffern(text: str) -> str:
    return "".join(re.findall(r"\d", _s(text)))


def _ratio(a: str, b: str) -> float:
    a, b = _vergleich(a), _vergleich(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _lernbar(wort: str) -> bool:
    w = wort.casefold()
    return len(w) >= _MIN_WORT and w not in _STRUKTUR and w not in _ZAHLWORT


def _vokabular(sit: dict) -> set[str]:
    """Behandler-/Praxis-Woerter des Mandanten: die kommen aus der DB, sind
    Parakeets Hotwords und werden weder gelernt noch ueberschrieben."""
    try:
        from kern import tenants
        namen = tenants.stt_keywords(sit.get("tenant") or {})
    except Exception:
        namen = []
    aus: set[str] = set()
    for n in namen or []:
        for w in _woerter(str(n)):
            aus.add(w.casefold())
    return aus


# ------------------------------------------------------------ Zug-Zaehler

def zug_nr(sit: dict) -> int:
    return int(sit.get("_zugNr") or 0)


def naechster_zug(sit: dict) -> int:
    n = zug_nr(sit) + 1
    sit["_zugNr"] = n
    return n


# --------------------------------------------------------------- Nachtrag

def _lernen(sit: dict, zug: int, parakeet: str, qwen: str, vokabular: set[str]) -> list[str]:
    """Verhoerer-Paare aus Parakeet- und Qwen-Fassung eines Zugs ziehen.

    Token-Alignment per SequenceMatcher: jeder 'replace'-Block mit hoechstens
    _MAX_PHRASE Woertern je Seite wird EIN Paar (auch 2 -> 1: "brent
    campbellt" -> "Röntgenbild"). Streng gefiltert — ein falsch gelerntes Wort
    wuerde Folge-Zuege verfaelschen. Der Quell-Zug wird mitgemerkt
    (`qwenWoerterZug`): ein Paar gilt erst ab dem FOLGE-Zug — im eigenen Zug
    hat das Live-Ohr entschieden, das hebelt der Korrektor nicht aus."""
    p_w, q_w = _woerter(parakeet), _woerter(qwen)
    if not p_w or not q_w:
        return []
    p_cf = [w.casefold() for w in p_w]
    q_cf = [w.casefold() for w in q_w]
    neu: dict[str, str] = {}
    neu_hot: list[str] = []
    gelernt: list[str] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, p_cf, q_cf).get_opcodes():
        if tag != "replace":
            continue
        if not (1 <= i2 - i1 <= _MAX_PHRASE and 1 <= j2 - j1 <= _MAX_PHRASE):
            continue
        garble = " ".join(p_cf[i1:i2])
        richtig = " ".join(q_w[j1:j2])
        richtig_cf = richtig.casefold()
        if garble == richtig_cf:
            continue
        # Qwens Seite muss aus lernbaren Inhaltswoertern bestehen; Parakeets
        # Verhoerer darf Fuellwoerter tragen ("Brennt ein Builder"), aber
        # nicht NUR aus solchen bestehen.
        if not any(_lernbar(w) for w in p_cf[i1:i2]):
            continue
        if not all(_lernbar(w) for w in q_cf[j1:j2]):
            continue
        # Parakeets Fassung traegt ein Mandanten-Wort (Behandler): vertrauen.
        if any(w in vokabular for w in p_cf[i1:i2]):
            continue
        # Phonetisch muss es noch verwandt sein — sonst ist es kein Verhoerer,
        # sondern ein anderer Satz (dann lernt man Unsinn).
        aehnlich = SequenceMatcher(None, garble, richtig_cf).ratio()
        if aehnlich < 0.30 or aehnlich >= 0.97:
            continue
        neu[garble] = richtig
        gelernt.append(f"{garble}->{richtig}")
        for w in q_w[j1:j2]:
            if _lernbar(w) and w.casefold() not in vokabular and w not in neu_hot:
                neu_hot.append(w)
    if not neu:
        return []
    woerter: dict[str, str] = sit.setdefault("qwenWoerter", {})
    quelle: dict[str, int] = sit.setdefault("qwenWoerterZug", {})
    hot: list[str] = sit.setdefault("qwenHotwords", [])
    for garble, richtig in neu.items():
        woerter.pop(garble, None)  # neu einsortieren = juengster Eintrag
        woerter[garble] = richtig
        quelle[garble] = int(zug or 0)
    for w in neu_hot:
        if w not in hot:
            hot.append(w)
    # Deckel (aelteste zuerst raus).
    while len(woerter) > _MAX_WOERTER:
        alt = next(iter(woerter))
        del woerter[alt]
        quelle.pop(alt, None)
    del hot[:-_MAX_HOTWORDS]
    return gelernt


def nachtrag(sit: dict, zug: int, info: dict) -> dict | None:
    """Callback aus `kern.stt` (Qwen-Thread): Ergebnis merken, Woerter lernen,
    Mitschnitt nachtragen. Nie werfend, nie blockierend."""
    if not an() or not isinstance(sit, dict):
        return None
    qwen = _s(info.get("text"))
    parakeet = _s(info.get("parakeet"))
    auth = bool(info.get("authoritative")) and bool(qwen)
    eintrag = {
        "zug": int(zug or 0),
        "parakeet": parakeet,
        "qwen": qwen,
        "auth": auth,
        "reason": _s(info.get("reason")),
        "spaet": bool(info.get("spaet")),
        "s": info.get("s"),
        "t": time.time(),
    }
    liste = sit.setdefault("qwenSpaet", [])
    liste.append(eintrag)
    del liste[:-_MAX_SPAET]
    gelernt: list[str] = []
    anders = bool(qwen and parakeet) and _ratio(parakeet, qwen) < 0.999
    if auth and parakeet and anders and _ziffern(parakeet) == _ziffern(qwen):
        gelernt = _lernen(sit, eintrag["zug"], parakeet, qwen, _vokabular(sit))
    eintrag["gelernt"] = gelernt
    lage = "spaet" if eintrag["spaet"] else "abgelehnt"
    spur.merken(
        sit, "qwen-nachtrag",
        f"z{eintrag['zug']} {lage} auth={int(auth)} qwen={qwen[:60]!r}"
        + (f" gelernt={gelernt}" if gelernt else ""),
    )
    print(f"qwen-korrektor nachtrag z{eintrag['zug']} {lage} auth={int(auth)} "
          f"s={eintrag['s']} parakeet={parakeet[:50]!r} qwen={qwen[:50]!r} "
          f"gelernt={gelernt}", flush=True)
    try:
        from kern import mitschnitt
        mitschnitt.stt_nachtragen(sit, eintrag["zug"], {
            "qwen": qwen, "auth": auth, "s": eintrag["s"],
            "reason": eintrag["reason"], "gelernt": gelernt,
        })
    except Exception as exc:
        print(f"qwen-korrektor mitschnitt fail {type(exc).__name__}: {exc}", flush=True)
    return eintrag


def hotwords(sit: dict) -> list[str]:
    """Qwens Inhaltswoerter als Zusatz-Hotwords fuer Parakeets Nachkorrektur."""
    if not an() or not isinstance(sit, dict):
        return []
    return [str(w) for w in (sit.get("qwenHotwords") or []) if _s(w)]


# --------------------------------------------------------------- Anwenden

def _woerterbuch_anwenden(text: str, woerter: dict[str, str], vokabular: set[str]) -> tuple[str, list[str]]:
    """Gelernte Verhoerer im neuen Zug ersetzen (Wort oder Phrase bis 3 Woerter).

    Unscharf (Ratio >= 0.80), rechts-nach-links ersetzt, nie ueberlappend,
    nie ein Mandanten-Wort, nie Ziffern."""
    if not woerter or not text:
        return text, []
    treffer_liste = [(m.start(), m.end(), m.group(0)) for m in _WORT_RE.finditer(text)]
    if not treffer_liste:
        return text, []
    ersetzungen: list[tuple[int, int, str, str]] = []  # (start, ende, alt, neu)
    belegt: set[int] = set()
    for garble, richtig in woerter.items():
        n = len(garble.split())
        if n < 1 or n > _MAX_PHRASE:
            continue
        for i in range(0, len(treffer_liste) - n + 1):
            if any(k in belegt for k in range(i, i + n)):
                continue
            stueck = treffer_liste[i:i + n]
            phrase = " ".join(w.casefold() for _, _, w in stueck)
            if any(w.casefold() in vokabular for _, _, w in stueck):
                continue
            if phrase == richtig.casefold():
                continue
            if n == 1 and len(phrase) < _MIN_WORT:
                continue
            if phrase == garble or SequenceMatcher(None, phrase, garble).ratio() >= _TREFFER_MIN_RATIO:
                start, ende = stueck[0][0], stueck[-1][1]
                alt = text[start:ende]
                neu = richtig
                # Grossschreibung am Satzanfang uebernehmen.
                if alt[:1].isupper() and neu[:1].islower():
                    neu = neu[:1].upper() + neu[1:]
                ersetzungen.append((start, ende, alt, neu))
                belegt.update(range(i, i + n))
    if not ersetzungen:
        return text, []
    ersetzungen.sort(key=lambda e: e[0], reverse=True)
    aus = text
    protokoll: list[str] = []
    for start, ende, alt, neu in ersetzungen:
        aus = aus[:start] + neu + aus[ende:]
        protokoll.append(f"{alt}->{neu}")
    return aus, list(reversed(protokoll))


def _verlauf_umschreiben(sit: dict, parakeet: str, qwen: str) -> bool:
    """Den vorigen Anrufer-Satz im LLM-Verlauf auf Qwens Fassung setzen."""
    msgs = sit.get("messages")
    if not isinstance(msgs, list) or not parakeet or not qwen:
        return False
    for m in reversed(msgs):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        inhalt = _s(m.get("content"))
        if inhalt == parakeet or _ratio(inhalt, parakeet) >= 0.9:
            m["content"] = qwen
            return True
        return False  # der letzte Anrufer-Satz ist ein anderer — nichts anfassen
    return False


def _letzter_offener(sit: dict, aktueller_zug: int) -> dict | None:
    """Der juengste, noch nicht verwendete Qwen-Nachtrag zum VORIGEN Zug
    (oder dem davor — Qwen kann auch zwei Zuege brauchen).

    Nie der aktuelle Zug selbst: dessen Live-Entscheidung (Parakeet gewann,
    Qwen abgelehnt oder zu spaet) bleibt stehen — Qwen ist nicht das Live-Ohr.
    Erst das Signal des Anrufers im FOLGE-Zug gibt Qwens Fassung den Vorrang."""
    for e in reversed(sit.get("qwenSpaet") or []):
        if not isinstance(e, dict) or e.get("verwendet"):
            continue
        abstand = aktueller_zug - int(e.get("zug") or 0)
        if abstand < 1:
            continue
        if abstand > 2:
            return None
        return e
    return None


def _woerterbuch_gueltig(sit: dict, aktueller_zug: int) -> dict[str, str]:
    """Gelernte Paare OHNE die aus dem aktuellen Zug (s. _lernen)."""
    woerter = sit.get("qwenWoerter") or {}
    quelle = sit.get("qwenWoerterZug") or {}
    return {g: r for g, r in woerter.items() if int(quelle.get(g) or 0) != aktueller_zug}


def anwenden(sit: dict, text: str) -> tuple[str, dict[str, Any]]:
    """Neuen Zug vor Fluss/LLM korrigieren. Gibt (Text, Detail) zurueck;
    Detail ist leer, wenn nichts geschehen ist."""
    text = _s(text)
    if not an() or not isinstance(sit, dict) or not text:
        return text, {}
    detail: dict[str, Any] = {}
    vokabular = _vokabular(sit)
    aktuell = zug_nr(sit)

    # a) Woerterbuch (nur Paare aus FRUEHEREN Zuegen)
    neu, ersetzt = _woerterbuch_anwenden(text, _woerterbuch_gueltig(sit, aktuell), vokabular)
    if ersetzt:
        detail["woerterbuch"] = ersetzt

    # b) Wiederholung/Widerspruch gegen den vorigen Zug
    e = _letzter_offener(sit, aktuell)
    if e and e.get("auth") and e.get("qwen") and e.get("parakeet"):
        para, qwen = _s(e["parakeet"]), _s(e["qwen"])
        anders = _ratio(para, qwen) < _ANDERS_MAX_RATIO
        ziffern_ok = _ziffern(para) == _ziffern(qwen)
        widerspruch = bool(_WIDERSPRUCH_RE.search(text))
        wiederholt_garble = _ratio(text, para) >= _WIEDERHOLUNG_MIN_RATIO
        wiederholt_qwen = _ratio(text, qwen) >= _WIEDERHOLUNG_MIN_RATIO
        # Die Woerterbuch-Ersetzung hat gerade ein Qwen-Wort in den neuen Zug
        # geholt — auch das ist ein Bezug auf den verhoerten Zug.
        bezug = bool(ersetzt) and any(
            w.casefold() in _vergleich(qwen).split() for w in _woerter(neu)
        )
        if anders and ziffern_ok and (widerspruch or wiederholt_garble or wiederholt_qwen or bezug):
            e["verwendet"] = True
            grund = ("widerspruch" if widerspruch else
                     "wiederholung" if (wiederholt_garble or wiederholt_qwen) else "bezug")
            umgeschrieben = _verlauf_umschreiben(sit, para, qwen)
            detail.update({
                "vorzug": True, "grund": grund, "zug": e.get("zug"),
                "parakeetVorher": para, "qwenVorher": qwen, "verlauf": umgeschrieben,
            })
            # Reine Wiederholung des Verhoerers ohne Widerspruchs-Praefix:
            # der Anrufer hat denselben Satz noch einmal gesagt — Qwens Fassung
            # IST der neue Zug (Parakeet hoert ihn sonst zum zweiten Mal falsch).
            if wiederholt_garble and not widerspruch and not wiederholt_qwen and not ersetzt:
                detail["textVorher"] = neu
                neu = qwen
            # Hinweis traegt die Zug-Nummer: er gilt NUR fuer den LLM-Zug zu
            # diesem Anrufer-Satz. Beantwortet die Maschine den Zug ohne
            # Modell, verfaellt er (der Verlauf ist ja schon umgeschrieben)
            # statt einen spaeteren, fremden LLM-Zug zu verwirren.
            sit["qwenKorrekturHinweis"] = {
                "zug": aktuell,
                "text": (
                    "KORREKTUR ZWEIT-OHR (Qwen): Der vorige Satz des Anrufers lautete "
                    f"richtig: „{qwen}“ — das Live-Ohr hatte „{para}“ gehört. Beziehe "
                    "dich auf die richtige Fassung und frage nicht erneut, was gemeint war."
                ),
            }
            spur.merken(sit, "qwen-korrektur",
                        f"{grund} z{e.get('zug')} {para[:40]!r} -> {qwen[:40]!r}"
                        + (" verlauf" if umgeschrieben else ""))
            print(f"qwen-korrektor {grund} z{e.get('zug')} parakeet={para[:50]!r} "
                  f"qwen={qwen[:50]!r} verlauf={int(umgeschrieben)} text={neu[:60]!r}",
                  flush=True)
    if ersetzt and not detail.get("vorzug"):
        spur.merken(sit, "qwen-woerterbuch", ", ".join(ersetzt)[:120])
        print(f"qwen-korrektor woerterbuch {ersetzt} -> {neu[:60]!r}", flush=True)
    if neu != text:
        detail["text"] = neu
        detail.setdefault("textVorher", text)
    return neu, detail


def prompt_hinweis(sit: dict) -> str:
    """Einmaliger Prompt-Block fuer den LLM-Zug, in dem die Korrektur gilt.

    Wird immer verbraucht (pop); Text kommt nur zurueck, wenn der Hinweis zum
    AKTUELLEN Zug gehoert — ein liegengebliebener Hinweis aus einem
    Maschinen-Zug erreicht das Modell nie."""
    if not isinstance(sit, dict):
        return ""
    h = sit.pop("qwenKorrekturHinweis", None)
    if isinstance(h, dict):
        if int(h.get("zug") or 0) != zug_nr(sit):
            return ""
        return _s(h.get("text"))
    return _s(h)


def anzeige(sit: dict | None = None) -> str:
    return "an" if an() else "aus (QWEN_KORREKTOR=0)"
