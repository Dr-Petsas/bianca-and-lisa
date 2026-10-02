"""Anliegen eines Mitschnitts — fuer die Filterleiste in /anrufe.

Leitet die Anliegen aus dem schon geschriebenen Manifest ab, damit alte
Gespraeche ohne Nachschreiben filterbar sind. Belege (Buchung, Absage,
Verschieben, Transfer, Rueckrufnotiz) gewinnen vor dem Wortlaut.

Bianca-frei: kein Import aus bianca/.
"""
from __future__ import annotations

import re
from typing import Any

try:
    from kern.rechnung import erkannt as _rechnung_erkannt
except Exception:  # V4-Image ohne Re-Export
    _rechnung_erkannt = None

# Reihenfolge der Filterchips = Terminverwaltung, dann die Praxis-Anliegen.
TITEL: dict[str, str] = {
    "buchen": "Termin",
    "absagen": "Absage",
    "verschieben": "Verschieben",
    "auskunft": "Auskunft",
    "rezept": "Rezept",
    "au": "Krankschreibung",
    "ueberweisung": "Überweisung",
    "attest": "Attest",
    "befund": "Befund",
    "unterlagen": "Unterlagen",
    "medikament": "Medikament",
    "arzt_sprechen": "Arzt sprechen",
    "mitarbeiter_sprechen": "Anmeldung",
    "notfall": "Notfall",
    "rechnung": "Rechnung",
    "kosten": "Kosten",
    "neupatient": "Neupatient",
    "beschwerde": "Beschwerde",
    "rueckruf": "Rückruf",
    "oeffnungszeiten": "Öffnungszeiten",
    "sonstiges": "Sonstiges",
}
REIHE: tuple[str, ...] = tuple(TITEL.keys())


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _ok(eintrag: Any) -> bool:
    return isinstance(eintrag, dict) and bool(eintrag.get("ok"))


def _tool_namen(m: dict[str, Any]) -> list[str]:
    namen: list[str] = []
    for t in m.get("tools") or []:
        if not isinstance(t, dict):
            continue
        for k in ("name", "cf"):
            n = _s(t.get(k)).lower()
            if n:
                namen.append(n)
    for z in m.get("zuege") or []:
        if not isinstance(z, dict):
            continue
        for t in z.get("tools") or []:
            if not isinstance(t, dict):
                continue
            n = _s(t.get("name") or t.get("cf")).lower()
            if n:
                namen.append(n)
    return namen


def _anrufer_saetze(m: dict[str, Any]) -> list[str]:
    aus: list[str] = []
    for z in m.get("zuege") or []:
        if not isinstance(z, dict):
            continue
        t = _s(z.get("textIn"))
        if t:
            aus.append(t)
    return aus[:12]


_REZEPT_RE = re.compile(r"\b\w*rezept(?!ion)\w*", re.I)
_AU_RE = re.compile(
    r"\b(?:krankschreib\w*|arbeitsunf(?:ä|ae)hig\w*|\bau\b|gelber\s+schein|"
    r"krankmeldung)\b",
    re.I,
)
_UEBER_RE = re.compile(r"\b(?:(?:ü|ue)berweis\w+|ueberweisung)\b", re.I)
_ATTEST_RE = re.compile(r"\b(?:attest\w*|bescheinigung|schulbefreiung)\b", re.I)
_BEFUNDE_RE = re.compile(r"\b(?:befund\w*|laborwert\w*|blutwert\w*)\b", re.I)
_UNTERLAGEN_RE = re.compile(
    r"\b(?:unterlagen|krankenakte|akte\s+kopieren|einsicht)\b", re.I)
_MEDIKAMENT_RE = re.compile(r"\b(?:medikament\w*|rezeptur)\b", re.I)
_NOTFALL_RE = re.compile(
    r"\b(?:notfall|notaufnahme|lebensgefahr|bewusstlos)\b|\b112\b|"
    r"\bakute?\s+(?:haut)?beschwerden\b",
    re.I,
)
_RUECKRUF_RE = re.compile(
    r"\b(?:r(?:ü|ue)ckruf|zur(?:ü|ue)ckrufen|rufen\s+sie\s+(?:mich\s+)?"
    r"zur(?:ü|ue)ck)\b",
    re.I,
)
_VERBINDEN_RE = re.compile(
    r"\b(?:verbinden|durchstellen|weiterleiten|ans\s+telefon|"
    r"mit\s+(?:herrn|frau|doktor|dr\.?)\s+\w+\s+sprechen)\b",
    re.I,
)
_ANMELDUNG_RE = re.compile(
    r"\b(?:anmeldung|empfang|mitarbeiter|buchhaltung|rezeption)\b", re.I)
_ABSAGEN_RE = re.compile(
    r"\b(?:absagen|stornier\w*|canceln|termin\s+(?:l(?:ö|oe)schen|streichen))\b",
    re.I,
)
_VERSCHIEBEN_RE = re.compile(r"\b(?:verschieben|verlegen|umtausch(?:en)?)\b", re.I)
_BUCHEN_RE = re.compile(
    # „Termin haben wir erst im Oktober“ ist ein Bestand, kein Wunsch.
    # Gewünscht ist nur „einen Termin haben“.
    r"\b(?:(?:einen|ein)\s+termin\s+haben|termin\s+(?:machen|vereinbaren|buchen|ausmachen)|"
    r"(?:br(?:ä|ae)ucht\w*|m(?:ö|oe)cht\w*|h(?:ä|ae)tt\w+)\s+"
    r"(?:gern(?:e)?\s+)?einen\s+termin|"
    r"ich\s+(?:brauche|brauch)\s+einen\s+termin)\b",
    re.I,
)
_AUSKUNFT_RE = re.compile(
    r"\b(?:wann\s+(?:ist|war|mein)|habe\s+ich\s+(?:da\s+|denn\s+)?"
    r"(?:noch\s+)?einen\s+termin|n(?:ä|ae)chster\s+termin|"
    r"terminauskunft|termin\s+vergessen)\b",
    re.I,
)
_BESCHWERDE_RE = re.compile(
    # „Beschwerden“ sind Symptome. Eine Beschwerde ist die Klage.
    r"\b(?:reklamation|unfreundlich|wartezeit\s+zu\s+lang|"
    r"beschweren|beschwere|(?:eine|die|meine|ihre|diese)\s+beschwerde)\b",
    re.I,
)
_NEU_RE = re.compile(r"\b(?:neupatient\w*|noch\s+nie\s+(?:da|hier))\b", re.I)
_KOSTEN_RE = re.compile(r"\b(?:was\s+kostet|wie\s+teuer|preis(?:e)?)\b", re.I)
_OEFFNUNG_RE = re.compile(
    r"\b(?:(?:ö|oe)ffnungszeit\w*|sprechzeit\w*|"
    r"wann\s+(?:habt\s+ihr|haben\s+sie)\s+(?:auf|offen|ge(?:ö|oe)ffnet))\b",
    re.I,
)


def _text_treffer(saetze: list[str]) -> list[str]:
    ids: list[str] = []

    def _add(i: str, ja: bool) -> None:
        if ja and i not in ids:
            ids.append(i)

    for t in saetze:
        _add("rezept", bool(_REZEPT_RE.search(t)))
        _add("au", bool(_AU_RE.search(t)))
        _add("ueberweisung", bool(_UEBER_RE.search(t)))
        _add("attest", bool(_ATTEST_RE.search(t)))
        _add("befund", bool(_BEFUNDE_RE.search(t)))
        _add("unterlagen", bool(_UNTERLAGEN_RE.search(t)))
        _add("medikament", bool(_MEDIKAMENT_RE.search(t)) and not _REZEPT_RE.search(t))
        ist_notfall = bool(_NOTFALL_RE.search(t))
        _add("notfall", ist_notfall)
        ist_rechnung = bool(_rechnung_erkannt(t)) if _rechnung_erkannt else (
            "rechnung" in t.lower() or "mahnung" in t.lower())
        _add("rechnung", ist_rechnung)
        _add("kosten", bool(_KOSTEN_RE.search(t)) and not ist_rechnung)
        _add("rueckruf", bool(_RUECKRUF_RE.search(t)))
        # „Mit einem Mitarbeiter verbinden“ ist die Anmeldung, kein Arzt.
        # Ein namentlicher Arzt im selben Satz bleibt Durchstellen.
        anmeldung = bool(_ANMELDUNG_RE.search(t))
        arzt_im_satz = bool(re.search(
            r"\b(?:doktor|dr\.?|arzt|ärztin|aerztin|behandler)\b", t, re.I))
        if anmeldung and not arzt_im_satz:
            _add("mitarbeiter_sprechen", True)
        else:
            _add("arzt_sprechen", bool(_VERBINDEN_RE.search(t)))
        _add("oeffnungszeiten", bool(_OEFFNUNG_RE.search(t)))
        _add("beschwerde", bool(_BESCHWERDE_RE.search(t)) and not ist_notfall)
        _add("neupatient", bool(_NEU_RE.search(t)))
        _add("absagen", bool(_ABSAGEN_RE.search(t)))
        _add("verschieben", bool(_VERSCHIEBEN_RE.search(t)))
        _add("auskunft", bool(_AUSKUNFT_RE.search(t)) and not _BUCHEN_RE.search(t))
        _add("buchen", bool(_BUCHEN_RE.search(t)) and not _AUSKUNFT_RE.search(t)
             and not _ABSAGEN_RE.search(t) and not _VERSCHIEBEN_RE.search(t))
    # „Akute Beschwerden“ ist der Notfall. „Eine Beschwerde“ im selben
    # Anruf war der Einstieg in die Symptome, keine Klage.
    if "notfall" in ids and "beschwerde" in ids:
        klage = any(re.search(r"\bbeschwer(?:en|e)\b", t or "", re.I) for t in saetze)
        if not klage:
            ids.remove("beschwerde")
    return ids


def _belege(m: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    if _ok(m.get("lastBook")):
        ids.append("buchen")
    if _ok(m.get("lastCancel")):
        ids.append("absagen")
    if _ok(m.get("lastMove")):
        ids.append("verschieben")
    namen = _tool_namen(m)
    blob = " ".join(namen)
    if any(x in blob for x in ("transfer", "weiterleit", "forward")):
        ids.append("arzt_sprechen")
    if any(x in blob for x in ("findpatient", "list_appointments",
                               "agentfindpatient")):
        if "buchen" not in ids and "absagen" not in ids and "verschieben" not in ids:
            ids.append("auskunft")
    notiz = _s(m.get("praxisNotiz")).lower()
    if notiz:
        if "rueckruf" in notiz or "rückruf" in notiz:
            ids.append("rueckruf")
        if "rechnung" in notiz:
            ids.append("rechnung")
        if "rezept" in notiz:
            ids.append("rezept")
        if "überweis" in notiz or "ueberweis" in notiz:
            ids.append("ueberweisung")
    return ids


def ids_von(manifest: dict[str, Any] | None) -> list[str]:
    """Kanonische Anliegen-IDs, Belege zuerst, dann Wortlaut, ohne Duplikate."""
    m = manifest if isinstance(manifest, dict) else {}
    gesehen: list[str] = []
    for i in _belege(m) + _text_treffer(_anrufer_saetze(m)):
        if i in TITEL and i not in gesehen:
            gesehen.append(i)
    # Der Terminwunsch ist durch den Notfallweg beantwortet. Ohne Buchung
    # bleibt er nicht als offenes Anliegen in der Ergebnisseite stehen.
    if _zahnnotfall_richtig(m):
        if "notfall" not in gesehen:
            gesehen.append("notfall")
        if not _ok(m.get("lastBook")) and "buchen" in gesehen:
            gesehen.remove("buchen")
    return gesehen


def von(manifest: dict[str, Any] | None) -> list[dict[str, str]]:
    """Liste ``{id, titel}`` in Chip-Reihenfolge."""
    haben = set(ids_von(manifest))
    return [{"id": i, "titel": TITEL[i]} for i in REIHE if i in haben]


def hat(eintrag: dict[str, Any] | None, anliegen_id: str) -> bool:
    """Ein Listen-Eintrag (oder Manifest) tragt dieses Anliegen."""
    kid = _s(anliegen_id)
    if not kid:
        return True
    if isinstance(eintrag, dict):
        roh = eintrag.get("anliegen")
        if isinstance(roh, list):
            for x in roh:
                if isinstance(x, dict) and _s(x.get("id")) == kid:
                    return True
                if _s(x) == kid:
                    return True
        if roh is None:
            return kid in ids_von(eintrag)
    return False


def _tool_ok(m: dict[str, Any], *teile: str) -> bool:
    nadel = tuple(t.lower() for t in teile if t)
    for t in m.get("tools") or []:
        if not isinstance(t, dict):
            continue
        name = _s(t.get("name") or t.get("cf")).lower()
        if name and any(x in name for x in nadel):
            if _ok(t) or t.get("notFound") or t.get("mehrdeutig"):
                return True
    return False


def _mund(m: dict[str, Any]) -> str:
    return " ".join(_outputs(m))


def _verbindung_gelegt(m: dict[str, Any]) -> bool:
    """Durchgestellt. Ob der Arzt abhebt, gehört nicht zur Wertung."""
    if _VERBINDUNG_GELEGT_RE.search(_mund(m)):
        return True
    return _tool_ok(m, "transfer", "weiterleit", "forward")


def _verbindung_technisch_gescheitert(m: dict[str, Any]) -> bool:
    """Die Verbindung kam gar nicht zustande. Nicht-Abheben zählt hier nicht."""
    if _verbindung_gelegt(m):
        return False
    return bool(_VERBINDUNG_TECHNIK_RE.search(_mund(m)))


def _mund_hat(m: dict[str, Any], *woerter: str) -> bool:
    nadel = tuple(w.lower() for w in woerter if w)
    for z in m.get("zuege") or []:
        if not isinstance(z, dict):
            continue
        t = _s(z.get("text")).lower()
        if t and any(w in t for w in nadel):
            return True
    return False


# Historische Parakeet-Leaks vor W-STT-DE-ONLY. Neue Anrufe tragen diese
# Texte nicht mehr: sie werden am Ohr verworfen. In der Ergebnisseite dürfen
# sie weder als Anruferinhalt noch als Dialogschleife zählen (Chef 28.09.2026,
# Anruf 8e68db99…).
_ENGLISCHE_STT_ALTLAST_RE = re.compile(
    r"^\s*(?:damn(?:\s+it)?|queen\s+service)\s*[.!?]*\s*$",
    re.I,
)
_NOTFALL_ANWEISUNG_RE = re.compile(
    r"kommen sie bitte jetzt|rufen sie bitte 112|116\s*117",
    re.I,
)
_TERMIN_BLEIBT_RE = re.compile(
    r"\btermin\b.{0,50}\bbleibt\b.{0,30}\bbestehen\b",
    re.I,
)
_ABSAGE_VERNEINT_RE = re.compile(
    r"^\s*(?:nein|nee|ne|doch nicht|lieber nicht|nicht absagen)\b",
    re.I,
)


def _englische_stt_altlast(zug: dict[str, Any]) -> bool:
    return bool(_ENGLISCHE_STT_ALTLAST_RE.match(_s(zug.get("textIn"))))


def _outputs(m: dict[str, Any]) -> list[str]:
    aus: list[str] = []
    for z in m.get("zuege") or []:
        if not isinstance(z, dict) or _englische_stt_altlast(z):
            continue
        t = _s(z.get("text"))
        if t:
            aus.append(t)
    return aus


def _notfall_waechter(m: dict[str, Any]) -> bool:
    for z in m.get("zuege") or []:
        if not isinstance(z, dict):
            continue
        for w in z.get("waechter") or []:
            if isinstance(w, dict) and _s(w.get("w")).lower() == "notfall-vorrang":
                return True
    return False


def _zahnnotfall_richtig(m: dict[str, Any]) -> bool:
    """Wächter plus Sofortanweisung. Der Wächter allein ist kein Erfolg."""
    return _notfall_waechter(m) and bool(_NOTFALL_ANWEISUNG_RE.search(_mund(m)))


def _absage_sicher_beibehalten(m: dict[str, Any]) -> bool:
    """„Nein“ auf die Absagefrage, und der Termin bleibt ausdrücklich bestehen."""
    for z in m.get("zuege") or []:
        if not isinstance(z, dict) or _englische_stt_altlast(z):
            continue
        if (_ABSAGE_VERNEINT_RE.search(_s(z.get("textIn")))
                and _TERMIN_BLEIBT_RE.search(_s(z.get("text")))):
            return True
    return False


def _letzter_anrufer(m: dict[str, Any]) -> str:
    for z in reversed(m.get("zuege") or []):
        if not isinstance(z, dict):
            continue
        t = _s(z.get("textIn"))
        if t:
            return t
    return ""


_UNKLAR_RE = re.compile(
    r"was meinen sie damit|meinen sie vielleicht etwas anderes|"
    r"das habe ich nicht verstanden|akustisch nicht verstanden",
    re.I,
)
_PRESENCE_RE = re.compile(
    r"sind sie noch dran|ich bin noch da|meine frage war",
    re.I,
)
_FERTIG_RE = re.compile(
    r"\b(?:das\s+war(?:'?s|'s| es)|hat\s+sich\s+erledigt|"
    r"reicht\s+(?:so|mir|mir so)|mehr\s+brauch(?:e|)\s+ich\s+nicht|"
    r"passt\s+so|rufe?\s+(?:ich\s+)?(?:sp(?:ä|ae)ter|ein\s+anderes\s+mal))\b",
    re.I,
)
_DANK_SCHLUSS_RE = re.compile(
    r"^(?:(?:ja|nein|nee|okay|ok|gut|alles\s+klar|prima),?\s+)*"
    r"(?:vielen(?:\s+lieben)?\s+dank|danke(?:sch[oö]n)?|dankeschoen)"
    r"(?:\s+(?:ihnen|dir|gleichfalls|auch|sch[oö]n))*"
    r"[.!]*$",
    re.I,
)
_SONST_NOCH_RE = re.compile(
    r"kann ich (?:ihnen )?sonst noch|sonst etwas fuer sie|sonst noch etwas",
    re.I,
)
_KURZ_NEIN_RE = re.compile(
    r"^(?:nein|nee|nope|passt|reicht)(?:\s+(?:danke|dankesch[oö]n))?[.!]*$",
    re.I,
)
_BUCHEN_MUND_RE = re.compile(
    r"schon einmal|wann passt|welche[rn]?\s+(?:termin|tag)|"
    r"bei welchem behandler|wie sind sie versichert|"
    r"vormittag|nachmittag|soll ich (?:das so )?eintragen|"
    r"frei w(?:ä|ae)re|ich h(?:ä|ae)tte(?:\s+da)?",
    re.I,
)
_ABSAGE_MUND_RE = re.compile(
    r"absagen|stornier|welchen termin|wirklich.*(?:absagen|streichen|l(?:ö|oe)schen)",
    re.I,
)
_NACHNAME_FRAGE_RE = re.compile(r"nachname|buchstabier", re.I)
_VERSCHIEB_MUND_RE = re.compile(
    r"verschieben|verlegen|neuen termin|ander(?:en|er)\s+termin",
    re.I,
)
_AUSKUNFT_MUND_RE = re.compile(
    r"ihr(?:en)?\s+(?:n(?:ä|ae)chsten?\s+)?termin|ich sehe|"
    r"gefunden|im kalender",
    re.I,
)
_DOKUMENT_MUND_RE = re.compile(
    r"pers(?:ö|oe)nlich|\bnotiz\b|notiere|"
    r"r(?:ü|ue)ckruf|melde sich|meldet sich|"
    r"ruft sie zur(?:ü|ue)ck|rufe sie zur(?:ü|ue)ck|"
    r"am telefon nicht|nicht am telefon|am telefon (?:nichts|darf ich)|"
    r"telefonassistent|worum es geht|"
    r"nehme (?:ihren|das|die|den)\b|"
    r"wunsch auf|zur abholung|zuschicken|"
    r"nicht ohne untersuchung|in die praxis kommen|in der praxis sehen|"
    r"vorstellung in der praxis|dienstweg|"
    r"beantwortet ihnen der arzt|besprechen sie bitte|"
    r"schreiben sie uns|kann ich das nicht kl(?:ä|ae)ren|"
    r"mit dem behandler|e-mail|zur besprechung",
    re.I,
)
_ARZT_PLAN_RE = re.compile(
    r"r(?:ü|ue)ckruf|nicht ans telefon|"
    r"ber(?:ä|ae)t der arzt nicht|gebe ich ihnen einen termin",
    re.I,
)
# Die Verbindung wurde gelegt. Der Arzt muss nicht abheben: „nicht zustande
# gekommen“ und „Da bin ich wieder“ sind der Rückweg nach dem Klingeln.
_VERBINDUNG_GELEGT_RE = re.compile(
    r"stelle die verbindung|stelle sie durch|ich verbinde sie|"
    r"verbindung.{0,80}nicht zustande gekommen|da bin ich wieder",
    re.I,
)
# Kein Ziel, kein Dial. Das ist der technische Fehlschlag, nicht „geht nicht ran“.
_VERBINDUNG_TECHNIK_RE = re.compile(
    r"direkte verbindung ist im moment leider nicht|"
    r"verbindung (?:ist|kann|konnte).{0,40}nicht m(?:ö|oe)glich",
    re.I,
)


def _letzte_bianca(m: dict[str, Any]) -> str:
    for z in reversed(m.get("zuege") or []):
        if not isinstance(z, dict):
            continue
        t = _s(z.get("text"))
        if t:
            return t
    return ""


def anrufer_hat_geschlossen(manifest: dict[str, Any] | None) -> bool:
    """Letzter Anrufer-Satz ist ein Gesprächsschluss, kein stilles Auflegen."""
    m = manifest if isinstance(manifest, dict) else {}
    text = _letzter_anrufer(m)
    if not text:
        return False
    try:
        from kern.abschied import ist_abschied
        if ist_abschied(text):
            return True
    except Exception:
        pass
    if _FERTIG_RE.search(text) or _DANK_SCHLUSS_RE.match(text.strip()):
        return True
    kurz_schluss = bool(
        _KURZ_NEIN_RE.match(text.strip()) or _DANK_SCHLUSS_RE.match(text.strip())
    )
    # „Nein.“ / „Danke.“ nach „Sonst noch?“ oder nach ehrlicher Notiz.
    if kurz_schluss and (
        _SONST_NOCH_RE.search(_letzte_bianca(m)) or _s(m.get("praxisNotiz"))
    ):
        return True
    return False


def _frage_wiederholt_detail(outputs: list[str]) -> tuple[int, str]:
    zaehl: dict[str, int] = {}
    for text in outputs:
        for satz in re.split(r"(?<=[?])\s+", text):
            if "?" not in satz:
                continue
            norm = re.sub(r"[^a-z0-9äöüß]+", " ", satz.lower()).strip()
            if len(norm) >= 8:
                zaehl[norm] = zaehl.get(norm, 0) + 1
    if not zaehl:
        return 0, ""
    text, anzahl = max(zaehl.items(), key=lambda x: x[1])
    return anzahl, text[:100]


def _frage_wiederholt(outputs: list[str]) -> int:
    return _frage_wiederholt_detail(outputs)[0]


def _http_status(tool: dict[str, Any]) -> int:
    d = tool.get("dispatch") if isinstance(tool.get("dispatch"), dict) else {}
    try:
        return int(d.get("httpStatus") or 0)
    except (TypeError, ValueError):
        return 0


def _designed_leer(tool: dict[str, Any]) -> bool:
    if tool.get("notFound") or tool.get("mehrdeutig") or tool.get("noUpcomingReason"):
        return True
    d = tool.get("dispatch") if isinstance(tool.get("dispatch"), dict) else {}
    r = d.get("response") if isinstance(d.get("response"), dict) else {}
    status = _s(r.get("status") or tool.get("status")).lower()
    return status in {"not_found", "no_upcoming", "ambiguous", "conflict"}


def verlauf_stoerungen(manifest: dict[str, Any] | None) -> list[str]:
    """Offensichtliche Gesprächsfehler — dann bleibt ein Abbruch negativ."""
    m = manifest if isinstance(manifest, dict) else {}
    outputs = _outputs(m)
    stoer: list[str] = []
    if any(_UNKLAR_RE.search(t) for t in outputs):
        stoer.append("missverstaendnis")
    if _frage_wiederholt(outputs) >= 2:
        stoer.append("wiederholungsschleife")
    if sum(1 for t in outputs if _PRESENCE_RE.search(t)) >= 2:
        stoer.append("presence_schleife")
    for t in m.get("tools") or []:
        if not isinstance(t, dict):
            continue
        if _designed_leer(t):
            continue
        if t.get("ok") is False or _http_status(t) >= 500:
            stoer.append("technik")
            break
    if _ok(m.get("lastBook")) is False and isinstance(m.get("lastBook"), dict):
        if m.get("lastBook").get("ok") is False:
            stoer.append("technik")
    return stoer


def _erste_jobfrage(m: dict[str, Any]) -> str:
    for text in _outputs(m):
        if "?" not in text:
            continue
        if _UNKLAR_RE.search(text) or _PRESENCE_RE.search(text):
            continue
        return text
    return ""


def anliegen_bearbeitet(manifest: dict[str, Any] | None, anliegen_id: str) -> bool:
    """Das Anliegen wurde erkannt und angegangen — Abschluss ist nicht nötig."""
    m = manifest if isinstance(manifest, dict) else {}
    kid = _s(anliegen_id)
    if _erledigt_beleg(m, kid):
        return True
    blob = " ".join(_tool_namen(m))
    mund = " ".join(_outputs(m))
    erste = _erste_jobfrage(m)
    if kid in ("buchen", "neupatient"):
        return ("getfreetimeslots" in blob or "book" in blob
                or bool(_BUCHEN_MUND_RE.search(mund)))
    if kid == "absagen":
        if _absage_sicher_beibehalten(m):
            return True
        if "cancel" in blob or bool(_ABSAGE_MUND_RE.search(mund)):
            return True
        if _BUCHEN_MUND_RE.search(erste) and not _ABSAGE_MUND_RE.search(erste):
            return False
        return bool(_NACHNAME_FRAGE_RE.search(erste))
    if kid == "verschieben":
        return "move" in blob or bool(_VERSCHIEB_MUND_RE.search(mund))
    if kid == "auskunft":
        return ("findpatient" in blob or "list_appointments" in blob
                or bool(_AUSKUNFT_MUND_RE.search(mund)))
    if kid == "arzt_sprechen":
        if _verbindung_technisch_gescheitert(m):
            return False
        return (_verbindung_gelegt(m) or bool(_s(m.get("praxisNotiz")))
                or bool(_ARZT_PLAN_RE.search(mund)))
    if kid in ("rezept", "au", "ueberweisung", "attest", "befund",
               "unterlagen", "medikament", "rechnung", "beschwerde",
               "mitarbeiter_sprechen", "rueckruf"):
        return bool(_s(m.get("praxisNotiz"))) or bool(_DOKUMENT_MUND_RE.search(mund))
    if kid == "oeffnungszeiten":
        return _mund_hat(m, "uhr", "geöffnet", "geoeffnet", "offen",
                         "nicht vorliegen", "sprechzeit")
    if kid == "kosten":
        return _mund_hat(m, "euro", "kostet", "preis")
    if kid == "notfall":
        return (_ok(m.get("lastBook")) or bool(_s(m.get("praxisNotiz")))
                or "112" in mund or _zahnnotfall_richtig(m))
    return False


def guter_anrufer_abschluss(manifest: dict[str, Any] | None) -> bool:
    """Anrufer hat selbst geschlossen und der Verlauf war bis dahin sauber.

    Kein Write nötig: ohne Wiederholungsschleife, ohne offensichtliches
    Missverständnis und ohne unerkanntes Anliegen zählt der Fall positiv.
    Stilles Auflegen mitten in der Frage bleibt negativ.
    """
    m = manifest if isinstance(manifest, dict) else {}
    if not anrufer_hat_geschlossen(m):
        return False
    if verlauf_stoerungen(m):
        return False
    text_ids = _text_treffer(_anrufer_saetze(m))
    if text_ids and not any(anliegen_bearbeitet(m, i) for i in text_ids):
        if not _s(m.get("praxisNotiz")):
            return False
    return True


def _erledigt_beleg(manifest: dict[str, Any], kid: str) -> bool:
    """True, wenn das Anliegen im Manifest belegbar abgeschlossen ist."""
    if kid == "buchen" or kid == "neupatient":
        return _ok(manifest.get("lastBook"))
    if kid == "absagen":
        return _ok(manifest.get("lastCancel")) or _absage_sicher_beibehalten(manifest)
    if kid == "verschieben":
        return _ok(manifest.get("lastMove"))
    if kid == "auskunft":
        return _tool_ok(manifest, "findpatient", "list_appointments", "agentfindpatient")
    if kid == "arzt_sprechen":
        if _verbindung_technisch_gescheitert(manifest):
            return False
        return (_verbindung_gelegt(manifest)
                or bool(_s(manifest.get("praxisNotiz")))
                or bool(_ARZT_PLAN_RE.search(_mund(manifest))))
    if kid == "rueckruf":
        return bool(_s(manifest.get("praxisNotiz")))
    if kid == "mitarbeiter_sprechen":
        if _verbindung_technisch_gescheitert(manifest):
            return False
        return (_verbindung_gelegt(manifest)
                or bool(_s(manifest.get("praxisNotiz")))
                or bool(_DOKUMENT_MUND_RE.search(_mund(manifest))))
    if kid in ("rezept", "au", "ueberweisung", "attest", "befund",
               "unterlagen", "medikament", "rechnung", "beschwerde"):
        if _s(manifest.get("praxisNotiz")):
            return True
        return bool(_DOKUMENT_MUND_RE.search(_mund(manifest)))
    if kid == "oeffnungszeiten":
        return _mund_hat(manifest, "uhr", "geöffnet", "geoeffnet", "offen",
                         "nicht vorliegen", "sprechzeit")
    if kid == "kosten":
        return _mund_hat(manifest, "euro", "kostet", "preis")
    if kid == "notfall":
        return (_ok(manifest.get("lastBook"))
                or bool(_s(manifest.get("praxisNotiz")))
                or _zahnnotfall_richtig(manifest))
    return False


# Chef 28.09.2026: MedDent ee168a12… ist kein Fail. Nach der Terminfrage
# wechselt der Anrufer auf Griechisch, Bianca antwortet langsam und deutlich.
# Der Fall zählt in der Ergebnisliste als Erfolg.
_CHEF_ERFOLG = frozenset({
    "ee168a125c5444abbd7b857ad34f291e",
})


def erledigt(manifest: dict[str, Any] | None, anliegen_id: str) -> bool:
    """Belegter Abschluss oder sauberer Gesprächsschluss durch den Anrufer."""
    m = manifest if isinstance(manifest, dict) else {}
    kid = _s(anliegen_id)
    if kid in ("arzt_sprechen", "mitarbeiter_sprechen") and (
            _verbindung_technisch_gescheitert(m)):
        return False
    if _s(m.get("id") or m.get("sid")) in _CHEF_ERFOLG:
        return True
    if _erledigt_beleg(m, kid):
        return True
    return guter_anrufer_abschluss(m)


# ------------------------------------------------------------------ Failwertung
# Chef 26.09.2026 (wörtlich): „ein fail ist nicht wenn der Misserfolg durch
# Fehlverhalten auf Anruferseite entsteht. Auflegen, ablehnen etc. fails sind
# nur dann fails, wenn ein nachweislicher Fehler im Gesprächsdialog entsteht,
# der von Bianca initiiert wird … falscher Intent, nicht auf wunschtermine
# eingegangen, Patient nicht gefunden … das letzte ist ganz kritisch.“
# Eine Stelle für Ergebnisseite UND Tages-Scorer, damit beide dieselbe Wahrheit
# sprechen. Anruferabbrüche (Auflegen, Ablehnen) sind NEUTRAL.

_PATIENT_LESER = (
    "findpatient", "agentfindpatient", "searchpatient", "massearchpatient",
    "patientlastdoctor", "findappointmentsbydate",
)
_WRITE_PARTS = {
    "book": ("bookappointment", "book_slot", "masbook"),
    "cancel": ("cancelappointment", "cancel_appointment", "mascancel"),
    "move": ("moveappointment", "move_appointment", "masmove"),
    "note": ("appointmentnote", "note_appointment", "praxis_notiz"),
    "phone": ("updatepatientphone", "update_phone"),
    "patient": ("createpatient", "create_patient"),
    "transfer": ("transfer",),
}
_ERFOLG_CLAIMS = {
    "book": re.compile(
        r"\btermin\b.{0,90}\b(?:fest )?(?:eingetragen|gebucht|vereinbart)\b|"
        r"\balles\b.{0,30}\beingetragen\b",
        re.I | re.S,
    ),
    "cancel": re.compile(
        r"\btermin\b.{0,90}\b(?:abgesagt|storniert|geloescht|gestrichen)\b",
        re.I | re.S,
    ),
    "move": re.compile(
        r"\btermin\b.{0,90}\b(?:verschoben|verlegt|umgebucht)\b",
        re.I | re.S,
    ),
    "note": re.compile(
        r"\b(?:notiz|rueckruf(?:bitte|wunsch)?)\b.{0,90}"
        r"\b(?:notiert|angelegt|geschrieben|eingerichtet)\b|"
        r"\bdie praxis meldet sich\b",
        re.I | re.S,
    ),
    "transfer": re.compile(
        r"\b(?:stelle|verbinde|leite)\b.{0,80}\b(?:durch|weiter|verbindung)\b|"
        r"\bverbindung\b.{0,60}\b(?:eingeleitet|hergestellt)\b",
        re.I | re.S,
    ),
}


def _fold(v: Any) -> str:
    return (
        _s(v).lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def _alle_tools(m: dict[str, Any]) -> list[dict[str, Any]]:
    aus = [t for t in (m.get("tools") or []) if isinstance(t, dict)]
    for zug in m.get("zuege") or []:
        if isinstance(zug, dict):
            aus.extend(t for t in (zug.get("tools") or []) if isinstance(t, dict))
    return aus


def _tool_name(tool: dict[str, Any]) -> str:
    return _fold(tool.get("name") or tool.get("tool") or tool.get("cf"))


def _tool_art(tool: dict[str, Any]) -> str:
    name = _tool_name(tool)
    for art, teile in _WRITE_PARTS.items():
        if any(teil in name for teil in teile):
            return art
    return ""


def _tool_eindeutig_ok(tool: dict[str, Any]) -> bool:
    if tool.get("ok") is False or tool.get("success") is False or tool.get("error"):
        return False
    if tool.get("ok") is True or tool.get("success") is True:
        return True
    d = tool.get("dispatch") if isinstance(tool.get("dispatch"), dict) else {}
    r = d.get("response") if isinstance(d.get("response"), dict) else {}
    if r.get("success") is False or r.get("ok") is False:
        return False
    return bool(r.get("success") or r.get("ok"))


def _tool_eindeutig_fehlgeschlagen(tool: dict[str, Any]) -> bool:
    if tool.get("ok") is False or tool.get("success") is False or tool.get("error"):
        return True
    d = tool.get("dispatch") if isinstance(tool.get("dispatch"), dict) else {}
    r = d.get("response") if isinstance(d.get("response"), dict) else {}
    return (
        r.get("success") is False
        or r.get("ok") is False
        or _http_status(tool) >= 500
    )


def _marker_ok(m: dict[str, Any], key: str) -> bool:
    wert = m.get(key)
    if not wert:
        return False
    if not isinstance(wert, dict):
        return bool(wert)
    if wert.get("ok") is False or wert.get("success") is False:
        return False
    if wert.get("error") and not (
            wert.get("ok") or wert.get("success")
            or wert.get("appointmentId") or wert.get("id")):
        return False
    return True


def _abschluss_evidenz(m: dict[str, Any]) -> dict[str, bool]:
    tools = _alle_tools(m)
    return {
        "book": _marker_ok(m, "lastBook")
        or any(_tool_art(t) == "book" and _tool_eindeutig_ok(t) for t in tools),
        "cancel": _marker_ok(m, "lastCancel")
        or any(_tool_art(t) == "cancel" and _tool_eindeutig_ok(t) for t in tools),
        "move": _marker_ok(m, "lastMove")
        or any(_tool_art(t) == "move" and _tool_eindeutig_ok(t) for t in tools),
        "note": _marker_ok(m, "lastNote")
        or bool(_s(m.get("praxisNotiz")))
        or any(_tool_art(t) == "note" and _tool_eindeutig_ok(t) for t in tools),
        "transfer": _marker_ok(m, "lastTransfer")
        or bool(m.get("weiterleitungZiel"))
        or any(_tool_art(t) == "transfer" and _tool_eindeutig_ok(t) for t in tools)
        or any(
            bool(z.get("transfer"))
            for z in (m.get("zuege") or [])
            if isinstance(z, dict)
        ),
        "phone": any(
            _tool_art(t) == "phone" and _tool_eindeutig_ok(t) for t in tools
        ),
        "patient": _marker_ok(m, "lastCreate")
        or any(_tool_art(t) == "patient" and _tool_eindeutig_ok(t) for t in tools),
    }


def harte_fehler(manifest: dict[str, Any] | None) -> list[str]:
    """Persistierte harte Fehlergrenze für Ergebnisseite UND Tages-Scorer.

    Die Manifest-Belege sind die einzige Wahrheit. Ein erfolgreicher Retry
    räumt den vorangegangenen Werkzeugfehler aus der harten Fehlerklasse;
    eine bloße Rückrufnotiz ist ein ehrlicher Abschluss und niemals ein Fail.
    """
    m = manifest if isinstance(manifest, dict) else {}
    tools = _alle_tools(m)
    evidenz = _abschluss_evidenz(m)
    aus: list[str] = []

    for art in sorted(_WRITE_PARTS):
        if evidenz.get(art):
            continue
        if any(
                _tool_art(t) == art and _tool_eindeutig_fehlgeschlagen(t)
                for t in tools):
            aus.append(f"write_fehlgeschlagen:{art}")

    # Auch echte Lese-/Cloud-Fehler bleiben sichtbar. Ein später erfolgreicher
    # Aufruf desselben Werkzeugs beweist einen gelungenen Retry.
    erfolgreiche_namen = {
        _tool_name(t) for t in tools if _tool_name(t) and _tool_eindeutig_ok(t)
    }
    for tool in tools:
        name = _tool_name(tool)
        if (
                _tool_art(tool)
                or _designed_leer(tool)
                or not _tool_eindeutig_fehlgeschlagen(tool)
                or name in erfolgreiche_namen):
            continue
        aus.append(f"technik:{name or 'werkzeug'}")

    if patient_nicht_gefunden(m):
        aus.append("patient_nicht_gefunden")

    mund = _fold(" ".join(_outputs(m)))
    for art, muster in _ERFOLG_CLAIMS.items():
        if muster.search(mund) and not evidenz.get(art, False):
            aus.append(f"erfolg_ohne_beweis:{art}")

    outputs = _outputs(m)
    unklar_n = sum(1 for text in outputs if _UNKLAR_RE.search(text))
    presence_n = sum(1 for text in outputs if _PRESENCE_RE.search(text))
    sonst_n = sum(1 for text in outputs if _SONST_NOCH_RE.search(text))
    wiederholt_n, wiederholt_text = _frage_wiederholt_detail(outputs)
    if unklar_n >= 2:
        aus.append(f"unklar_schleife:{unklar_n}")
    if presence_n >= 2:
        aus.append(f"presence_schleife:{presence_n}")
    if sonst_n >= 3:
        aus.append(f"sonst_noch_schleife:{sonst_n}")
    if wiederholt_n >= 2:
        aus.append(f"frage_wiederholt:{wiederholt_n}:{wiederholt_text}")

    eindeutig: list[str] = []
    for grund in aus:
        if grund not in eindeutig:
            eindeutig.append(grund)
    return eindeutig


def _online_link_belegt(m: dict[str, Any]) -> bool:
    beleg = m.get("onlineBuchungslink")
    if isinstance(beleg, dict):
        return bool(beleg.get("ok") or beleg.get("gesendet"))
    return bool(beleg)


def patient_nicht_gefunden(manifest: dict[str, Any] | None) -> bool:
    """Eine Patienten-/Terminsuche lief ins Leere UND das Anliegen wurde nicht
    anderweitig gelöst (kein Termin, keine echte Buchung, kein Online-Link).

    Chef: „Patient nicht gefunden … darf es nicht geben“ — deshalb ein eigener,
    scharf belegter Fehlergrund. Ein bloßes ``no_upcoming`` (Patient gefunden,
    nur ohne kommenden Termin) ist KEIN „nicht gefunden“. Eine reine
    Rückrufnotiz räumt den Fehler bewusst NICHT weg (Rückruf ist die absolute
    Ausnahme, nicht der Normalweg)."""
    m = manifest if isinstance(manifest, dict) else {}
    leergelaufen = False
    for t in m.get("tools") or []:
        if not isinstance(t, dict):
            continue
        name = _s(t.get("name") or t.get("cf")).lower()
        if not any(x in name for x in _PATIENT_LESER):
            continue
        d = t.get("dispatch") if isinstance(t.get("dispatch"), dict) else {}
        r = d.get("response") if isinstance(d.get("response"), dict) else {}
        status = _s(r.get("status") or t.get("status")).lower()
        if t.get("notFound") or status in {"not_found", "ambiguous"}:
            leergelaufen = True
    if not leergelaufen:
        return False
    if (_ok(m.get("lastBook")) or _ok(m.get("lastCancel"))
            or _ok(m.get("lastMove")) or _ok(m.get("lastCreate"))):
        return False
    if _online_link_belegt(m):
        return False
    return True


def bianca_fehler(manifest: dict[str, Any] | None) -> list[str]:
    """Nachweisbare, von Bianca ausgelöste Dialogfehler (leere Liste = kein Fehler).

    Die Detailgründe kommen ausschließlich aus ``harte_fehler``. Diese
    Projektion hält die historischen kurzen Labels der Ergebnisseite stabil.
    Anruferabbrüche und ehrliche Rückrufnotizen stehen bewusst NICHT darin."""
    gruende: list[str] = []
    for detail in harte_fehler(manifest):
        if detail.startswith(("write_fehlgeschlagen:", "technik:")):
            grund = "technik"
        elif detail.startswith("erfolg_ohne_beweis:"):
            grund = "unbelegte_erfolgsaussage"
        elif detail.startswith("unklar_schleife:"):
            grund = "missverstaendnis"
        elif detail.startswith(("frage_wiederholt:", "sonst_noch_schleife:")):
            grund = "wiederholungsschleife"
        elif detail.startswith("presence_schleife:"):
            grund = "presence_schleife"
        else:
            grund = detail
        gruende.append(grund)
    aus: list[str] = []
    for g in gruende:
        if g not in aus:
            aus.append(g)
    return aus


def ist_bianca_fehler(manifest: dict[str, Any] | None) -> bool:
    return bool(bianca_fehler(manifest))


def anruf_wertung(manifest: dict[str, Any] | None) -> tuple[str, list[str]]:
    """('fehler'|'ok'|'neutral', Gründe) — eine Wahrheit für alle Auswertungen.

    * ``fehler``: Bianca hat einen nachweisbaren Dialogfehler gemacht.
    * ``ok``: jedes erkannte Anliegen ist belegt oder sauber abgeschlossen.
    * ``neutral``: kein Job erkannt ODER der Anrufer hat abgebrochen/abgelehnt,
      ohne dass Bianca einen Fehler gemacht hat — zählt weder als Fehler noch
      als Erfolg."""
    m = manifest if isinstance(manifest, dict) else {}
    gruende = bianca_fehler(m)
    if gruende:
        return "fehler", gruende
    jobs = ids_von(m)
    if not jobs:
        return "neutral", []
    if all(erledigt(m, i) for i in jobs):
        return "ok", []
    return "neutral", []
