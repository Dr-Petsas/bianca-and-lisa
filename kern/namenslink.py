"""Namens-SMS für Neupatienten aller Live-Praxen.

Platzhalter-Termin sofort, Gespräch läuft weiter. Der getippte Name wird
nachgereicht. Dokumenten-SMS erst nach Bestätigen. Nach 90 Minuten
verfällt die Reservierung ohne Erinnerung.

Kein SMS-Reply (alphanumerischer Praxis-Absender). Notaus: NAMENS_LINK=0.
"""

from __future__ import annotations

import os
import re
from typing import Any

from kern import patients
from kern.calendar import _cf_call
from kern.config import DEV_PHONE

Melde = Any

_ANKUENDIGUNG = (
    "Ich schicke Ihnen kurz eine SMS. "
    "Bitte tippen Sie dort Ihren Vor- und Nachnamen ein, "
    "während wir weiter telefonieren."
)
_ANKUENDIGUNG_PREFILL = (
    "Ich schicke Ihnen kurz eine SMS. "
    "Prüfen Sie dort bitte, ob ich den Namen richtig verstanden habe — "
    "wir können am Telefon schon weiter machen."
)
RESERVIERUNG_ERKLAERUNG = (
    "Da Sie Neupatient sind und wir keine Akte von Ihnen haben, "
    "schicke ich Ihnen eine SMS. Öffnen Sie bitte die SMS und den Link. "
    "Sie haben neunzig Minuten Zeit, Ihre Daten einzutragen, bevor die "
    "Reservierung verfällt. Sobald Sie Ihre Daten abgesendet haben, "
    "erhalten Sie die Terminbestätigung und einen weiteren Link — "
    "dort füllen Sie bitte die Dokumente zur Erstuntersuchung genauso aus."
)
ABSCHLUSS = (
    "Okay, ich reserviere Ihnen jetzt einen Termin. "
    + RESERVIERUNG_ERKLAERUNG
)
ABSCHLUSS_NACH_ERKLAERUNG = (
    "Gut, der Termin ist reserviert. Die SMS ist unterwegs — "
    "bitte öffnen Sie den Link."
)
ABSCHLUSS_SCHON_DA = (
    "Gut, der Termin ist reserviert. In der SMS, die Sie bekommen haben, "
    "öffnen Sie bitte den Link. Sie haben neunzig Minuten Zeit, Ihre Daten "
    "einzutragen, bevor die Reservierung verfällt. "
    "Sobald Sie Ihre Daten abgesendet haben, erhalten Sie die "
    "Terminbestätigung und einen weiteren Link — dort füllen Sie bitte "
    "die Dokumente zur Erstuntersuchung genauso aus."
)
HANDY_FRAGE_FESTNETZ = (
    "An die Festnetznummer kann ich keine SMS schicken. "
    "Unter welcher Handynummer darf ich Ihnen die Bestätigung schicken?"
)
HANDY_FRAGE = (
    "Für die Bestätigung per SMS brauche ich eine Handynummer — "
    "unter welcher Nummer erreichen wir Sie?"
)

_UNSICHER_KONSONANTEN = re.compile(r"[bcdfghjklmnpqrstvwxyzß]{5,}", re.I)
_UNSICHER_MUELL = re.compile(r"\d|[^A-Za-zÄÖÜäöüß\- ]")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _ziffern(raw: str) -> str:
    return "".join(c for c in str(raw or "") if c.isdigit())


def aktiv() -> bool:
    return (os.getenv("NAMENS_LINK", "1") or "1").strip().lower() not in {
        "0", "false", "off", "no",
    }


# Eingebaute Testhandys — später mit dem ganzen Canary-Pfad wieder raus.
# Chef + Kiriakos Tzannis (01525304756). Extra nur über NAMENS_LINK_CANARY.
_CANARY_HANDYS = (DEV_PHONE, "01525304756")


def canary_ziffern() -> set[str]:
    """Chef-Handy und Kiriakos, plus optionale Extra-Nummern aus NAMENS_LINK_CANARY."""
    nummern = set()
    for roh in _CANARY_HANDYS:
        t = _ziffern(patients.handy_e164(roh) or roh)
        if t:
            nummern.add(t)
    extra = os.getenv("NAMENS_LINK_CANARY", "") or ""
    for teil in extra.split(","):
        t = _ziffern(patients.handy_e164(teil) or teil)
        if len(t) >= 10:
            nummern.add(t)
    return {n for n in nummern if n}


def ist_canary(phone: str) -> bool:
    d = _ziffern(patients.handy_e164(phone) or phone)
    return bool(d and d in canary_ziffern())


def leitung(sit: dict) -> str:
    """Angerufene Leitung — Festnetz oder Handy, noch ohne SMS-Tauglichkeit."""
    an = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
    for roh in (an.get("telefon"), sit.get("callerPhone")):
        n = patients.handy_e164(str(roh or ""))
        if len(_ziffern(n)) >= 7:
            return n
    return ""


def ist_festnetz_anrufer(sit: dict) -> bool:
    n = leitung(sit)
    return bool(n and not patients.ist_handy_de(n))


def handy(sit: dict) -> str:
    """Nur echte Mobilnummer — Festnetz der Leitung zählt nie als SMS-Ziel."""
    an = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    for roh in (
        s.get("telefon") if s.get("telefonOk") else "",
        s.get("telefonBekannt"),
        s.get("kontaktTelefon"),
        an.get("telefon"),
    ):
        if patients.ist_handy_de(str(roh or "")):
            return patients.handy_e164(str(roh))
    return ""


def handy_frage(sit: dict) -> str:
    return HANDY_FRAGE_FESTNETZ if ist_festnetz_anrufer(sit) else HANDY_FRAGE


def erlaubt(sit: dict) -> bool:
    """Namens-SMS, sobald ein Handy als Ziel da ist — alle Live-Praxen."""
    return aktiv() and bool(handy(sit))


# TEST-ONLY: Chef-Handy nicht als bekannten Patienten behandeln.
# Spaeter raus: NAMENS_LINK_UNBEKANNT=0 oder diese Bloecke + Aufrufe loeschen.
def test_unbekannt_aktiv() -> bool:
    return (os.getenv("NAMENS_LINK_UNBEKANNT", "1") or "1").strip().lower() not in {
        "0", "false", "off", "no",
    }


def test_unbekannt(sit: dict) -> bool:
    """Nur Testanrufe vom Chef-Handy: Nummer merken, Identität nicht vorsprechen."""
    return aktiv() and test_unbekannt_aktiv() and (
        ist_canary(leitung(sit)) or ist_canary(handy(sit))
    )


PLATZHALTER_VORNAME = "Reservierung"
PLATZHALTER_NACHNAME = "SMS"


def platzhalter_name() -> tuple[str, str]:
    return PLATZHALTER_VORNAME, PLATZHALTER_NACHNAME


def ist_platzhalter_name(first: str, last: str = "", name: str = "") -> bool:
    return patients.ist_platzhalter_name(first, last, name)


def ohne_stammdaten(sit: dict) -> bool:
    """Neupatient ohne bekannte Akte: kein Name/Versicherung am Telefon."""
    if not aktiv() or verifiziert(sit):
        return False
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if test_unbekannt(sit):
        return _s(s.get("modus")) in {"", "buchen"}
    if _s(s.get("modus")) != "buchen":
        return False
    if s.get("bekannt") or _s(s.get("anruferCheck")) == "ja":
        return False
    if s.get("warSchonMal") is True:
        return False
    a = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
    if _s(a.get("nachname")) and _s(a.get("telefon")):
        return False
    return True


def erkannte_nummer(sit: dict) -> str:
    """Die für den Platzhalter-Termin geltende Nummer — bis das Formular sie bestätigt oder ersetzt."""
    stand = _stand(sit)
    for roh in (handy(sit), stand.get("phone"), leitung(sit)):
        if patients.ist_handy_de(str(roh or "")):
            return patients.handy_e164(str(roh))
    return ""


def nummer_parken(sit: dict) -> str:
    """Nummer erkennen und für SMS/Platzhalter speichern — ohne Identität."""
    if not aktiv():
        return ""
    s = sit.setdefault("sammler", {})
    n = leitung(sit) or handy(sit)
    if not n:
        return ""
    sit["namenslink"] = {**_stand(sit), "phone": n, "leitung": n}
    e164 = erkannte_nummer(sit)
    if e164:
        s["telefonBekannt"] = e164
        if not s.get("telefonOk"):
            s["telefon"] = e164
            s["telefonOk"] = True
            s["telefonAkte"] = False
    return n


def _gehoert_merken(sit: dict, s: dict) -> None:
    """Gehörten Namen für die SMS behalten, bevor der Platzhalter ihn ersetzt."""
    if s.get("nameVerified") or s.get("nameQuelle") == "platzhalter":
        return
    first, last = _s(s.get("vorname")), _s(s.get("nachname"))
    if not first and not last:
        return
    if ist_platzhalter_name(first, last):
        return
    stand = _stand(sit)
    sit["namenslink"] = {
        **stand,
        "gehoertVorname": first or _s(stand.get("gehoertVorname")),
        "gehoertNachname": last or _s(stand.get("gehoertNachname")),
    }


def gehoerte_namen(sit: dict) -> tuple[str, str]:
    stand = _stand(sit)
    return _s(stand.get("gehoertVorname")), _s(stand.get("gehoertNachname"))


def _platzhalter_setzen(s: dict) -> None:
    vor, nach = platzhalter_name()
    s["vorname"] = vor
    s["nachname"] = nach
    s["name"] = f"{vor} {nach}"
    s["platzhalterName"] = True
    s["buchstabiert"] = True
    s["vornameQuelle"] = "platzhalter"
    s["nameQuelle"] = "platzhalter"
    s["geschlecht"] = ""
    s["geschlechtQuelle"] = "platzhalter"


def stammdaten_parken(sit: dict) -> None:
    """Neupatient: Kalender bekommt den Platzhalter, die SMS das Gehörte.

    Eine fremde Handynummer wird zuerst nach dem Namen gefragt. Der Name
    wird nicht als Tatsache vorgesprochen. Sobald Vor- und Nachname da sind,
    merkt Bianca sie für das Formular und bucht weiter als Reservierung SMS.
    Die Chef-Testleitung parkt sofort, damit keine Kartei-Identität durchrutscht.
    """
    nummer_parken(sit)
    if not ohne_stammdaten(sit):
        return
    # Ohne Handy gibt es keine Namens-SMS. Die normale Fragenkette
    # (schon einmal da, Buchstabieren) bleibt dann stehen.
    if not erlaubt(sit):
        return
    s = sit.setdefault("sammler", {})
    if not _s(s.get("anruferCheck")):
        s["anruferCheck"] = "skip"
    if not _s(s.get("fuerWenCheck")):
        s["fuerWenCheck"] = "ja"
    if s.get("warSchonMal") is None:
        s["warSchonMal"] = False
    s["patientId"] = ""
    s["bekannt"] = False
    if not s.get("nameVerified"):
        s["nameNurGehoert"] = True
        _gehoert_merken(sit, s)
        first, last = _s(s.get("vorname")), _s(s.get("nachname"))
        if (
            test_unbekannt(sit)
            or ist_platzhalter_name(first, last)
            or (first and last)
        ):
            if not ist_platzhalter_name(first, last):
                _platzhalter_setzen(s)
    if not _s(s.get("versicherung")):
        s["versicherung"] = "gesetzlich"
        s["versicherungOk"] = True
    sit["patient"] = {}


def _stand(sit: dict) -> dict:
    raw = sit.get("namenslink")
    return raw if isinstance(raw, dict) else {}


def verifiziert(sit: dict) -> bool:
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    return bool(s.get("nameVerified") or _stand(sit).get("verified"))


def offen(sit: dict) -> bool:
    return bool(_stand(sit).get("token") and not verifiziert(sit)
                and not _stand(sit).get("expired"))


def unsicher(sit: dict) -> bool:
    if verifiziert(sit):
        return False
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if s.get("bekannt") or s.get("buchstabiert"):
        return False
    nach = _s(s.get("nachname"))
    vor = _s(s.get("vorname"))
    if s.get("nachnameKlaeren"):
        return True
    if sit.get("kandidaten"):
        return True
    for teil in (nach, vor):
        if not teil:
            continue
        if len(teil) <= 2 or len(teil) >= 14:
            return True
        if _UNSICHER_MUELL.search(teil) or _UNSICHER_KONSONANTEN.search(teil):
            return True
    return False


def soll_statt_buchstabieren(sit: dict) -> bool:
    if not erlaubt(sit) or verifiziert(sit):
        return False
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if s.get("bekannt") or _s(s.get("anruferCheck")) == "ja":
        return unsicher(sit)
    if s.get("warSchonMal") is False:
        return True
    return unsicher(sit)


def skip_documents(sit: dict) -> bool:
    """Erste Buchung ohne Dokumenten-SMS — der Link ist die Bestätigung."""
    if not erlaubt(sit) or verifiziert(sit):
        return False
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    return bool(
        s.get("platzhalterName")
        or ohne_stammdaten(sit)
        or _stand(sit).get("token")
    )


def abschluss_satz(sit: dict) -> str:
    if not skip_documents(sit):
        return ""
    if sit.get("_reservierungErklaert"):
        return ABSCHLUSS_NACH_ERKLAERUNG
    if _stand(sit).get("sent") or offen(sit):
        return ABSCHLUSS_SCHON_DA
    return ABSCHLUSS


def _anwenden(sit: dict, first: str, last: str) -> None:
    s = sit.setdefault("sammler", {})
    s["vorname"] = _s(first)
    s["nachname"] = _s(last)
    s["name"] = f"{_s(first)} {_s(last)}".strip()
    s["buchstabiert"] = True
    s["vornameQuelle"] = "gesagt"
    s["nameQuelle"] = "typed"
    s["nameVerified"] = True
    s["nameNurGehoert"] = False
    s["platzhalterName"] = False
    sit["gefunden"] = []
    sit["gefundenKey"] = ""
    sit["kandidaten"] = []
    sit["namenslink"] = {
        **_stand(sit),
        "done": True,
        "verified": True,
        "source": "typed_by_patient",
    }


def starten(sit: dict, *, dry_run: bool = False, parallel: bool = False) -> dict | None:
    if not erlaubt(sit):
        return None
    if verifiziert(sit):
        return None
    if _stand(sit).get("token"):
        return None if parallel else warten(sit)
    phone = handy(sit)
    if not phone:
        return None
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    first = _s(s.get("vorname"))
    last = _s(s.get("nachname"))
    if ist_platzhalter_name(first, last) or s.get("nameQuelle") == "platzhalter":
        first, last = gehoerte_namen(sit)
    status, data, _dispatch = _cf_call("agentNameConfirm", {
        "action": "create",
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "sessionId": _s(sit.get("id") or sit.get("sessionId")),
        "phone": phone,
        "firstName": first,
        "lastName": last,
        "appointmentId": _s(s.get("appointmentId") or sit.get("lastBookId")),
        "patientId": _s(s.get("patientId")),
        "start": _s(s.get("slotIso") or sit.get("lastBookIso")),
        "dryRun": bool(dry_run or tenant.get("_testNoWrite")),
    })
    if status != 200 or not isinstance(data, dict) or not data.get("token"):
        return None
    sit["namenslink"] = {
        "token": _s(data.get("token")),
        "url": _s(data.get("url")),
        "sent": bool(data.get("sent") or data.get("dryRun")),
        "parallel": bool(parallel),
        "firstNameHint": first,
        "lastNameHint": last,
    }
    text = _ANKUENDIGUNG_PREFILL if (first or last) else _ANKUENDIGUNG
    if parallel:
        if ohne_stammdaten(sit) or ist_platzhalter_name(
            _s(s.get("vorname")), _s(s.get("nachname"))
        ):
            return {"text": ""}
        sit["_namenslinkSatz"] = text
        return {"text": text}
    s = sit.setdefault("sammler", {})
    s["frage"] = "namenslink"
    return {"text": text}


def termin_binden(sit: dict, appointment_id: str, patient_id: str = "") -> None:
    """Nach der Platzhalter-Buchung Termin und Link zusammenhängen."""
    if not erlaubt(sit):
        return
    token = _s(_stand(sit).get("token"))
    aid = _s(appointment_id)
    if not token or not aid:
        return
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    _cf_call("agentNameConfirm", {
        "action": "bind",
        "token": token,
        "appointmentId": aid,
        "patientId": _s(patient_id),
        "start": _s(s.get("slotIso") or sit.get("lastBookIso")),
    })
    sit["namenslink"] = {**_stand(sit), "appointmentId": aid}


def status_holen(sit: dict) -> dict:
    stand = _stand(sit)
    token = _s(stand.get("token"))
    if not token:
        return {}
    status, data, _dispatch = _cf_call("agentNameConfirm", {
        "action": "status",
        "token": token,
    })
    return data if status == 200 and isinstance(data, dict) else {}


def einziehen(sit: dict) -> dict:
    nummer_parken(sit)
    if ohne_stammdaten(sit):
        stammdaten_parken(sit)
    if not erlaubt(sit) or verifiziert(sit) or not _stand(sit).get("token"):
        return {}
    data = status_holen(sit)
    if data.get("status") == "done" and _s(data.get("lastName")):
        _anwenden(sit, _s(data.get("firstName")), _s(data.get("lastName")))
        return data
    if data.get("status") == "expired":
        sit["namenslink"] = {**_stand(sit), "expired": True}
    return data


def warten(sit: dict) -> dict:
    s = sit.setdefault("sammler", {})
    s["frage"] = "namenslink"
    return {"text": _ANKUENDIGUNG}


def braucht_vor_buchung(sit: dict) -> bool:
    """Gespräch wartet nicht — der Slot wird als Vorlage gehalten."""
    return False


def zug(sit: dict, gesagt: str, neu: set[str], melde: Melde = None,
        *, stille: bool = False) -> dict | None:
    if not erlaubt(sit) and _s((sit.get("sammler") or {}).get("frage")) != "namenslink":
        return None
    s = sit.setdefault("sammler", {})
    blocking = _s(s.get("frage")) == "namenslink"
    if not blocking and not stille:
        einziehen(sit)
        return None
    data = einziehen(sit) if stille else status_holen(sit)
    if data.get("status") == "done" and _s(data.get("lastName")):
        if not verifiziert(sit):
            _anwenden(sit, _s(data.get("firstName")), _s(data.get("lastName")))
        s["frage"] = ""
        neu.update({"name", "vorname", "nachname"})
        from bianca import verwalten
        return verwalten._dispatch(sit, melde)
    if data.get("status") == "expired":
        s["frage"] = "nachname"
        return {"text": (
            "Der Link ist abgelaufen. Sagen Sie den Nachnamen bitte noch einmal."
        )}
    if stille:
        return {"text": ""}
    t = _s(gesagt)
    if t and t.casefold() not in {"ja", "ok", "okay", "gut", "mhm", "hm"} and s.get("nachname"):
        s["frage"] = ""
        sit["namenslink"] = {**_stand(sit), "spoken": True}
        from bianca import verwalten
        return verwalten._dispatch(sit, melde)
    return {"text": (
        "Ich warte noch auf die Angabe in der SMS. "
        "Sie können den Namen auch einfach sagen."
    )}
