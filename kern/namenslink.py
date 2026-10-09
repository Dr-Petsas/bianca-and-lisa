"""Namens-SMS für Neupatienten aller Live-Praxen.

Platzhalter-Termin sofort, Gespräch läuft weiter. Der getippte Name wird
nachgereicht. Dokumenten-SMS erst nach Bestätigen. Nach 90 Minuten
verfällt die Reservierung ohne Erinnerung.

Kein SMS-Reply (alphanumerischer Praxis-Absender). Notaus: NAMENS_LINK=0.
"""

from __future__ import annotations

import os
import re
import secrets
from typing import Any

from kern import observability_manifest, patients
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
    # P0-CONTAINMENT (02.10.2026): Die sieben Live-Reservierungen landeten als
    # BESTÄTIGTE Termine mit Zufalls-IDs auf einem gemeinsamen Platzhalter-
    # Patienten — der deterministische nca_/ncp_-Vertrag (bookingReservationGuard
    # in pickadoc-live-base) wurde nie geschrieben, die 90-Minuten-Reservierung
    # verfällt also nie. Bis die Cloud Function rückwärtskompatibel repariert und
    # per Canary abgenommen ist (Reparatur-Plan Paket 3), ist der Namenslink
    # AUS. Default bewusst "0": eine beim Deploy überschriebene .env darf ihn
    # nie versehentlich wieder scharf schalten. Wieder-An erst mit NAMENS_LINK=1.
    return (os.getenv("NAMENS_LINK", "0") or "0").strip().lower() not in {
        "0", "false", "off", "no",
    }


def sms_aktiv() -> bool:
    """W-NAMENS-SMS-RETTUNG (05.10.2026): die reine Namens-SMS.

    Chef: „eine sms an die anrufernummer, damit der patient seinen namen
    schreiben und senden kann, wenn bianca das mehrmals nicht versteht".
    Das Containment vom 02.10. schaltete mit ``NAMENS_LINK=0`` BEIDE Hälften
    ab — auch den bewährten Weg ohne Termin (01.10.: acht getippte Namen
    angekommen). Hier läuft nur dieser Weg: kein Platzhalter-Termin, keine
    Reservierung, keine Termin-ID an die Cloud Function. Notaus:
    ``NAMENS_SMS=0``."""
    if aktiv():
        return True
    return (os.getenv("NAMENS_SMS", "1") or "1").strip().lower() not in {
        "0", "false", "off", "no",
    }


def nur_name() -> bool:
    """Namens-SMS ohne Reservierung (der Reservierungsvertrag ist aus)."""
    return sms_aktiv() and not aktiv()


_VERWALTUNG_MODI = {"absagen", "verschieben", "auskunft"}


def sms_verwaltung_aktiv() -> bool:
    """Namens-SMS in Absage/Verschieben/Auskunft (Stufe 1c, Default „1").

    Notaus ``NAMENS_SMS_VERWALTUNG=0``: dann schickt Bianca in diesen Modi
    nie eine reine Namens-SMS, und ``starten()`` legt dort keinen
    Reservierungs-Create ohne Slot an. Das Buchen bleibt unberührt."""
    return (os.getenv("NAMENS_SMS_VERWALTUNG", "1") or "1").strip().lower() not in {
        "0", "false", "off", "no",
    }


def _nur_name_fuer(sit: dict) -> bool:
    """Reine Namensabfrage für diese Sitzung.

    Reserviert wird nur beim Buchen. Absagen, Verschieben und Auskunft haben
    keinen Slot — dort ist die SMS immer nur der Name, auch mit
    ``NAMENS_LINK=1`` (Anruf 205930f8: sonst sagte Bianca „während wir weiter
    telefonieren" und wartete nicht). Für diese Modi lässt sich die
    Namens-SMS über ``NAMENS_SMS_VERWALTUNG=0`` abschalten (Stufe 1c)."""
    if not sms_aktiv():
        return False
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if _s(s.get("modus")) in _VERWALTUNG_MODI:
        return sms_verwaltung_aktiv()
    if not aktiv():
        return True
    return False


# Nach so vielen gescheiterten Namensaufnahmen (Rücklese verneint,
# korrigiert, unklar) schickt Bianca die Namens-SMS, statt erneut
# buchstabieren zu lassen.
NAME_FEHLVERSUCHE_SMS = 2
_ANKUENDIGUNG_RETTUNG = (
    "Damit ich Ihren Namen sicher richtig schreibe, schicke ich Ihnen jetzt "
    "eine SMS. Öffnen Sie bitte den Link in der SMS und tragen Sie dort Ihren "
    "Vor- und Nachnamen ein — ich warte so lange."
)


def fehlversuch(sit: dict) -> int:
    """Eine gescheiterte Namensaufnahme zählen; liefert den neuen Stand."""
    s = sit.setdefault("sammler", {})
    n = int(s.get("nameFehlversuche") or 0) + 1
    s["nameFehlversuche"] = n
    return n


def rettung_faellig(sit: dict) -> bool:
    """Nach wiederholtem Scheitern: Namens-SMS statt nächster Buchstabierrunde."""
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    return bool(
        int(s.get("nameFehlversuche") or 0) >= NAME_FEHLVERSUCHE_SMS
        and erlaubt(sit)
        and not verifiziert(sit)
        and not _stand(sit).get("done")
        and not _stand(sit).get("expired")
        and not _stand(sit).get("createFailed")
        and not _stand(sit).get("abgebrochen")
    )


def rettung_braucht_handy(sit: dict) -> bool:
    """Rettung wäre fällig, es fehlt aber ein Handy (Festnetz/unterdrückt).

    Einmal je Anruf fragt Bianca dann nach einer Handynummer, statt still
    weiter buchstabieren zu lassen (Anruf 205930f8: Festnetz-Anrufer,
    die SMS kam nie in Frage)."""
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    return bool(
        int(s.get("nameFehlversuche") or 0) >= NAME_FEHLVERSUCHE_SMS
        and sms_aktiv()
        and not handy(sit)
        and not verifiziert(sit)
        and not sit.get("namensHandyGefragt")
        and not _stand(sit).get("done")
        and not _stand(sit).get("abgebrochen")
    )


def rettung_starten(sit: dict) -> dict | None:
    """Namens-SMS als Rettung; None, wenn sie nicht gehen kann."""
    if rettung_faellig(sit):
        return starten(sit)
    if rettung_braucht_handy(sit):
        return _handy_frage_start(sit)
    return None


NAMENS_HANDY_FRAGE = "Unter welcher Handynummer darf ich Ihnen die SMS schicken?"
_NAMENS_HANDY_FESTNETZ = (
    "Damit ich Ihren Namen sicher richtig schreibe, würde ich Ihnen gern "
    "eine SMS schicken, in die Sie ihn eintippen. An die Festnetznummer, "
    "von der Sie anrufen, geht das leider nicht. "
)
_NAMENS_HANDY_OHNE = (
    "Damit ich Ihren Namen sicher richtig schreibe, würde ich Ihnen gern "
    "eine SMS schicken, in die Sie ihn eintippen. "
)
_NAMENS_HANDY_AUFGEBEN = (
    "Kein Problem. Dann buchstabieren Sie mir den Nachnamen bitte ganz "
    "langsam, Buchstabe für Buchstabe; am Ende sagen Sie fertig."
)
_NAMENS_HANDY_NEIN_RE = re.compile(
    r"^\s*(?:nein|nee|ne|nö)\b|\bkein(?:e|en)?\s+(?:handy|mobil\w*|sms)\b"
    r"|\bhabe?\s+(?:ich\s+)?(?:leider\s+|gar\s+)?kein(?:e|en|s)?\b(?!\s+(?:andere|zweite|weitere|neue))"
    r"|\bnur\s+(?:ein\s+|das\s+)?festnetz\b"
    r"|\bwill\s+ich\s+nicht\b|\blieber\s+nicht\b",
    re.I,
)


def _handy_frage_start(sit: dict) -> dict:
    s = sit.setdefault("sammler", {})
    sit["namensHandyGefragt"] = True
    sit["namensHandyTeil"] = ""
    sit["namensHandyUnklar"] = 0
    s["frage"] = "namens_handy"
    s["buchstabenTeil"] = ""
    _beobachten(sit, "handy_frage", outcome="festnetz" if ist_festnetz_anrufer(sit) else "ohne")
    vorsatz = _NAMENS_HANDY_FESTNETZ if ist_festnetz_anrufer(sit) else _NAMENS_HANDY_OHNE
    return {"text": vorsatz + NAMENS_HANDY_FRAGE}


def _handy_aufgeben(sit: dict, grund: str) -> dict:
    s = sit.setdefault("sammler", {})
    sit["namensHandyAbgelehnt"] = True
    sit.pop("namensHandyTeil", None)
    sit.pop("namensHandyOffen", None)
    s["frage"] = "buchstabieren"
    s["buchstabenTeil"] = ""
    _beobachten(sit, "handy_frage", outcome=grund)
    return {"text": _NAMENS_HANDY_AUFGEBEN}


def _handy_unklar(sit: dict, text: str) -> dict:
    n = int(sit.get("namensHandyUnklar") or 0) + 1
    sit["namensHandyUnklar"] = n
    if n >= 2:
        return _handy_aufgeben(sit, "unklar")
    return {"text": text, "_wiederholungErlaubt": True}


def _handy_readback(sit: dict, nummer: str) -> dict:
    from bianca import gehirn
    s = sit.setdefault("sammler", {})
    sit["namensHandyOffen"] = nummer
    sit["namensHandyTeil"] = ""
    s["frage"] = "namens_handy_check"
    return {"text": gehirn.readback_text(nummer)}


def _handy_ziffern(sit: dict, t: str) -> dict | None:
    """Ziffern auf die Handyfrage: sammeln, prüfen, vorlesen."""
    from bianca import telefon
    neu = telefon.ziffern(t)
    if not neu:
        return None
    teil = _ziffern(sit.get("namensHandyTeil")) + neu
    nummer = telefon.mit_fuehrender_null(teil)
    if len(nummer) > 13:
        sit["namensHandyTeil"] = ""
        return _handy_unklar(sit, (
            "Da sind mir zu viele Ziffern durcheinander geraten. "
            "Sagen Sie mir die Handynummer bitte noch einmal von vorn?"
        ))
    if len(nummer) >= 11 or (len(nummer) >= 10 and re.search(r"\bfertig\b", t, re.I)):
        if not telefon.ist_handy(nummer):
            sit["namensHandyTeil"] = ""
            return _handy_unklar(sit, (
                "Das ist leider keine Handynummer — dort kommt keine SMS an. "
                "Haben Sie eine Handynummer, die mit null eins beginnt?"
            ))
        return _handy_readback(sit, nummer)
    sit["namensHandyTeil"] = teil
    return {"text": "", "warte": True, "stilleMs": 1500}


def handy_zug(sit: dict, gesagt: str) -> dict | None:
    """Antwort auf die Handyfrage der Namens-SMS (``namens_handy[_check]``).

    Deterministisch wie ``telefon_check``: nie das Modell, nie ungeprüft
    eine Nummer übernehmen. Ablehnen oder zweimal unklar führt zurück ins
    langsame Buchstabieren — nie eine Schleife."""
    s = sit.setdefault("sammler", {})
    frage = _s(s.get("frage"))
    if frage not in {"namens_handy", "namens_handy_check"}:
        return None
    from bianca import gehirn, telefon
    t = _s(gesagt)
    if not t:
        return {"text": "", "warte": True, "stilleMs": 1500}
    if frage == "namens_handy_check":
        offen = _s(sit.get("namensHandyOffen"))
        if telefon.ziffern(t) and len(telefon.ziffern(t)) >= 7:
            sit["namensHandyTeil"] = ""
            s["frage"] = "namens_handy"
            aus = _handy_ziffern(sit, t)
            if aus is not None:
                return aus
        if offen and gehirn.ist_ja(t) and not telefon.check_ist_nein(t):
            sit["namensZielHandy"] = patients.handy_e164(offen)
            sit.pop("namensHandyOffen", None)
            s["frage"] = ""
            aus = starten(sit)
            if aus:
                return aus
            return _handy_aufgeben(sit, "create_failed")
        if telefon.check_ist_nein(t) or gehirn.ist_nein(t):
            sit.pop("namensHandyOffen", None)
            sit["namensHandyTeil"] = ""
            s["frage"] = "namens_handy"
            return _handy_unklar(sit, (
                "Entschuldigung. Dann sagen Sie mir die Handynummer bitte "
                "noch einmal, Ziffer für Ziffer?"
            ))
        return _handy_unklar(sit, (
            gehirn.readback_text(offen) if offen else NAMENS_HANDY_FRAGE
        ))
    aus = _handy_ziffern(sit, t)
    if aus is not None:
        return aus
    if _NAMENS_HANDY_NEIN_RE.search(t) or _SMS_GEHT_NICHT_RE.search(t):
        return _handy_aufgeben(sit, "caller_declined")
    return _handy_unklar(sit, (
        "Sie können mir die Handynummer einfach Ziffer für Ziffer sagen. "
        + NAMENS_HANDY_FRAGE
    ))


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
        # Eben für die Namens-SMS genannt und rückbestätigt (Festnetz-Anrufer).
        sit.get("namensZielHandy"),
        s.get("telefon") if s.get("telefonOk") else "",
        s.get("telefonBekannt"),
        s.get("kontaktTelefon"),
        an.get("telefon"),
        # Die übermittelte Anrufernummer: ein unbekannter Anrufer vom Handy
        # hat sonst nie ein SMS-Ziel — genau der Fall, für den die
        # Namens-SMS gedacht ist.
        sit.get("callerPhone"),
    ):
        if patients.ist_handy_de(str(roh or "")):
            return patients.handy_e164(str(roh))
    return ""


def handy_frage(sit: dict) -> str:
    return HANDY_FRAGE_FESTNETZ if ist_festnetz_anrufer(sit) else HANDY_FRAGE


def erlaubt(sit: dict) -> bool:
    """Namens-SMS, sobald ein Handy als Ziel da ist — alle Live-Praxen."""
    return sms_aktiv() and bool(handy(sit))


# TEST-ONLY: Chef-Handy nur nach ausdruecklichem Opt-in als unbekannt
# behandeln. Produktionsdefault ist AUS — ein korrekt erkannter
# Bestandspatient darf nie wieder zu "Reservierung SMS" werden.
def test_unbekannt_aktiv() -> bool:
    return (os.getenv("NAMENS_LINK_UNBEKANNT", "0") or "0").strip().lower() not in {
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
    # Die Plattform hat mit ``needs_phone`` ausdruecklich verlangt, dass
    # diese Nummer noch einmal bestaetigt wird. Der Platzhalterpfad darf
    # diesen Sicherheitsdialog nicht mit ``telefonOk=True`` umgehen.
    if e164 and not sit.get("needsPhoneOffen"):
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


def _beobachten(
    sit: dict,
    phase: str,
    *,
    status: int | None = None,
    dispatch: dict | None = None,
    outcome: str = "unknown",
) -> None:
    observability_manifest.emit(
        sit,
        "reservation",
        phase,
        http_status=status,
        dispatch=dispatch,
        route_class="name_confirm",
        outcome=outcome,
    )


def _terminal_bereinigen(sit: dict, terminal: str) -> None:
    """Token, URL, Rufnummer, Namens-Hinweise und Termin-IDs lokal verwerfen."""
    sit["namenslink"] = {terminal: True}
    sit.pop("namenslinkReservierung", None)
    sit.pop("_namenslinkSatz", None)
    _beobachten(sit, "cleanup", outcome="cleanup_ok")


def verifiziert(sit: dict) -> bool:
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    return bool(s.get("nameVerified") or _stand(sit).get("verified"))


def reservierungs_scope(sit: dict) -> str:
    """Mandant + konkreter Terminrahmen eines Namenslinks."""
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    booking = sit.get("booking") if isinstance(sit.get("booking"), dict) else {}
    last = sit.get("lastBook") if isinstance(sit.get("lastBook"), dict) else {}
    if _nur_name_fuer(sit):
        # Ohne Reservierung gehört der Link nur zum Anruf, nicht zu einem
        # Slot — sonst verfällt er, sobald der Anrufer einen Termin wählt.
        return "|".join((
            _s(tenant.get("clientId")), _s(tenant.get("locationId")), "name",
        ))
    return "|".join((
        _s(tenant.get("clientId")),
        _s(tenant.get("locationId")),
        _s(
            s.get("slotIso")
            or booking.get("slotIso")
            or sit.get("lastBookIso")
            or last.get("slotIso")
        ),
        _s(s.get("calendarId") or booking.get("calendarId") or last.get("calendarId")),
        _s(
            s.get("motivId")
            or s.get("visitMotiveId")
            or booking.get("visitMotiveId")
            or last.get("visitMotiveId")
        ),
    ))


def _scope_passt(sit: dict, stand: dict | None = None) -> bool:
    stand = stand if isinstance(stand, dict) else _stand(sit)
    scope = _s(stand.get("reservationScope"))
    token = _s(stand.get("reservationToken") or stand.get("token")).lower()
    return bool(
        scope
        and scope == reservierungs_scope(sit)
        and token
    )


def reservierungs_token(sit: dict) -> str:
    """Stabiler, nicht erratbarer Token fuer genau einen Slot-Schreibversuch."""
    scope = reservierungs_scope(sit)
    state = sit.get("namenslinkReservierung")
    if not isinstance(state, dict):
        state = {}
        sit["namenslinkReservierung"] = state
    token = _s(state.get("token")).lower()
    if state.get("scope") != scope or not re.fullmatch(r"[a-f0-9]{32}", token):
        state.clear()
        state.update({"scope": scope, "token": secrets.token_hex(16)})
    return _s(state["token"])


def offen(sit: dict) -> bool:
    return bool(
        _scope_passt(sit)
        and not verifiziert(sit)
        and not _stand(sit).get("expired")
    )


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
    if nur_name():
        # Ohne Reservierung ersetzt die SMS das Buchstabieren nicht von
        # vornherein — sie ist die Rettung nach wiederholtem Scheitern
        # (rettung_starten an den Fehlerstellen).
        return False
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if s.get("bekannt") or _s(s.get("anruferCheck")) == "ja":
        return unsicher(sit)
    if s.get("warSchonMal") is False:
        return True
    return unsicher(sit)


def skip_documents(sit: dict) -> bool:
    """Erste Buchung ohne Dokumenten-SMS — der Link ist die Bestätigung."""
    if not aktiv() or not erlaubt(sit) or verifiziert(sit):
        return False
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    return bool(
        s.get("platzhalterName")
        or ohne_stammdaten(sit)
        or _scope_passt(sit)
    )


def abschluss_satz(sit: dict) -> str:
    if not skip_documents(sit):
        return ""
    # Erst nach nachweislich erzeugtem Link UND erfolgreicher Bindung an den
    # gebuchten Termin darf Bianca SMS/Reservierung als erledigt ansagen.
    if not _scope_passt(sit) or not _stand(sit).get("bound"):
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
    _beobachten(sit, "done", outcome="done")
    _terminal_bereinigen(sit, "done")


def _create_nachpruefen(sit: dict, token: str, appointment_id: str) -> dict | None:
    """W-NAMENSLINK-NACHPRUEFEN (07.10.2026, Anruf dad02eaf): ``create`` lief in
    den Client-Timeout (httpStatus 0), die Cloud Function hatte die SMS aber
    gesendet. ``open`` setzt sie erst nach dem Versand, ``done`` nach der
    Bestätigung — nur dann gilt der Link als erzeugt. Alles andere bleibt
    fail-closed."""
    if os.getenv("NAMENSLINK_NACHPRUEFEN", "1").strip() == "0":
        return None
    token = _s(token).lower()
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        return None
    status, data, dispatch = _cf_call(
        "agentNameConfirm", {"action": "status", "token": token}, timeout=3.0)
    remote = _s(data.get("status")) if isinstance(data, dict) else ""
    ok = status == 200 and remote in {"open", "done"}
    _beobachten(
        sit,
        "status",
        status=status,
        dispatch=dispatch,
        outcome=remote if ok else "error",
    )
    if not ok:
        return None
    return {"status": "ok", "token": token, "url": "", "sent": True,
            "dryRun": False, "bound": bool(_s(appointment_id)), "nachgeprueft": True}


def starten(
    sit: dict,
    *,
    dry_run: bool = False,
    parallel: bool = False,
    appointment_id: str = "",
    patient_id: str = "",
    created_patient: bool = False,
) -> dict | None:
    if not erlaubt(sit):
        return None
    if verifiziert(sit):
        return None
    # Stufe 1c: ohne Reservierung (nur Name) und mit Notaus NAMENS_SMS_VERWALTUNG=0
    # darf in Absage/Verschieben/Auskunft kein Reservierungs-Create ohne Slot
    # entstehen — genau der Weg zu den Platzhalter-Geisterterminen.
    _mod = _s((sit.get("sammler") or {}).get("modus"))
    if _mod in _VERWALTUNG_MODI and not sms_verwaltung_aktiv():
        return None
    if _scope_passt(sit):
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
    reservation_token = reservierungs_token(sit)
    appointment_id = _s(
        appointment_id or s.get("appointmentId") or sit.get("lastBookId")
    )
    nur = _nur_name_fuer(sit)
    if nur:
        # Reine Namensabfrage: nie einen Termin oder eine Akte an den Link
        # binden — das war der Weg zu den Platzhalter-Geisterterminen.
        appointment_id = ""
        patient_id = ""
        created_patient = False
        parallel = False
    status, data, dispatch = _cf_call("agentNameConfirm", {
        "action": "create",
        "token": reservation_token,
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "sessionId": _s(sit.get("id") or sit.get("sessionId")),
        "phone": phone,
        "firstName": first,
        "lastName": last,
        "appointmentId": appointment_id,
        "patientId": "" if nur else _s(patient_id or s.get("patientId")),
        "createdPatient": bool(created_patient),
        "start": "" if nur else _s(s.get("slotIso") or sit.get("lastBookIso")),
        "dryRun": bool(dry_run or tenant.get("_testNoWrite")),
    })
    if status == 0 and not (dry_run or tenant.get("_testNoWrite")):
        nach = _create_nachpruefen(sit, reservation_token, appointment_id)
        if nach is not None:
            status, data = 200, nach
    _beobachten(
        sit,
        "create",
        status=status,
        dispatch=dispatch,
        outcome="ok" if (
            status == 200
            and isinstance(data, dict)
            and data.get("token")
            and (data.get("sent") or data.get("dryRun"))
        ) else "error",
    )
    if (
        status != 200
        or not isinstance(data, dict)
        or not data.get("token")
        or not (data.get("sent") or data.get("dryRun"))
    ):
        # Teilantworten (insbesondere ``sent:false``) duerfen weder einen
        # offenen Link markieren noch spaeter eine Erfolgsansage ausloesen.
        sit["namenslink"] = {
            "createFailed": True,
            "sent": bool(data.get("sent")) if isinstance(data, dict) else False,
            "dryRun": bool(data.get("dryRun")) if isinstance(data, dict) else False,
            "httpStatus": status,
            "abort": abbrechen(
                sit,
                appointment_id=appointment_id,
                patient_id=_s(patient_id or s.get("patientId")),
                token=reservation_token,
                reason="create_failed",
                created_patient=created_patient,
            ) if appointment_id and not (dry_run or tenant.get("_testNoWrite")) else None,
        }
        return None
    sit["namenslink"] = {
        "token": _s(data.get("token")),
        "reservationToken": _s(data.get("token")),
        "reservationScope": reservierungs_scope(sit),
        "url": _s(data.get("url")),
        "sent": bool(data.get("sent") or data.get("dryRun")),
        "dryRun": bool(data.get("dryRun")),
        "bound": bool(data.get("bound")),
        "parallel": bool(parallel),
        "firstNameHint": first,
        "lastNameHint": last,
        "nurName": nur,
    }
    if nur:
        s = sit.setdefault("sammler", {})
        s["frage"] = "namenslink"
        return {"text": _ANKUENDIGUNG_RETTUNG}
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


def abbrechen(
    sit: dict,
    *,
    appointment_id: str,
    patient_id: str,
    token: str,
    reason: str,
    created_patient: bool = False,
) -> bool:
    """Fail-closed: unklare Reservierung samt Link serverseitig verwerfen."""
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    token = _s(token).lower()
    appointment_id = _s(appointment_id)
    if not appointment_id or not re.fullmatch(r"[a-f0-9]{32}", token):
        return False
    status, data, dispatch = _cf_call("agentNameConfirm", {
        "action": "abort",
        "token": token,
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "sessionId": _s(sit.get("id") or sit.get("sessionId")),
        "appointmentId": appointment_id,
        "patientId": _s(patient_id),
        "createdPatient": bool(created_patient),
        "reason": _s(reason) or "aborted",
    })
    ok = (
        status == 200
        and isinstance(data, dict)
        and _s(data.get("status")).lower() in {"ok", "success", "cancelled"}
    )
    _beobachten(
        sit,
        "abort",
        status=status,
        dispatch=dispatch,
        outcome="ok" if ok else "error",
    )
    return ok


def termin_binden(
    sit: dict,
    appointment_id: str,
    patient_id: str = "",
    *,
    created_patient: bool = False,
) -> bool:
    """Nach der Platzhalter-Buchung Termin und Link zusammenhängen."""
    if not aktiv() or not erlaubt(sit) or not _scope_passt(sit):
        return False
    token = _s(
        _stand(sit).get("reservationToken") or _stand(sit).get("token")
    )
    aid = _s(appointment_id)
    if not token or not aid:
        return False
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    status, data, dispatch = _cf_call("agentNameConfirm", {
        "action": "bind",
        "token": token,
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "sessionId": _s(sit.get("id") or sit.get("sessionId")),
        "appointmentId": aid,
        "patientId": _s(patient_id),
        "createdPatient": bool(created_patient),
        "start": _s(s.get("slotIso") or sit.get("lastBookIso")),
    })
    data = data if isinstance(data, dict) else {}
    ok = status == 200 and _s(data.get("status")).lower() in {"ok", "success"}
    _beobachten(
        sit,
        "bind",
        status=status,
        dispatch=dispatch,
        outcome="ok" if ok else "error",
    )
    neu = {**_stand(sit), "bound": ok, "bindFailed": not ok}
    if ok:
        neu["appointmentId"] = aid
        if patient_id:
            neu["patientId"] = _s(patient_id)
    sit["namenslink"] = neu
    return ok


def status_holen(sit: dict) -> dict:
    stand = _stand(sit)
    token = _s(stand.get("reservationToken") or stand.get("token"))
    if not token or not _scope_passt(sit, stand):
        return {}
    status, data, dispatch = _cf_call("agentNameConfirm", {
        "action": "status",
        "token": token,
    })
    remote = _s(data.get("status")) if isinstance(data, dict) else ""
    outcome = remote if remote in {"open", "done", "expired"} else (
        "error" if status != 200 else "unknown"
    )
    _beobachten(
        sit,
        "status",
        status=status,
        dispatch=dispatch,
        outcome=outcome,
    )
    return data if status == 200 and isinstance(data, dict) else {}


def einziehen(sit: dict) -> dict:
    nummer_parken(sit)
    if ohne_stammdaten(sit):
        stammdaten_parken(sit)
    if (
        not erlaubt(sit)
        or verifiziert(sit)
        or not _scope_passt(sit)
    ):
        return {}
    data = status_holen(sit)
    if data.get("status") == "done" and _s(data.get("lastName")):
        _anwenden(sit, _s(data.get("firstName")), _s(data.get("lastName")))
        return data
    if data.get("status") == "expired":
        _beobachten(sit, "expired", outcome="expired")
        _terminal_bereinigen(sit, "expired")
    return data


def warten(sit: dict) -> dict:
    s = sit.setdefault("sammler", {})
    s["frage"] = "namenslink"
    if _stand(sit).get("nurName"):
        return {"text": "Die SMS ist unterwegs — öffnen Sie bitte den Link und "
                        "tragen Sie dort Ihren Vor- und Nachnamen ein."}
    return {"text": _ANKUENDIGUNG}


_SMS_GEHT_NICHT_RE = re.compile(
    r"\b(?:geht\s+nicht|klappt\s+nicht|funktioniert\s+nicht"
    r"|(?:keine|nicht\s+die)\s+sms"
    r"|(?:ist\s+)?nicht\s+angekommen|nichts\s+(?:bekommen|angekommen)"
    r"|kein\s+handy|kann\s+ich\s+nicht|will\s+ich\s+nicht)\b",
    re.I,
)


def _weiter(sit: dict, melde: Melde = None) -> dict | None:
    """Name ist da: Buchung läuft weiter, Verwaltung sucht den Termin."""
    s = sit.setdefault("sammler", {})
    if _s(s.get("modus")) == "buchen":
        from bianca import flow
        return flow.weiter_nach_namenslink(sit, melde)
    from bianca import verwalten
    return verwalten._dispatch(sit, melde)


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
    if blocking and verifiziert(sit):
        # ``flow.zug`` hat den getippten Namen am Zuganfang schon über
        # ``einziehen`` übernommen; der Status ist danach bereinigt.
        s["frage"] = ""
        neu.update({"name", "vorname", "nachname"})
        return _weiter(sit, melde)
    t = _s(gesagt)
    if blocking and t and _stand(sit).get("nurName") and _SMS_GEHT_NICHT_RE.search(t):
        sit["namenslink"] = {"abgebrochen": True}
        s["frage"] = "buchstabieren"
        s["buchstabenTeil"] = ""
        _beobachten(sit, "abort", outcome="caller_declined")
        return {"text": (
            "Kein Problem. Dann buchstabieren Sie mir den Nachnamen bitte "
            "ganz langsam, Buchstabe für Buchstabe; am Ende sagen Sie fertig."
        )}
    data = einziehen(sit) if stille else status_holen(sit)
    if data.get("status") == "done" and _s(data.get("lastName")):
        if not verifiziert(sit):
            _anwenden(sit, _s(data.get("firstName")), _s(data.get("lastName")))
        s["frage"] = ""
        neu.update({"name", "vorname", "nachname"})
        return _weiter(sit, melde)
    if data.get("status") == "expired":
        if not _stand(sit).get("expired"):
            _beobachten(sit, "expired", outcome="expired")
            _terminal_bereinigen(sit, "expired")
        s["frage"] = "nachname"
        return {"text": (
            "Der Link ist abgelaufen. Sagen Sie den Nachnamen bitte noch einmal."
        )}
    if stille:
        return {"text": ""}
    if _stand(sit).get("nurName"):
        # Der gesprochene Name ist genau das, was zweimal scheiterte — nicht
        # wieder ungeprüft übernehmen. Warten oder „geht nicht“ (oben).
        return {"text": (
            "Ich warte noch auf Ihren Namen aus der SMS. Falls die SMS nicht "
            "ankommt, sagen Sie einfach: geht nicht."
        )}
    if t and t.casefold() not in {"ja", "ok", "okay", "gut", "mhm", "hm"} and s.get("nachname"):
        s["frage"] = ""
        sit["namenslink"] = {**_stand(sit), "spoken": True}
        return _weiter(sit, melde)
    return {"text": (
        "Ich warte noch auf die Angabe in der SMS. "
        "Sie können den Namen auch einfach sagen."
    )}
