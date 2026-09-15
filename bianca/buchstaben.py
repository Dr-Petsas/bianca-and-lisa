"""Buchstabier-Verstehen für Namen am Telefon (rein, ohne Netz).

Versteht die drei Formen, die am Telefon wirklich vorkommen:
  "M wie Martha, Ü wie Übermut, L wie Ludwig ..."
  "M-Ü-L-L-E-R" / "M Ü L L E R" (auch als STT-Kleinbuchstaben)
  "Müller, M wie Martha, Ü wie Übermut ..." (Name plus Buchstabierung)
Dazu "Doppel-L", "A Umlaut", "scharfes S" und gesprochene Buchstabennamen
("emm", "zett"). Ergebnis ist der zusammengesetzte Name plus ein
Sicher-Kennzeichen, wenn ein mitgesprochenes Wort die Buchstabierung bestätigt.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

# Buchstabier-Wörter -> Buchstabe. DIN-Tafel plus die gängigen freien Varianten
# (Menschen sagen "M wie Maria" genauso oft wie "M wie Martha").
_TAFEL: dict[str, str] = {
    "anton": "a", "alfa": "a", "alpha": "a", "anna": "a", "adam": "a",
    "ärger": "ä", "aerger": "ä",
    "berta": "b", "bruno": "b", "bravo": "b", "bernd": "b",
    "cäsar": "c", "caesar": "c", "cesar": "c", "charlotte": "c", "christian": "c",
    "dora": "d", "david": "d", "delta": "d", "daniel": "d",
    "emil": "e", "echo": "e", "erich": "e", "emma": "e",
    "friedrich": "f", "fritz": "f", "foxtrot": "f", "felix": "f", "frieda": "f",
    "gustav": "g", "georg": "g", "golf": "g",
    "heinrich": "h", "hans": "h", "hotel": "h", "heinz": "h",
    "ida": "i", "india": "i", "ingrid": "i",
    "julius": "j", "julia": "j", "johann": "j", "juliett": "j",
    "kaufmann": "k", "konrad": "k", "kilo": "k", "karl": "k",
    "ludwig": "l", "leopold": "l", "lima": "l", "lisa": "l",
    "martha": "m", "marie": "m", "maria": "m", "mike": "m", "max": "m",
    "nordpol": "n", "norbert": "n", "november": "n",
    "otto": "o", "oskar": "o", "oscar": "o",
    "ökonom": "ö", "oekonom": "ö", "österreich": "ö", "oesterreich": "ö",
    "paula": "p", "peter": "p", "papa": "p", "paul": "p",
    "quelle": "q", "quebec": "q",
    "richard": "r", "romeo": "r", "rudolf": "r",
    "samuel": "s", "siegfried": "s", "sierra": "s", "sophie": "s",
    "theodor": "t", "tango": "t", "toni": "t", "theo": "t",
    "ulrich": "u", "uniform": "u", "ulla": "u",
    "übermut": "ü", "uebermut": "ü", "übung": "ü", "uebung": "ü",
    "viktor": "v", "victor": "v",
    "wilhelm": "w", "whiskey": "w", "willi": "w",
    "xanthippe": "x", "xaver": "x",
    "ypsilon": "y", "yankee": "y",
    "zacharias": "z", "zeppelin": "z", "zulu": "z",
    "eszett": "ß",
}

# Gesprochene Buchstabennamen, wie STT sie schreibt ("emm", "ell", "zett").
_LAUT: dict[str, str] = {
    "ah": "a", "be": "b", "beh": "b", "ce": "c", "ceh": "c", "zeh": "c",
    "de": "d", "deh": "d", "eff": "f", "ef": "f", "ge": "g", "geh": "g",
    "ha": "h", "jot": "j", "ka": "k", "kah": "k", "el": "l", "ell": "l",
    "em": "m", "emm": "m", "en": "n", "enn": "n", "pe": "p", "peh": "p",
    "ku": "q", "kuh": "q", "er": "r", "err": "r", "es": "s", "ess": "s",
    "te": "t", "teh": "t", "uh": "u", "vau": "v", "fau": "v",
    "we": "w", "weh": "w", "iks": "x", "ix": "x", "üpsilon": "y",
    "zet": "z", "zett": "z",
}

_UMLAUT = {"a": "ä", "o": "ö", "u": "ü"}
_FUELL = {
    "und", "dann", "also", "genau", "bitte", "noch", "einmal", "nochmal",
    "der", "die", "das", "mein", "name", "nachname", "vorname", "ist",
    "heißt", "heisst", "sich", "schreibt", "man", "so", "ja", "okay",
    "buchstabiere", "buchstabiert", "ich", "gerne", "gern",
    "äh", "ähm", "eh", "ehm", "hm", "mhm",
}

# Für das Rückwärts-Buchstabieren (Bianca liest vor): eine feste, klare Tafel.
_VORLESE: dict[str, str] = {
    "a": "Anton", "ä": "Ärger", "b": "Berta", "c": "Cäsar", "d": "Dora",
    "e": "Emil", "f": "Friedrich", "g": "Gustav", "h": "Heinrich", "i": "Ida",
    "j": "Julius", "k": "Konrad", "l": "Ludwig", "m": "Martha", "n": "Nordpol",
    "o": "Otto", "ö": "Ökonom", "p": "Paula", "q": "Quelle", "r": "Richard",
    "s": "Samuel", "t": "Theodor", "u": "Ulrich", "ü": "Übermut", "v": "Viktor",
    "w": "Wilhelm", "x": "Xanthippe", "y": "Ypsilon", "z": "Zacharias",
    "ß": "Eszett",
}

_EINZEL = set("abcdefghijklmnopqrstuvwxyzäöüß")

# Diktat-Schlusswoerter. Sie BEENDEN die Buchstabierung und gehoeren NIE zum
# Namen (W-DIKTAT-FERTIG 13.09.2026, Anruf 1fbda5db — Chef: "obwohl ich nach
# dem buchstabieren fertig sage und bianca den namen rateike erkennt, nennt
# sie mich spaeter rateike fertig.... was wird in das session brain
# geschrieben?!"). Live wurde aus "Rateike, R-A-T-E-I-K-E, fertig." der
# Nachname "Rateikefertig": ``teil`` kannte die Woerter, ``deute`` nicht — dort
# lief "fertig" als Anschluss-Wort in die Suffix-Fuge. Der Schwanz wird
# deshalb VOR dem Zerlegen abgeschnitten.
_ENDE_RE = re.compile(
    r"(?:[\s,.;:!?-]*\b(?:fertig|ende|gewesen|danke|das\s+war(?:'s|s|\s+es)?|"
    r"mehr\s+nicht|war\s+es)\b)+[\s,.;:!?-]*$", re.I)

# Blessing-Liveketten 15.09.2026:
# - „C wie Cäsar, O“ kam bei Parakeet als C-V-C-S-A-O bzw. C-B-C-S-A-O.
# - „R-E-N-C-O“ kam als R-EN-C-O; das zusammengeklebte EN wurde danach als
#   gesprochener Buchstabenname N gelesen und das E ging verloren.
# Diese Normalisierung wird NUR über ``deute_feldsegment`` verwendet. Der
# bisherige Standardparser bleibt für alle anderen Mandanten byte-identisch.
_ZERHACKTES_CAESAR_RE = re.compile(
    r"\bC(?:\s*-\s*|\s+)[BV](?:\s*-\s*|\s+)C"
    r"(?:\s*-\s*|\s+)S(?:\s*-\s*|\s+)A"
    r"(?=(?:\s*-\s*|\s+)O\b)",
    re.I,
)
_EXPLIZITE_KETTE_RE = re.compile(
    r"\b(?:[A-ZÄÖÜ](?:\s*-\s*[A-ZÄÖÜ]{1,4}){2,})\b"
)
_NEUES_WORT_RE = re.compile(
    r"\b(?:neues?|nächstes?|naechstes?|weiteres?)\s+wort\b",
    re.I,
)


def _ende_ab(text: str) -> str:
    """Diktat-Schlusswort am Satzende abschneiden ("… E, fertig." -> "… E")."""
    gekappt = _ENDE_RE.sub("", _s(text)).strip(" ,.;:!?-")
    # Nur das Schlusswort allein ("Fertig.") darf nicht zu einem leeren Satz
    # werden — dann bliebe die Kette ohne Bezug und `deute` liefe auf None.
    return gekappt if gekappt else _s(text)


def ohne_schlusswort(text: str) -> str:
    """Öffentliche Form für Name plus Diktat-Ende („Gavranides, fertig“)."""
    return _ende_ab(text)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _tokens(text: str) -> list[str]:
    raw = _s(text).lower()
    raw = re.sub(r"[.,;:!?/'’]+", " ", raw)
    # "m-ü-l-l-e-r" -> einzelne Buchstaben; "wie-maria" bleibt trennbar
    raw = raw.replace("-", " ")
    return [t for t in raw.split() if t]


def _als_buchstabe(tok: str) -> str:
    if len(tok) == 1 and tok in _EINZEL:
        return tok
    return _LAUT.get(tok, "")


def _name_nach_also(toks: list[str]) -> str:
    """Wort nach 'also'/'genau', das die Schreibweise bestätigt."""
    skip = _FUELL | {"der", "die", "das", "den", "dem"}
    for i, tok in enumerate(toks):
        if tok not in {"also", "genau"}:
            continue
        j = i + 1
        while j < len(toks) and toks[j] in skip:
            j += 1
        if j >= len(toks):
            continue
        w = toks[j]
        if w.isalpha() and len(w) >= 6 and w not in _TAFEL:
            return w
    return ""


def _name_anker_vor_also(toks: list[str], kandidat: str) -> bool:
    """Hat der Kandidat vor „also/genau“ einen ähnlich gesprochenen Namen?

    Ohne diesen Anker wurde normale Prosa wie „aus dem Kalender, also
    entfernen“ als sicher buchstabierter Nachname „Entfernen“ gelesen.
    """
    stop = next(
        (i for i, tok in enumerate(toks) if tok in {"also", "genau"}),
        len(toks),
    )
    for tok in toks[:stop]:
        if not tok.isalpha() or len(tok) < 4 or tok in _FUELL or tok in _TAFEL:
            continue
        if difflib.SequenceMatcher(None, tok, kandidat).ratio() >= 0.55:
            return True
    return False


_TAFEL_KEYS = sorted(_TAFEL)


def _tafel_anlaute(toks: list[str]) -> list[str]:
    """Buchstabiertafel-Woerter im Satz (auch verhoert: "Nordpool", "Bertha")
    -> ihre Anlaute in Sprechreihenfolge.

    STT zerlegt "K wie Kaufmann, A wie Anton" live gern zu "Kavi Kaufmann,
    Avi Anton" (Batch s14/s17 29.08.2026) — die Tafel-Woerter selbst kommen
    aber fast immer durch. Fuzzy-Abgleich ab 4 Zeichen, konservativ 0.8."""
    anlaute: list[str] = []
    for tok in toks:
        if tok in _FUELL or tok == "wie" or not tok.isalpha():
            continue
        if tok in _TAFEL:
            anlaute.append(_TAFEL[tok])
            continue
        if len(tok) >= 4:
            m = difflib.get_close_matches(tok, _TAFEL_KEYS, n=1, cutoff=0.8)
            if m:
                anlaute.append(_TAFEL[m[0]])
    return anlaute


def _fuzzy_tafel_fragment(toks: list[str]) -> str:
    """Stark verschliffenes ``X wie Tafelwort`` als EINEN Buchstaben retten.

    Whisper liefert bei isolierten Buchstabierclips unter anderem
    ``Zwiesacher Rias`` statt ``Z wie Zacharias``. Der Abgleich ist nur bei
    klarer bester Tafelphrase erlaubt; Gleichstände bleiben leer.
    """
    ignorieren = _FUELL | {"fertig", "ende", "wars", "gewesen"}
    gehoert = "".join(t for t in toks if t not in ignorieren)
    if len(gehoert) < 4:
        return ""
    pro_buchstabe: dict[str, float] = {}
    for wort, letter in _TAFEL.items():
        for soll in (
            f"{letter}wie{wort}",
            f"{letter}vi{wort}",
            f"wie{wort}",
            wort,
        ):
            score = difflib.SequenceMatcher(None, gehoert, soll).ratio()
            pro_buchstabe[letter] = max(pro_buchstabe.get(letter, 0.0), score)
    rang = sorted(pro_buchstabe.items(), key=lambda x: (-x[1], x[0]))
    if not rang or rang[0][1] < 0.72:
        return ""
    zweit = rang[1][1] if len(rang) > 1 else 0.0
    return rang[0][0] if rang[0][1] - zweit >= 0.08 else ""


def deute(text: str) -> dict[str, Any] | None:
    """Buchstabierung erkennen und zusammensetzen.

    Rückgabe {"name": "Müller", "sicher": bool} oder None, wenn der Satz
    keine Buchstabierung ist. "sicher" wird gesetzt, wenn ein zusammenhängend
    gesprochenes Wort im Satz exakt dem zusammengesetzten Namen entspricht.
    """
    toks = _tokens(_ende_ab(text))
    if not toks:
        return None
    letters: list[str] = []
    woerter: list[str] = []  # zusammenhängende Nicht-Buchstabier-Wörter
    anschluss: list[str] = []  # Wörter DIREKT hinter der Buchstabier-Kette
    fremd = 0
    kette = False   # sind wir gerade IN einer Buchstabier-Folge?
    fuell_folge = 0  # wie viele Füllwörter seit dem letzten Buchstaben?
    i = 0
    while i < len(toks):
        tok = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        # "Doppel L" / "doppeltes L" / "Doppel-L"
        if tok.startswith("doppel"):
            rest = tok[len("doppel"):].lstrip("tes").lstrip("te")
            l = _als_buchstabe(rest) if rest else (_als_buchstabe(nxt) or _TAFEL.get(nxt, ""))
            if l:
                letters.append(l * 2)
                i += 1 if rest else 2
                continue
        # "A Umlaut" -> Ä (bezieht sich auf den letzten Buchstaben)
        if tok == "umlaut" and letters and letters[-1] and letters[-1][-1] in _UMLAUT:
            letters[-1] = letters[-1][:-1] + _UMLAUT[letters[-1][-1]]
            i += 1
            continue
        # "scharfes S" -> ß
        if tok in {"scharfes", "scharfe"} and nxt in {"s", "es", "ess"}:
            letters.append("ß")
            i += 2
            continue
        # "M wie Martha": Buchstabe vor dem "wie" zählt, das Wort bestätigt nur.
        if nxt == "wie":
            l = _als_buchstabe(tok) or _TAFEL.get(tok, "")
            wort = toks[i + 2] if i + 2 < len(toks) else ""
            if not l and wort:
                l = _TAFEL.get(wort, "") or (wort[:1] if wort[:1] in _EINZEL else "")
            if l:
                letters.append(l)
                kette = True
                fuell_folge = 0
                i += 3
                continue
        l = _als_buchstabe(tok)
        if l:
            letters.append(l)
            kette = True
            fuell_folge = 0
            i += 1
            continue
        # STT klebt Einzelbuchstaben gern zu Clustern zusammen ("F-E-LD-Kamp"
        # kam live 29.08.2026 statt F-E-L-D-K-A-M-P). Ein kurzes vokalloses
        # Token INNERHALB der Kette ist kein Wort, sondern zusammengezogene
        # Buchstaben: aufspalten. Vokalhaltige Kurz-Tokens ("Kam" statt
        # K-A-M, Batch s11 29.08.2026) nur, wenn die Buchstabierung danach
        # sichtbar WEITERGEHT — sonst wäre jedes Alltagswort ein Cluster.
        # Fuellwoerter NIE zerlegen (W-DIKTAT-FERTIG 13.09.2026): live wurde
        # aus "aufstabiert es das R-A-T-E-I-K-E" der Name "Sdasrateike" —
        # "das" landete als d-a-s in der Kette, weil diese Cluster-Regel VOR
        # dem Fuellwort-Zweig greift.
        if (kette and fuell_folge == 0 and 2 <= len(tok) <= 4 and tok.isalpha()
                and tok not in _TAFEL and tok not in _FUELL):
            nxt_tafel = nxt in _TAFEL and len(nxt) > 1
            # Verschliffenes "X wie" VOR einem Tafel-Wort ("Ew Emil",
            # "Uwi Ulrich", "SW Samuel" — Batch s09 29.08.2026): das
            # Kurz-Token ist der kaputte "X wie"-Rest, NICHT zusammen-
            # gezogene Buchstaben. Ueberspringen — das Tafel-Wort danach
            # traegt den Buchstaben. Erkennbar am passenden Anlaut oder
            # der verschluckten wie-Endung (…w/…wi).
            if nxt_tafel and (tok[0] == _TAFEL[nxt] or tok.endswith(("w", "wi"))):
                i += 1
                continue
            vokallos = not any(v in tok for v in "aeiouäöüy")
            nxt2 = toks[i + 2] if i + 2 < len(toks) else ""
            weiter = bool(_als_buchstabe(nxt)) or nxt2 == "wie"
            if vokallos or weiter:
                letters.extend(tok)
                i += 1
                continue
        if tok in _TAFEL and len(tok) > 1:
            # Ein Tafel-Wort OHNE "wie" zählt nur INNERHALB einer
            # Buchstabier-Kette ("Anton Berta Cäsar") oder wenn direkt das
            # nächste Token weiterbuchstabiert. Sonst ist es ein normales
            # Wort: "… der Vorname ist Paul" hängte live (27.08.2026) ein
            # P an den buchstabierten Namen ("Panzerp").
            im_fluss = kette and fuell_folge <= 1
            nxt_buchstabig = bool(_als_buchstabe(nxt)) or (nxt in _TAFEL and len(nxt) > 1) or nxt == "wie"
            if im_fluss or nxt_buchstabig:
                letters.append(_TAFEL[tok])
                kette = True
                fuell_folge = 0
                i += 1
                continue
            woerter.append(tok)
            fremd += 1
            i += 1
            continue
        if tok in _FUELL:
            fuell_folge += 1
            i += 1
            continue
        if tok.isalpha() and len(tok) >= 2:
            woerter.append(tok)
            if kette and fuell_folge == 0:
                anschluss.append(tok)
        fremd += 1
        kette = False
        fuell_folge = 0
        i += 1

    zusammen = "".join(letters)
    # "Papa Gregoriu, also Papagrigoriou" (live 30.08.2026): STT hat die
    # Buchstabenkette als Woerter gehoert — das Wort NACH "also"/"genau"
    # ist die gemeinte Schreibweise, nicht das Bruchstueck davor.
    also_name = _name_nach_also(toks)
    if also_name and len(letters) < 2 and _name_anker_vor_also(toks, also_name):
        return {"name": also_name[0].upper() + also_name[1:], "sicher": True}
    # Tafel-Rettung: hat STT die "X wie Y"-Paare verstuemmelt ("Kavi Kaufmann,
    # Iwi Emil …", Batch s14/s17 29.08.2026), tragen die TAFEL-WOERTER selbst
    # mehr Signal als die zerhackten Buchstaben — ihre Anlaute sind der Name.
    # Bei nur 3 Treffern braucht es ein Buchstabier-Signal (Kette oder "wie"),
    # sonst wuerde "Emil Richard Otto" als Namensangabe zu "Ero".
    tafel = _tafel_anlaute(toks)
    if (len(tafel) >= 3 and len(tafel) > len(letters)
            and (len(tafel) >= 4 or letters or "wie" in toks)):
        name = "".join(tafel)
        return {"name": name[0].upper() + name[1:], "sicher": False}
    if len(letters) < 2 or len(zusammen) < 2:
        return None
    # Wort-Anker: Beginnt ein mitgesprochenes Wort mit GENAU den buchstabierten
    # Buchstaben (mind. 3, sonst Zufallstreffer), ist das Wort der Name — egal
    # wie STT den Rest der Buchstabierung verstümmelt hat ("Feldkamp, also
    # F-E-LD-Kamp", live 29.08.2026: deute lieferte None, die Frage loopte).
    if also_name and len(also_name) >= max(6, len(zusammen)) and (
            also_name.startswith(zusammen) or zusammen in also_name):
        return {"name": also_name[0].upper() + also_name[1:], "sicher": True}
    if len(zusammen) >= 3:
        for w in woerter:
            if len(w) > len(zusammen) and w.startswith(zusammen):
                return {"name": w[0].upper() + w[1:], "sicher": True}
    # Streu-Buchstaben VOR dem gesprochenen Namen (live 13.09.2026: in
    # "Rateike, aufstabiert es das R-A-T-E-I-K-E" wurde das Woertchen "es" zum
    # Buchstaben S, der Nachname hiess "Srateike"). Steht der gesprochene Name
    # vollstaendig am ENDE der Kette und fehlen davor hoechstens zwei
    # Buchstaben, ist der Vorlauf STT-Muell — das Wort wurde gesprochen UND
    # buchstabiert, ist also sicher.
    for w in woerter:
        if (len(w) >= 4 and w != zusammen and zusammen.endswith(w)
                and len(zusammen) - len(w) <= 2):
            return {"name": w[0].upper() + w[1:], "sicher": True}
    # Suffix-Fuge: STT hat das ENDE der Buchstabierung zu einem Wort
    # zusammengezogen ("F-E-L-D-Kamp"). Genau ein Wort direkt hinter der
    # Kette ohne Füller dazwischen => anfügen — ausser das Wort ist die
    # Buchstabierung selbst ("M-E-I-E-R, Meier") oder steckt schon am Ende.
    # NUR wenn die Kette dominiert: aus "acwc" + fremdem Muell entstand sonst
    # der Phantasiename "Acwchabi" (Batch s14 29.08.2026).
    if (len(zusammen) >= 3 and len(anschluss) == 1 and 2 <= len(anschluss[0]) <= 15
            and fremd <= len(letters)
            and anschluss[0] != zusammen and not zusammen.endswith(anschluss[0])):
        voll = zusammen + anschluss[0]
        return {"name": voll[0].upper() + voll[1:], "sicher": False}
    # Dominanz: eine echte Buchstabierung besteht überwiegend aus Buchstaben.
    if fremd > len(letters):
        return None
    name = zusammen[0].upper() + zusammen[1:]
    sicher = any(w == zusammen for w in woerter)
    return {"name": name, "sicher": sicher}


def _explizite_cluster_trennen(text: str) -> str:
    """Groß geschriebene Hyphen-Cluster innerhalb einer Kette entfalten.

    ``R-EN-C-O`` bedeutet im Buchstabierkontext R-E-N-C-O, nicht R-(gespro-
    chenes EN=N)-C-O. Normale Wörter und ``T-Mia`` bleiben unangetastet.
    """
    def _entfalten(m: re.Match[str]) -> str:
        teile = re.split(r"\s*-\s*", m.group(0))
        return "-".join(ch for teil in teile for ch in teil)

    return _EXPLIZITE_KETTE_RE.sub(_entfalten, text)


def _feldsegment_vorbereiten(text: str) -> str:
    raw = ohne_schlusswort(text)
    # Das zerhackte „C wie Cäsar“ zuerst auf das gemeinte C reduzieren; das O
    # bleibt durch den Lookahead als nächster Buchstabe erhalten.
    raw = _ZERHACKTES_CAESAR_RE.sub("C", raw)
    return _explizite_cluster_trennen(raw)


def _hat_explizite_kette(text: str) -> bool:
    return bool(re.search(
        r"(?<!\w)[A-Za-zÄÖÜäöüß]"
        r"(?:\s*-\s*[A-Za-zÄÖÜäöüß]){1,}(?!\w)",
        text,
    ))


def deute_feldsegment(text: str) -> dict[str, Any] | None:
    """Buchstabierung für EIN gerade erfragtes Namensfeld.

    Explizites „neues Wort“ bewahrt zusammengesetzte Nachnamen als getrennte
    Wörter. Ohne diesen Marker endet das aktuelle Feld an einer bereits
    vollständigen ersten Kette, wenn danach eine zweite vollständige Kette
    folgt — so wird der Kindesname in „H-A-L-L-W-A-C-H-S, T-A-M-I-A“ nicht
    an den Nachnamen der Anruferin geklebt.

    Dieser strengere Pfad ist opt-in; ``deute`` selbst bleibt unverändert.
    """
    raw = _feldsegment_vorbereiten(text)

    wortteile = [
        teil.strip(" ,.;:!?-")
        for teil in _NEUES_WORT_RE.split(raw)
    ]
    if len(wortteile) >= 2 and all(_hat_explizite_kette(t) for t in wortteile):
        gedeutet = [deute(t) for t in wortteile]
        if all(gedeutet):
            namen = [str(d["name"]).strip() for d in gedeutet if d]
            if len(namen) == len(wortteile):
                return {
                    "name": " ".join(namen),
                    "sicher": all(bool(d.get("sicher")) for d in gedeutet if d),
                }

    # Ein Komma zwischen einzelnen Buchstaben („M, Ü, L, L, E, R“) ist keine
    # Feldgrenze. Nur eine schon vollständige ERSTE Kette (mindestens vier
    # Zeichen) wird abgetrennt, wenn später eine weitere vollständige Kette
    # folgt. „L-O-U, R-EN-C-O“ bleibt deshalb eine einzige Kette.
    abschnitte = [t.strip() for t in re.split(r"[,;]", raw) if t.strip()]
    if len(abschnitte) >= 2 and _hat_explizite_kette(abschnitte[0]):
        erste = deute(abschnitte[0])
        erste_name = str((erste or {}).get("name") or "")
        spaetere_kette = any(
            _hat_explizite_kette(t) and deute(t)
            for t in abschnitte[1:]
        )
        if erste and len(re.sub(r"\W", "", erste_name, flags=re.UNICODE)) >= 4 \
                and spaetere_kette:
            return erste

    return deute(raw)


def teil(text: str) -> str:
    """Eindeutiges Buchstabier-Fragment, auch nur EIN Buchstabe.

    Diese engere Deutung ist ausschließlich für eine bereits offene
    Buchstabier-Frage gedacht. Unbekannte Wörter verwerfen das Fragment,
    damit ein normal gesprochener Nachname nicht als Buchstabenfolge endet.
    """
    toks = _tokens(text)
    if not toks:
        return ""
    # Das Tafelwort ist im Telefon-ASR stabiler als der davor gesprochene
    # Einzelbuchstabe: „I wie Ida“ kam als „E wie Ida“, „Z wie Zacharias“
    # als „Zwesacharias“. Die bestehende fuzzy Tafelrettung löst beides.
    tafel = _tafel_anlaute(toks)
    if tafel:
        return "".join(tafel)
    fuzzy = _fuzzy_tafel_fragment(toks)
    if fuzzy:
        return fuzzy
    erlaubt = _FUELL | {
        "wie", "fertig", "ende", "wars", "war's", "gewesen",
    }
    letters: list[str] = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if tok.startswith("doppel"):
            rest = tok[len("doppel"):].lstrip("tes").lstrip("te")
            letter = (
                _als_buchstabe(rest)
                if rest
                else (_als_buchstabe(nxt) or _TAFEL.get(nxt, ""))
            )
            if not letter:
                return ""
            letters.append(letter * 2)
            i += 1 if rest else 2
            continue
        if nxt == "wie":
            wort = toks[i + 2] if i + 2 < len(toks) else ""
            letter = _als_buchstabe(tok) or _TAFEL.get(tok, "")
            if not letter and wort:
                letter = _TAFEL.get(wort, "")
            if not letter:
                return ""
            letters.append(letter)
            i += 3
            continue
        letter = _als_buchstabe(tok)
        if letter and nxt.startswith(("wi", "vi")) and len(nxt) >= 3:
            # „N wie Nordpol“ -> „N'Winopol“: der Einzelbuchstabe blieb
            # erhalten, „wie“ klebt am verhörten Tafelwort.
            letters.append(letter)
            i += 2
            continue
        # Whisper klebt einen Einzelbuchstaben plus „wie“ oft zu einem
        # kurzen Vorspann vor dem Tafelwort: „AVI Anton“, „Ivi Ida“,
        # „SW Samuel“. Der Anlaut des Vorspanns MUSS zum Tafelwort passen;
        # dadurch wird kein beliebiges unbekanntes Wort verschluckt.
        if (
            nxt in _TAFEL
            and len(nxt) > 1
            and 2 <= len(tok) <= 5
            and tok[:1] == _TAFEL[nxt]
        ):
            letters.append(_TAFEL[nxt])
            i += 2
            continue
        letter = _als_buchstabe(tok)
        if letter:
            letters.append(letter)
            i += 1
            continue
        if tok in _TAFEL and len(tok) > 1:
            letters.append(_TAFEL[tok])
            i += 1
            continue
        if tok not in erlaubt:
            return ""
        i += 1
    return "".join(letters)


def ist_buchstabierung(text: str) -> bool:
    return deute(text) is not None


def vorlesen(name: str) -> str:
    """"Müller" -> "M wie Martha, Ü wie Übermut, ..." für die Rückbestätigung."""
    teile = []
    for ch in _s(name).lower():
        if ch in _VORLESE:
            teile.append(f"{ch.upper()} wie {_VORLESE[ch]}")
        elif ch in {" ", "-"}:
            teile.append("Bindestrich" if ch == "-" else "dann")
    return ", ".join(teile)
