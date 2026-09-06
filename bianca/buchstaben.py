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


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _tokens(text: str) -> list[str]:
    raw = _s(text).lower()
    raw = re.sub(r"[.,;:!?/]+", " ", raw)
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


def deute(text: str) -> dict[str, Any] | None:
    """Buchstabierung erkennen und zusammensetzen.

    Rückgabe {"name": "Müller", "sicher": bool} oder None, wenn der Satz
    keine Buchstabierung ist. "sicher" wird gesetzt, wenn ein zusammenhängend
    gesprochenes Wort im Satz exakt dem zusammengesetzten Namen entspricht.
    """
    toks = _tokens(text)
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
        if (kette and fuell_folge == 0 and 2 <= len(tok) <= 4 and tok.isalpha()
                and tok not in _TAFEL):
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
    if also_name and len(letters) < 2:
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
