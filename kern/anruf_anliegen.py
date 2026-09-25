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


def _outputs(m: dict[str, Any]) -> list[str]:
    aus: list[str] = []
    for z in m.get("zuege") or []:
        if not isinstance(z, dict):
            continue
        t = _s(z.get("text"))
        if t:
            aus.append(t)
    return aus


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


def _frage_wiederholt(outputs: list[str]) -> int:
    zaehl: dict[str, int] = {}
    for text in outputs:
        for satz in re.split(r"(?<=[?])\s+", text):
            if "?" not in satz:
                continue
            norm = re.sub(r"[^a-z0-9äöüß]+", " ", satz.lower()).strip()
            if len(norm) >= 8:
                zaehl[norm] = zaehl.get(norm, 0) + 1
    return max(zaehl.values(), default=0)


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
        return _ok(m.get("lastBook")) or bool(_s(m.get("praxisNotiz"))) or "112" in mund
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
        return _ok(manifest.get("lastCancel"))
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
        return _ok(manifest.get("lastBook")) or bool(_s(manifest.get("praxisNotiz")))
    return False


def erledigt(manifest: dict[str, Any] | None, anliegen_id: str) -> bool:
    """Belegter Abschluss oder sauberer Gesprächsschluss durch den Anrufer."""
    m = manifest if isinstance(manifest, dict) else {}
    kid = _s(anliegen_id)
    if kid in ("arzt_sprechen", "mitarbeiter_sprechen") and (
            _verbindung_technisch_gescheitert(m)):
        return False
    if _erledigt_beleg(m, kid):
        return True
    return guter_anrufer_abschluss(m)
