"""Fuzzy-Nachkorrektur von STT-Transkripten gegen eine Hotword-Liste.

KOPIE von F:\\Clara-Voice-dev\\services\\stt_postcorrect.py (Clara V7, 28.08.2026) —
Claras seit Monaten bewaehrte Telefon-Strecke, uebernommen fuer Lisa/Bianca
(Chef 28.08.2026: "alle besten und bewaehrtesten Entwicklungsstufen von
Clara V7 und Demo Clara"). Bewusst Kopie statt Import: dieses Repo darf
Clara-Voice nie anfassen. Aenderungen hier fliessen NICHT nach Clara zurueck.

Zweck: Engines ohne Hotword-/initial_prompt-Support (z. B. Parakeet ueber
onnx-asr) sollen seltene Eigennamen trotzdem treffen. Wir vergleichen jedes
namensverdaechtige Token (und benachbarte Token-Paare wie "Kuriyaki Dou")
unscharf gegen die mitgesendeten Keywords und ersetzen knappe Hoerfehler:

    "Vassiliu"      -> "Vassiliou"
    "Tranorf"       -> "Thrandorf"
    "Kuriyaki-Dou"  -> "Kyriakidou"
    "Häuser"        -> "Heuser"   (Firmenname im Praxiskontext)

Bewusst konservativ: nur grossgeschriebene Tokens ab 4 Zeichen, hohe
Aehnlichkeitsschwelle, haeufige deutsche Woerter sind tabu. Stdlib-only
(difflib), damit der Container es ohne neue Abhaengigkeit nutzt.
"""
from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

# Haeufige grossgeschriebene Woerter, die NIE zu Namen korrigiert werden
# duerfen (Satzanfaenge, Anreden, Wochentage, Praxis-Vokabular).
_STOPWORDS = {
    "herr", "herrn", "frau", "doktor", "praxis", "termin", "termine",
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag",
    "sonntag", "morgen", "heute", "gestern", "woche", "uhr", "bitte",
    "danke", "hallo", "guten", "kalender", "patienten", "patient",
    "unterlagen", "rechnung", "email", "mail", "nummer", "telefon",
    "nachricht", "team", "chef", "recall", "luecke", "luecken",
    "zahnreinigung", "kontrolle", "krone", "schiene", "behandlung",
    "wann", "wer", "was", "wie", "kannst", "schick", "simse", "sage",
    "lisa", "nadine", "clara", "bianca",
}

_TOKEN_RE = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]+")

# ---------------------------------------------------------------------------
# Buchstabiertes Zuhoeren (Clara V7, Vorfall 16.08.2026) — Kopie.
# "T-Z-A-N-N-I-S" / "T wie Theodor, Z wie Zeppelin, …" wird ZUERST zum
# Namen, danach greift die Fuzzy-Korrektur gegen die Keyword-Liste.
# ---------------------------------------------------------------------------
_BUCHSTABIERTAFEL: dict[str, str] = {
    "anton": "A", "ärger": "Ä", "aerger": "Ä", "berta": "B", "bertha": "B",
    "cäsar": "C", "caesar": "C", "cesar": "C", "charlotte": "CH",
    "david": "D", "dora": "D", "emil": "E", "friedrich": "F", "fritz": "F",
    "gustav": "G", "heinrich": "H", "ida": "I", "julius": "J",
    "kaufmann": "K", "konrad": "K", "ludwig": "L", "martha": "M",
    "marta": "M", "nordpol": "N", "nathan": "N", "otto": "O",
    "ökonom": "Ö", "oekonom": "Ö", "paula": "P", "quelle": "Q",
    "richard": "R", "rudolf": "R", "samuel": "S", "siegfried": "S",
    "schule": "SCH", "theodor": "T", "toni": "T", "ulrich": "U",
    "übermut": "Ü", "uebermut": "Ü", "viktor": "V", "victor": "V",
    "wilhelm": "W", "xanthippe": "X", "xaver": "X", "ypsilon": "Y",
    "zacharias": "Z", "zeppelin": "Z", "eszett": "ß", "esszett": "ß",
}
_BUCHSTABENKETTE_RE = re.compile(
    r"\b(?:[A-ZÄÖÜ](?:\s*[-–.]\s*|\s+)){3,}[A-ZÄÖÜ]\b")
_BUCHSTABIER_MIN = 3
_WIE_GLIED = r"[A-Za-zÄÖÜäöü]\s+wie\s+(?:in\s+)?[A-Za-zÄÖÜäöüß]+"
_WIE_KETTE_RE = re.compile(
    rf"\b{_WIE_GLIED}(?:\s*[,;]?\s*(?:und\s+)?{_WIE_GLIED})"
    rf"{{{_BUCHSTABIER_MIN - 1},}}",
    re.IGNORECASE)
_WIE_BUCHSTABE_RE = re.compile(r"\b([A-Za-zÄÖÜäöü])\s+wie\s", re.IGNORECASE)


def _kette_zusammenziehen(m: "re.Match[str]") -> str:
    return "".join(re.findall(r"[A-ZÄÖÜ]", m.group(0))).title()


def _wie_kette_zusammenziehen(m: "re.Match[str]") -> str:
    return "".join(_WIE_BUCHSTABE_RE.findall(m.group(0))).upper().title()


def buchstabiertes_zusammenziehen(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Buchstabierte Namen zu einem Wort: T-Z-A-N-N-I-S / T wie Theodor …"""
    if not text:
        return text, []
    ersetzungen: list[tuple[str, str]] = []
    neu = _WIE_KETTE_RE.sub(
        lambda m: (ersetzungen.append((m.group(0), _wie_kette_zusammenziehen(m)))
                   or _wie_kette_zusammenziehen(m)),
        text)
    neu = _BUCHSTABENKETTE_RE.sub(
        lambda m: (ersetzungen.append((m.group(0), _kette_zusammenziehen(m)))
                   or _kette_zusammenziehen(m)),
        neu)
    treffer = list(re.finditer(r"[A-Za-zÄÖÜäöüß]+", neu))
    laeufe: list[tuple[int, int]] = []
    start: int | None = None
    for i, m in enumerate(treffer):
        if m.group().lower() in _BUCHSTABIERTAFEL:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= _BUCHSTABIER_MIN:
                laeufe.append((start, i))
            start = None
    if start is not None and len(treffer) - start >= _BUCHSTABIER_MIN:
        laeufe.append((start, len(treffer)))
    for von, bis in reversed(laeufe):
        a, b = treffer[von].start(), treffer[bis - 1].end()
        wort = "".join(_BUCHSTABIERTAFEL[treffer[i].group().lower()]
                       for i in range(von, bis)).title()
        ersetzungen.append((neu[a:b], wort))
        neu = neu[:a] + wort + neu[b:]
    return neu, ersetzungen


# Patiententelefon (immer an, ohne Marker): STT-Garbles aus echten Bianca-
# Gespraechen. Heads-up/Teleskop/Kons bleiben marker-gated wie bei Clara.
_TELEFON_PHRASE_FIXES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bwelcher\s+ta(?:cken|gen|ck|ggen)\b", re.IGNORECASE), "welcher Tag"),
    (re.compile(r"\bwurzelkanal(?:behandlung)?\b", re.IGNORECASE), "Wurzelbehandlung"),
    (re.compile(r"\bnachmittach\b", re.IGNORECASE), "Nachmittag"),
    (re.compile(r"\bvormittach\b", re.IGNORECASE), "Vormittag"),
    # Clara-V7-Dental-Garbles, die Patienten sagen — ohne Teleskop/Kons-Marker.
    (re.compile(r"\bz[uü]lung\b", re.IGNORECASE), "Füllung"),
    (re.compile(r"\bcovidus\b", re.IGNORECASE), "Karies"),
    (re.compile(r"\bkarie\b", re.IGNORECASE), "Karies"),
    (re.compile(r"\bf2ud\b", re.IGNORECASE), "Füllung MOD"),
]

# Deterministische PHRASEN-Korrekturen (Clara 07.07.2026): Parakeet hoert das
# Kommando "Heads up" regelmaessig als "Hands up" / "Herz up" / "Hat's up" /
# "Head App". Die Token-Fuzzy-Logik unten kann Mehrwort-Phrasen nicht
# treffen. Diese Fixes laufen NUR, wenn die Keywords das Marker-Keyword
# "Heads-up" tragen — Lisa/Bianca (Patiententelefon) senden die Marker nicht
# und bleiben byte-identisch.
_PHRASE_FIXES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:hands?|hat'?s|herz|heads?)[ -]?(?:up|app)\b", re.IGNORECASE),
     "Heads-up"),
]
_PHRASE_MARKERS = {"headsup"}

# Dental-Garbles (Clara-Live-Befund 21./22.07.). NUR wenn die Keywords den
# Marker "Teleskopkrone" tragen — Patiententelefon bleibt byte-identisch.
_DENTAL_PHRASE_FIXES: list[tuple[re.Pattern, str]] = [
    (re.compile(
        r"\b(?:ein(?:e|zig(?:e|en)?)?\s+)?(?:sex|sechs(?:t)?)\s*[-]?\s*teleskop"
        r"(?:\s*[-]?\s*krone)?\b",
        re.IGNORECASE,
    ), "Teleskopkrone"),
    (re.compile(r"\btelesco\b", re.IGNORECASE), "Teleskop"),
    (re.compile(r"\bz[uü]lung\b", re.IGNORECASE), "Füllung"),
    (re.compile(r"\bcovidus\b", re.IGNORECASE), "Karies"),
    (re.compile(r"\bf2ud\b", re.IGNORECASE), "Füllung MOD"),
    (re.compile(r"\bkarie\b", re.IGNORECASE), "Karies"),
    (re.compile(r"\bdistar\b", re.IGNORECASE), "distal"),
    (re.compile(r"\boctosal(?:distale?)?", re.IGNORECASE),
     lambda m: "okklusal distal" if "distal" in m.group(0).lower() else "okklusal"),
]
_DENTAL_PHRASE_MARKERS = {"teleskopkrone"}

# Fachbereichs-Antwort "Kons" (Clara-Live 28.07.2026): Das kurze "Kons" kam
# als "Cont." bzw. "Funks." an. NUR aktiv, wenn die Keywords das Marker-
# Keyword "Kons" tragen. Nur alleinstehende Tokens (\b..\b) — "Konzept"/
# "Kontrolle" bleiben unangetastet.
_KONS_PHRASE_FIXES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:cont|conz|konz|cons|kohns|funks|konst)\b", re.IGNORECASE), "Kons"),
]
_KONS_PHRASE_MARKERS = {"kons"}


# Deutsche STT-Verwechslungen am WORTANFANG (Clara-Live-Befund: "Zannis"/
# "Tzannis", "Betsas"/"Petsas", "Gaufmann"/"Kaufmann", "Kerber"/"Gerber").
# Der Bucket-Lookup schlug sonst nur im Bucket mit gleichem Anfangsbuchstaben
# nach und verpasste diese haeufigen Anlaut-Hoerfehler komplett. Wir suchen
# daher zusaetzlich in den Buckets phonetisch verwandter Anlaute. Die hohe
# Aehnlichkeitsschwelle bleibt unveraendert -> nur wirklich knappe Treffer
# werden ersetzt (kein neues Fehl-Snap-Risiko).
_INITIAL_GROUPS: tuple[frozenset[str], ...] = (
    frozenset("tdz"),   # T / D / Z (Dentale + Affrikate: "Tz..." -> "Z...")
    frozenset("zsc"),   # Z / S / C (Sibilanten)
    frozenset("pb"),    # P / B (stimmhaft/stimmlos)
    frozenset("kgc"),   # K / G / C (Velare)
    frozenset("fvw"),   # F / V / W (Frikative)
)


def _build_initial_confuse() -> dict[str, tuple[str, ...]]:
    table: dict[str, tuple[str, ...]] = {}
    for ch in "abcdefghijklmnopqrstuvwxyzäöüß":
        alts = {ch}
        for grp in _INITIAL_GROUPS:
            if ch in grp:
                alts |= grp
        table[ch] = tuple(sorted(alts))
    return table


_INITIAL_CONFUSE = _build_initial_confuse()


def _norm(s: str) -> str:
    # y klingt im Deutschen wie i (Hayla/Haila, Meyer/Meier) — Clara V7.
    return re.sub(r"[^a-zäöüß]", "", s.lower()).replace("y", "i")


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _threshold(length: int) -> float:
    # Kurze Tokens brauchen fast exakte Treffer, lange duerfen unschaerfer sein.
    # 0.82 statt 0.84, damit "Zanis" -> "Tzannis" (0.833) noch greift.
    if length <= 5:
        return 0.82
    if length <= 8:
        return 0.78
    return 0.74


def _index(keywords: list[str]) -> tuple[dict[tuple[str, int], list[tuple[str, str]]], set[str]]:
    """Laengen-/Anfangsbuchstaben-Register der Keywords (siehe correct_transcript)."""
    kw = [(k, _norm(k)) for k in keywords
          if k and " " not in k.strip() and len(_norm(k)) >= 4]
    by_key: dict[tuple[str, int], list[tuple[str, str]]] = defaultdict(list)
    for orig, norm in kw:
        by_key[(norm[0], len(norm))].append((orig, norm))
    return by_key, {n for _, n in kw}


def _ranked_matches(
    norm_token: str,
    by_key: dict[tuple[str, int], list[tuple[str, str]]],
    limit: int = 3,
) -> list[tuple[str, float]]:
    """Beste Namenskandidaten zu einem Token, absteigend nach Aehnlichkeit."""
    seen: dict[str, float] = {}
    nlen = len(norm_token)
    for first in _INITIAL_CONFUSE.get(norm_token[0], (norm_token[0],)):
        for L in range(max(4, nlen - 2), nlen + 3):
            for orig, norm in by_key.get((first, L), ()):
                r = _ratio(norm_token, norm)
                if r > seen.get(orig, 0.0):
                    seen[orig] = r
    return sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


# Anreden, nach denen ein Name FOLGEN MUSS. Steht dort ein Wort, das in der
# Praxisliste nirgends anklingt, hat die Erkennung den Namen sehr wahrscheinlich
# verfehlt -- genau dann darf nicht gehandelt, sondern muss nachgefragt werden.
_TITLE_RE = re.compile(r"(?i)^(herr|herrn|frau|doktor|dr)$")
# Ab hier klingt ein Name "aehnlich genug", um ihn als Rueckfrage-Vorschlag zu
# nennen (unter der Ersetzungsschwelle, sonst haette die Korrektur zugegriffen).
_HINT_MIN = 0.62


def assess_name_certainty(text: str, keywords: list[str], *, margin: float = 0.05) -> dict:
    """Prueft, ob ein gehoerter Name ZWEIFELHAFT ist.

    Gedacht als Sicherung vor schreibenden Aktionen (absagen, verschieben,
    buchen): Lieber einmal gezielt nachfragen als den falschen Patienten
    erwischen. Rein rechnerisch, kein Modellaufruf, daher ohne Zeitkosten.

    Zwei Zweifelsfaelle:
      * ``mehrdeutig`` -- zwei Praxisnamen klingen fast gleich gut (Abstand
        kleiner ``margin``), z. B. "Thermos" zwischen "Dermatis" und "Termas".
      * ``unbekannt``  -- nach einer Anrede ("Frau ...") steht ein Wort, das in
        der Praxisliste nirgends anklingt.

    Liefert ``{"unsicher": bool, "wort": str, "grund": str,
    "kandidaten": [str, ...]}``. Ohne Zweifel: ``unsicher`` = False.
    """
    leer = {"unsicher": False, "wort": "", "grund": "", "kandidaten": []}
    if not text or not keywords:
        return leer
    by_key, kw_norms = _index(keywords)
    if not kw_norms:
        return leer
    matches = list(_TOKEN_RE.finditer(text))
    for i, m in enumerate(matches):
        tok = m.group()
        norm = _norm(tok)
        if len(norm) < 4 or norm in _STOPWORDS or not tok[0].isupper():
            continue
        if norm in kw_norms:
            continue  # exakter Treffer -> sicher
        ranked = _ranked_matches(norm, by_key)
        best = ranked[0][1] if ranked else 0.0
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        schwelle = _threshold(len(norm))
        if best >= schwelle and second >= schwelle and (best - second) <= margin:
            return {"unsicher": True, "wort": tok, "grund": "mehrdeutig",
                    "kandidaten": [name for name, _ in ranked[:2]]}
        if best < schwelle:
            vorher = _norm(matches[i - 1].group()) if i > 0 else ""
            if vorher and _TITLE_RE.match(vorher):
                return {"unsicher": True, "wort": tok, "grund": "unbekannt",
                        "kandidaten": [name for name, r in ranked if r >= _HINT_MIN][:2]}
    return leer


def correct_transcript(text: str, keywords: list[str]) -> tuple[str, list[tuple[str, str]]]:
    """Korrigiert namensverdaechtige Tokens gegen die Keyword-Liste.

    Liefert (korrigierter Text, Liste der Ersetzungen). Mehrwort-Keywords
    werden ignoriert; benachbarte Token-Paare werden zusaetzlich als
    zusammengezogenes Wort geprueft (STT zerhackt lange Namen gern).
    """
    if not text:
        return text, []
    # Buchstabiertes zuerst — auch ohne Keywords (Clara V7; dort hing das
    # an keywords und blieb bei leerer Liste stumm).
    text, replacements_pre = buchstabiertes_zusammenziehen(text)
    for pat, repl in _TELEFON_PHRASE_FIXES:
        def _tel_sub(m: "re.Match[str]", _repl=repl) -> str:
            if _norm(m.group(0)) != _norm(_repl):
                replacements_pre.append((m.group(0), _repl))
            return _repl
        text = pat.sub(_tel_sub, text)
    if not keywords:
        return text, replacements_pre
    marker_norms = {_norm(k) for k in keywords if k}
    if marker_norms & _PHRASE_MARKERS:
        for pat, repl in _PHRASE_FIXES:
            def _sub(m: "re.Match[str]") -> str:
                if _norm(m.group(0)) != _norm(repl):
                    replacements_pre.append((m.group(0), repl))
                return repl
            text = pat.sub(_sub, text)
    if marker_norms & _DENTAL_PHRASE_MARKERS:
        for pat, repl in _DENTAL_PHRASE_FIXES:
            def _dent_sub(m: "re.Match[str]", _repl=repl) -> str:
                out = _repl(m) if callable(_repl) else _repl
                if _norm(m.group(0)) != _norm(out):
                    replacements_pre.append((m.group(0), out))
                return out
            text = pat.sub(_dent_sub, text)
    if marker_norms & _KONS_PHRASE_MARKERS:
        for pat, repl in _KONS_PHRASE_FIXES:
            def _kons_sub(m: "re.Match[str]", _repl=repl) -> str:
                if _norm(m.group(0)) != _norm(_repl):
                    replacements_pre.append((m.group(0), _repl))
                return _repl
            text = pat.sub(_kons_sub, text)
    kw = [(k, _norm(k)) for k in keywords
          if k and " " not in k.strip() and len(_norm(k)) >= 4]
    if not kw:
        return text, replacements_pre
    kw_norms = {n for _, n in kw}
    # Laengen- + Anfangsbuchstaben-Buckets: bei mehreren tausend Praxisnamen
    # sonst O(N*Tokens) pro Utterance. +-2 Zeichen Laenge + gleicher Start
    # reichen fuer typische STT-Garbles.
    by_key: dict[tuple[str, int], list[tuple[str, str]]] = defaultdict(list)
    for orig, norm in kw:
        by_key[(norm[0], len(norm))].append((orig, norm))

    replacements: list[tuple[str, str]] = []
    matches = list(_TOKEN_RE.finditer(text))
    out = text
    used: set[int] = set()

    def best_match(norm_token: str) -> tuple[str, float]:
        best, score = "", 0.0
        nlen = len(norm_token)
        firsts = _INITIAL_CONFUSE.get(norm_token[0], (norm_token[0],))
        for first in firsts:
            for L in range(max(4, nlen - 2), nlen + 3):
                for orig, norm in by_key.get((first, L), ()):
                    r = _ratio(norm_token, norm)
                    if r > score:
                        best, score = orig, r
                        if score >= 0.99:
                            return best, score
        return best, score

    # 1) Token-Paare (zerhackte Namen wie "Kuriyaki Dou" / "Kuriyaki-Dou").
    pair_repl: list[tuple[int, int, str]] = []
    for i in range(len(matches) - 1):
        a, b = matches[i], matches[i + 1]
        # Nur direkt benachbart (max. 1 Trennzeichen dazwischen).
        if b.start() - a.end() > 1:
            continue
        if not (a.group()[0].isupper() and (b.group()[0].isupper() or "-" in text[a.end():b.start() + 1])):
            continue
        if _norm(a.group()) in _STOPWORDS or _norm(b.group()) in _STOPWORDS:
            continue
        joined = _norm(a.group() + b.group())
        if len(joined) < 6 or joined in kw_norms:
            continue
        cand, score = best_match(joined)
        if score >= _threshold(len(joined)) and _norm(cand) != joined:
            pair_repl.append((a.start(), b.end(), cand))
            used.add(i)
            used.add(i + 1)

    # 2) Einzel-Tokens.
    single_repl: list[tuple[int, int, str]] = []
    for i, m in enumerate(matches):
        if i in used:
            continue
        tok = m.group()
        norm = _norm(tok)
        if len(norm) < 4 or norm in _STOPWORDS or not tok[0].isupper():
            continue
        if norm in kw_norms:
            continue  # schon korrekt
        cand, score = best_match(norm)
        if score >= _threshold(len(norm)) and _norm(cand) != norm:
            single_repl.append((m.start(), m.end(), cand))

    # Von hinten ersetzen, damit die Offsets stabil bleiben.
    for start, end, cand in sorted(pair_repl + single_repl, reverse=True):
        replacements.append((text[start:end], cand))
        out = out[:start] + cand + out[end:]
    replacements.reverse()
    return out, replacements_pre + replacements
