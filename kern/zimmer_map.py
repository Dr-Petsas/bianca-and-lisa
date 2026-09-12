"""Thaler: Besuchsgrund -> Zimmer (Chef 08.09.2026).

Die Cloud Function liefert nur einen Arztkalender (Eva). Thaler bucht
telefonisch NUR sechs freigegebene Besuchsgrund-Gruppen:

- Neupatient / Erstuntersuchung
- Kontrolle
- Schmerzen / Akut
- Besprechung Zahnersatz
- Besprechung Implantate
- professionelle Zahnreinigung

Andere Katalogtermine werden weder direkt gebucht noch angeboten. Eine
Fuellung wird nach Chef-Vorgabe als Zahnersatz-Besprechung aufgenommen.

Raeumlich gilt:

- Prophylaxe / PZR -> Kalender Prophylaxe, Zimmer 3, wenn voll Zimmer 2
- alle Haupttermine -> bei Thaler selbst in Zimmer 4

Live stehen Zimmer in der rooms-Sammlung, nicht als Kalender. Gibt es
Kalender namens Zimmer 1-4 (Tests), suchen wir dort. Sonst: PZR auf
Prophylaxe, alles andere auf Eva.

Nur dieser Mandant. MedDent bleibt unveraendert.
"""

from __future__ import annotations

import re
from typing import Any

from kern import tenants as kern_tenants

THALER_CLIENT = "7tTnJZfJkb801r2rmYed"

# Reihenfolge = Suchreihenfolge (erster Treffer mit Slots gewinnt).
DEFAULT_MAP = {
    "pzr": [3, 2],
    "akut": [4],
    "behandlung": [4],
}

# Harte Telefon-Freigabe fuer Thaler (Chef 09.09.2026). Absichtlich gegen
# stabile Katalog-IDs UND Namen: Der Live-Katalog kommt pro Anruf aus der DB,
# lokale tenants-Dateien sind nicht die Wahrheit. Eng halten — insbesondere
# keine IMP/ZE/KFO-*Kontrollen*, keine OPs und keine PAR-PZR.
_BUCHBARE_MOTIVE = (
    re.compile(r"^kch-erstuntersuchung-neupatient(?:-|$)|^kch\s+erstuntersuchung\s*/\s*neupatient$", re.I),
    re.compile(r"^kch-kontrolluntersuchung(?:-|$)|^kch\s+kontrolluntersuchung$", re.I),
    re.compile(r"^kch-akute-beschwerden-notfall(?:-|$)|^kch\s+akute\s+beschwerden\s*/\s*notfall$", re.I),
    re.compile(r"^imp-besprechung(?:-|$)|^imp\s+besprechung$", re.I),
    re.compile(r"^ze-besprechung(?:-|$)|^ze\s+besprechung$", re.I),
    re.compile(r"^pro-professionelle-zahnreinigung(?:-|$)|^pro\s+professionelle\s+zahnreinigung$", re.I),
)

_NEUPATIENT_RE = re.compile(r"\bneupatient\w*|\berst(?:untersuchung|besuch)\w*", re.I)
_KONTROLLE_RE = re.compile(r"\bkontroll\w*|\bvorsorge\b|\bcheck-?up\b", re.I)
_SCHMERZ_RE = re.compile(
    r"schmerz|zahnweh|\bweh\b|\bakut\w*|\bnotfall\b|dicke\s+backe|"
    r"geschwollen|entzünd|entzuend|pocht|eiter",
    re.I,
)
_IMPLANTAT_RE = re.compile(r"\bimplant\w*", re.I)
_ZAHNERSATZ_RE = re.compile(
    r"\bzahnersatz\b|\bprothese\w*|\bkrone\w*|\bbrücke\w*|\bbruecke\w*|"
    r"\bfüll\w*|\bfuell\w*|\binlay\w*|\bveneer\w*",
    re.I,
)
_PZR_RE = re.compile(
    r"\bzahnreinigung\w*|\bprophylaxe\b|\bpzr\b|\bzahnstein\w*",
    re.I,
)
_NICHT_BUCHBAR_RE = re.compile(
    r"\b(?:wurzel(?:behandlung|kanal)?|endo|zahn\s*ziehen|extraktion|"
    r"naht(?:entfernung)?|kieferorthop|zahnspange|invisalign|schiene|cmd|"
    r"parodont|zahnfleisch(?:behandlung|op)?|bleaching|aufhellung|"
    r"abdruck|scan|implantation|freilegung|knochenaufbau|augmentation|"
    r"reparatur|eingliederung|provisorium|heil-?\s*und-?\s*kostenplan)\b",
    re.I,
)

# Spur-Frage: Frau Thaler oder Prophylaxe — kein Behandler-Roster.
_PZR_SPUR_RE = re.compile(
    r"prophylaxe|hygiene|\bpzr\b|zahnreinigung|zahnstein",
    re.I,
)
_PZR_NEIN_RE = re.compile(
    r"\bnicht\s+(?:zur\s+|die\s+|eine\s+)?(?:prophylaxe|zahnreinigung|\bpzr\b)|"
    r"\bkeine\s+(?:prophylaxe|zahnreinigung)",
    re.I,
)
_THALER_SPUR_RE = re.compile(
    r"\bthaler\b|\bkahler\b|\bparler\b|\btahler\b|\btaler\b|"
    r"bei\s+(?:ihr|frau|der\s+zahnaerztin|der\s+zahnärztin|"
    r"der\s+aerztin|der\s+ärztin)|"
    r"zur\s+(?:zahnaerztin|zahnärztin)|"
    r"\bzahn(?:arzt|aerztin|ärztin)\b",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def aktiv(tenant: dict[str, Any] | None) -> bool:
    """Nur mit ausdruecklicher Karte oder Thaler-clientId."""
    if not isinstance(tenant, dict):
        return False
    if isinstance(tenant.get("zimmerMap"), dict) and tenant["zimmerMap"]:
        return True
    return _s(tenant.get("clientId")) == THALER_CLIENT


def ist_thaler(tenant: dict[str, Any] | None) -> bool:
    t = tenant if isinstance(tenant, dict) else {}
    return (
        _s(t.get("clientId")) == THALER_CLIENT
        or "thaler" in _s(t.get("praxisName")).casefold()
    )


def motiv_buchbar(vm: dict[str, Any] | None) -> bool:
    """True nur fuer die sechs von Thaler telefonisch freigegebenen Motive."""
    if not isinstance(vm, dict):
        return False
    felder = (_s(vm.get("id")), _s(vm.get("name")))
    return any(cre.search(feld) for cre in _BUCHBARE_MOTIVE for feld in felder)


def buchbarer_katalog(
    tenant: dict[str, Any] | None,
    katalog: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Thaler-Katalog hart begrenzen; alle anderen Praxen byte-identisch."""
    pool = [vm for vm in (katalog or []) if isinstance(vm, dict)]
    if not aktiv(tenant):
        return pool
    return [vm for vm in pool if motiv_buchbar(vm)]


def mapping_text(tenant: dict[str, Any] | None, text: str) -> str:
    """Thaler-Wunsch auf genau eine der sechs Freigaben normalisieren.

    Der Originalwortlaut bleibt separat im Sammler/Termin-Hinweis. Hier wird
    nur das sichere Katalog-Mapping eindeutig gemacht: eine Fuellung,
    Kronenreparatur oder Implantat-OP wird telefonisch als Besprechung
    aufgenommen, nie als Eingriff.
    """
    t = _s(text)
    if not aktiv(tenant):
        return t
    if _SCHMERZ_RE.search(t):
        return "Akute Beschwerden Schmerzen Notfall"
    if _NEUPATIENT_RE.search(t):
        return "Erstuntersuchung Neupatient"
    if _PZR_RE.search(t):
        return "Professionelle Zahnreinigung PZR"
    if _IMPLANTAT_RE.search(t):
        return "Implantat Besprechung Beratung"
    if _ZAHNERSATZ_RE.search(t):
        return "Zahnersatz Besprechung Beratung"
    if _KONTROLLE_RE.search(t):
        return "Kontrolluntersuchung Kontrolle"
    return t


def klar_nicht_buchbar(tenant: dict[str, Any] | None, text: str) -> bool:
    """Expliziter, nicht freigegebener Behandlungswunsch bei Thaler."""
    t = _s(text)
    if not aktiv(tenant) or not t:
        return False
    if any(cre.search(t) for cre in (
            _SCHMERZ_RE, _NEUPATIENT_RE, _PZR_RE,
            _IMPLANTAT_RE, _ZAHNERSATZ_RE, _KONTROLLE_RE)):
        return False
    return bool(_NICHT_BUCHBAR_RE.search(t))


def buchbare_ansage() -> str:
    return (
        "Telefonisch kann ich bei Frau Thaler momentan Termine für "
        "Neupatienten, Kontrollen, Schmerzen, Besprechungen zu Zahnersatz "
        "oder Implantaten und professionelle Zahnreinigungen buchen. "
        "Welcher dieser Gründe passt zu Ihrem Anliegen?"
    )


def buchbare_frage() -> str:
    return (
        "Worum geht es denn — Neupatient, Kontrolle, Schmerzen, eine "
        "Besprechung zu Zahnersatz oder Implantaten, oder eine "
        "professionelle Zahnreinigung?"
    )


def karte(tenant: dict[str, Any] | None) -> dict[str, list[int]]:
    roh = (tenant or {}).get("zimmerMap") if isinstance(tenant, dict) else None
    if not isinstance(roh, dict) or not roh:
        return dict(DEFAULT_MAP)
    out = dict(DEFAULT_MAP)
    for key in ("pzr", "akut", "behandlung"):
        nums = roh.get(key)
        if isinstance(nums, list) and nums:
            sauber = []
            for n in nums:
                try:
                    i = int(n)
                except (TypeError, ValueError):
                    continue
                if 1 <= i <= 4 and i not in sauber:
                    sauber.append(i)
            if sauber:
                out[key] = sauber
    if ist_thaler(tenant):
        # Alte DB-Konfigurationen enthielten noch Notfall -> Zimmer 1.
        # Die aktuelle Praxisregel gewinnt: jeder Haupttermin in Zimmer 4.
        out["akut"] = [4]
        out["behandlung"] = [4]
    return out


def gruppe(s: dict | None, sit: dict | None = None) -> str:
    """pzr | akut | behandlung — aus Motiv/Grund, nie geraten als Notfall."""
    from bianca import gehirn
    stand = s if isinstance(s, dict) else {}
    if sit is not None and not stand.get("motivId") and not stand.get("grund"):
        stand = gehirn.sammler(sit)
    if gehirn.ist_pzr_grund(stand):
        return "pzr"
    vm = None
    mid = _s(stand.get("motivId"))
    name = _s(stand.get("motivName"))
    if mid or name:
        vm = {"id": mid, "name": name}
    if gehirn._ist_akut(stand) or kern_tenants.ist_akut_motiv(vm):
        return "akut"
    return "behandlung"


def zimmer_von(tenant: dict[str, Any], nr: int) -> dict[str, Any] | None:
    """Kalender, dessen Name Zimmer/Zi ``nr`` traegt."""
    for c in (tenant or {}).get("calendars") or []:
        if not isinstance(c, dict) or not _s(c.get("id")):
            continue
        if kern_tenants.zimmer_nr(c.get("name")) == nr:
            return c
    return None


def prophylaxe_kalender(tenant: dict[str, Any] | None) -> dict[str, Any] | None:
    """Kalender namens Prophylaxe/Hygiene, sonst Zimmer 3."""
    t = tenant if isinstance(tenant, dict) else {}
    for c in t.get("calendars") or []:
        if not isinstance(c, dict) or not _s(c.get("id")):
            continue
        name = _s(c.get("name"))
        if re.search(r"prophylaxe|hygiene|\bpzr\b", name, re.I):
            return c
    return zimmer_von(t, 3)


def spur_deute(text: str) -> str:
    """pzr | thaler | '' — Antwort auf die Thaler-Spur-Frage."""
    t = _s(text)
    if not t:
        return ""
    if _PZR_SPUR_RE.search(t) and not _PZR_NEIN_RE.search(t):
        return "pzr"
    if _THALER_SPUR_RE.search(t):
        return "thaler"
    return ""


def raeume(tenant: dict[str, Any] | None, grp: str) -> list[dict[str, Any]]:
    """Kalender in Suchreihenfolge: Zimmer 1-4, sonst Prophylaxe/Eva."""
    t = tenant if isinstance(tenant, dict) else {}
    nums = karte(t).get(grp) or []
    out: list[dict[str, Any]] = []
    gesehen: set[str] = set()
    for n in nums:
        cal = zimmer_von(t, int(n))
        cid = _s((cal or {}).get("id"))
        if cal and cid and cid not in gesehen:
            out.append(cal)
            gesehen.add(cid)
    if out:
        return out
    if not aktiv(t):
        return []
    if grp == "pzr":
        p = prophylaxe_kalender(t)
        if p and _s(p.get("id")):
            return [p]
    d = kern_tenants.default_kalender(t)
    if d and _s(d.get("id")):
        return [d]
    return []


def sprechname(tenant: dict[str, Any] | None, grp: str) -> str:
    """Was Bianca sagt — Prophylaxe oder Thaler, nie 'Zimmer 4'."""
    if grp == "pzr":
        return "Prophylaxe"
    d = kern_tenants.default_kalender(tenant or {})
    return _s((d or {}).get("name")) or "Frau Thaler"


def an_arzt(sit: dict) -> None:
    """Sammler-Arzt auf die Zimmer der aktuellen Gruppe setzen."""
    from bianca import gehirn
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    if not aktiv(tenant):
        return
    s = gehirn.sammler(sit)
    if not (s.get("grund") or s.get("motivId")):
        return
    grp = gruppe(s)
    zimmer = raeume(tenant, grp)
    if not zimmer:
        return
    first = zimmer[0]
    ids = [_s(z.get("id")) for z in zimmer if _s(z.get("id"))]
    name = sprechname(tenant, grp)
    alt = dict(s.get("arzt") or {})
    gleich = (
        alt.get("calendarId") == first.get("id")
        and list(alt.get("raeume") or []) == ids
    )
    if gleich:
        alt["calendarName"] = name
        alt["typ"] = alt.get("typ") or "zimmer"
        s["arzt"] = alt
        return
    s["arzt"] = {
        "typ": "zimmer",
        "calendarId": first["id"],
        "calendarName": name,
        "raeume": ids,
    }
    gehirn._vorrat_leeren(sit)


def raeume_am(sit: dict) -> list[dict[str, Any]]:
    """Zimmer-Objekte aus dem schon gesetzten Arzt (Reihenfolge halten)."""
    from bianca import gehirn
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    a = gehirn.sammler(sit).get("arzt") or {}
    ids = [str(x) for x in (a.get("raeume") or []) if str(x).strip()]
    if not ids:
        return []
    by_id = {
        _s(c.get("id")): c
        for c in (tenant.get("calendars") or [])
        if isinstance(c, dict) and _s(c.get("id"))
    }
    return [by_id[i] for i in ids if i in by_id]


def spur_anwenden(sit: dict, welche: str) -> bool:
    """Spur-Antwort binden. pzr setzt Grund + Zimmer, thaler nur Eva."""
    from bianca import gehirn
    s = gehirn.sammler(sit)
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    if welche == "pzr":
        if not s.get("grund"):
            s["grund"] = "Zahnreinigung"
            s["grundWortlaut"] = s.get("grundWortlaut") or "Prophylaxe"
        an_arzt(sit)
        return bool((s.get("arzt") or {}).get("calendarId"))
    if welche == "thaler":
        d = gehirn.arzt_default(tenant)
        if not d:
            return False
        alt = dict(s.get("arzt") or {})
        if alt.get("calendarId") == d.get("calendarId") and alt.get("typ") != "funktion":
            return True
        s["arzt"] = {
            "typ": "genannt",
            "calendarId": d["calendarId"],
            "calendarName": d.get("calendarName") or "Frau Thaler",
        }
        gehirn._vorrat_leeren(sit)
        return True
    return False
