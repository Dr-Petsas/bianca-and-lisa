"""Renderer des Dialogkerns: SpeakSpec -> deutscher Satz.

Eine Antwort hat immer dieselbe Form:

  Vorbezug aus belegten Fakten (nie der LLM-Metasatz)
  + deterministische Schublade

Das Modell schreibt keinen Satz. ``verstanden`` bleibt in der Dock-Zeile.

Bewusst abhaengigkeitsfrei (nur stdlib). Die Texte sind kurz und je Sprechakt
GENAU EINE Aussage bzw. EINE Frage (W-RUHE: ein Thema pro Zug). Wer die Woerter
einer Praxis anpassen will, aendert nur diese Tabelle — Reducer und Invarianten
bleiben unberuehrt.
"""

from __future__ import annotations

from typing import Mapping

from bianca.controller import fuer_wen as _fuer_wen
from bianca.controller import varianten as _var
from bianca.controller.typen import SpeakSpec, SprechAkt


# --------------------------------------------------------------------------- #
# Fragetexte je frage_id (Sammelphase, Ruecklese-Neuerfragung, Sonderfragen).
# --------------------------------------------------------------------------- #
_FRAGE: dict[str, str] = {
    "schonmal": "Waren Sie denn schon einmal bei uns in der Praxis?",
    "behandler": "Zu welchem Behandler möchten Sie denn?",
    "besuchsgrund": "Worum geht es bei dem Termin?",
    "wunschzeit": "Wann würde es Ihnen denn passen?",
    "nachname": "Wie ist Ihr Nachname?",
    "vorname": "Und wie ist Ihr Vorname?",
    "versicherung": "Sind Sie gesetzlich oder privat versichert?",
    "telefon": "Unter welcher Handynummer erreichen wir Sie?",
    "aenderung": "Was möchten Sie ändern?",
    "ziel": "Zu wem darf ich Sie verbinden?",
    "rueckruf_ja": "Rezepte und Überweisungen kann ich telefonisch leider nicht "
    "ausstellen — das geht nur persönlich in der Praxis. Soll ich Ihnen dafür "
    "einen Rückruf einrichten?",
    "anmeldung_rueckruf": (
        "Eine direkte Verbindung zur Anmeldung ist nicht eingerichtet. "
        "Ich kann einen Rückrufwunsch für das Praxisteam aufnehmen. Soll ich das tun?"
    ),
    "auswahl": "Ich habe mehrere Termine gefunden. Welchen meinen Sie?",
    "mehrfach_ok": "Soll ich wirklich alle Termine absagen?",
    "terminwahl": "Welchen der genannten Termine meinen Sie?",
    "termin_hinweis": "Welchen Tag oder welche Uhrzeit darf ich suchen?",
}

# Menschliche Etiketten fuer die Ruecklese von Fakten.
_LABEL: dict[str, str] = {
    "terminwahl": "Termin",
    "behandler": "Behandler",
    "besuchsgrund": "Grund",
    "telefon": "Nummer",
    "nachname": "Name",
    "vorname": "Vorname",
    "gefunden_iso": "Termin",
    "gefunden_arzt": "Behandler",
    "gefunden_grund": "Grund",
    "versicherung": "Versicherung",
}


def _fakt_map(spec: SpeakSpec) -> dict[str, str]:
    return {k: v for k, v in spec.fakten}


def _fakt_liste(spec: SpeakSpec, schluessel: str) -> list[str]:
    return [v for k, v in spec.fakten if k == schluessel]


def _lesbar(fakten: Mapping[str, str], *keys: str) -> str:
    teile = []
    for k in keys:
        v = fakten.get(k)
        if v and str(v).strip().lower() != "egal":
            teile.append(f"{_LABEL.get(k, k)}: {v}")
    return ", ".join(teile)


# --------------------------------------------------------------------------- #
# Einzelne Sprechakte.
# --------------------------------------------------------------------------- #
def _plan_vorsatz(spec: SpeakSpec) -> str:
    f = _fakt_map(spec)
    rolle = f.get("plan_rolle") or ""
    if not rolle:
        return ""
    erst = f.get("plan_erst") or ""
    zweit = f.get("plan_typ") or ""
    wem = _fuer_wen.phrase(rolle, fall="wem") or "der anderen Person"
    wen = _fuer_wen.phrase(rolle, fall="wen") or "die andere Person"
    if erst == "absagen" and zweit == "verschieben":
        return (
            f"Gut. Dann sage ich zuerst Ihren Termin ab und verschiebe danach "
            f"den von {wem}. "
        )
    if erst == "absagen":
        return (
            f"Gut. Dann sage ich zuerst Ihren Termin ab und kümmere mich danach "
            f"um den Termin für {wen}. "
        )
    if zweit == "absagen":
        return (
            f"Gut. Dann verschieben wir zuerst Ihren Termin und sagen danach "
            f"den von {wem} ab. "
        )
    return (
        f"Gut. Dann verschieben wir zuerst Ihren Termin und kümmern uns danach "
        f"um den Termin für {wen}. "
    )


_ZAHL_WORT = {"2": "zwei", "3": "drei", "4": "vier", "5": "fünf"}


def _vorbezug(spec: SpeakSpec) -> str:
    """Bezug aus belegten Fakten — nie der LLM-Metasatz."""
    f = _fakt_map(spec)
    if spec.detail in (
        "unklar", "anzahl", "anstand_selber", "anstand_schimpf",
        "hallo", "hilfe", "anmeldung",
    ):
        return ""
    tw = (f.get("gehoert_terminwahl") or "").lower()
    ag = (f.get("gehoert_absage_grund") or f.get("absage_grund") or "").lower()
    n = f.get("anzahl") or f.get("gehoert_anzahl") or ""
    wort = _ZAHL_WORT.get(str(n), n)
    alle = tw == "alle" or spec.frage_id == "mehrfach_ok"
    if alle and (wort or ag or tw == "alle"):
        if ag in ("umzug", "umgezogen"):
            if wort:
                return f"Sie möchten alle {wort} Termine absagen, weil Sie umgezogen sind. "
            return "Sie möchten alle Termine absagen, weil Sie umgezogen sind. "
        if wort:
            return f"Sie möchten alle {wort} Termine absagen. "
        return "Sie möchten alle Termine absagen. "
    if f.get("gehoert_intent") == "absagen" and spec.frage_id == "auswahl":
        return "Sie möchten absagen. "
    if f.get("gehoert_wunsch"):
        return f"{f['gehoert_wunsch']} — "
    if f.get("gehoert_grund"):
        return f"{f['gehoert_grund']} — "
    if f.get("gehoert_rolle"):
        wen = _fuer_wen.phrase(f["gehoert_rolle"], fall="wen") or f["gehoert_rolle"]
        return f"Für {wen}. "
    return ""


def _vorsatz(spec: SpeakSpec) -> str:
    f = _fakt_map(spec)
    arzt = f.get("letzter_arzt") or ""
    grund = f.get("letzter_grund") or ""
    wann = f.get("letzter_wann") or "einiger Zeit"
    if not (arzt or grund):
        return ""
    n = _var.zug_von(f)
    return _var.waehle("bezug", n, arzt=arzt, grund=grund, wann=wann)


def _frage(spec: SpeakSpec) -> str:
    """Frage rendern; bei Loop-Aufsicht-Rueckblick der Zusammenfassung voran."""
    kern = _frage_kern(spec)
    recap = _fakt_map(spec).get("rueckblick")
    if recap and spec.detail == "rueckblick":
        return f"Ich fasse kurz zusammen, damit wir zusammenfinden — {recap}. " + kern
    return kern


def _frage_kern(spec: SpeakSpec) -> str:
    fid = spec.frage_id or ""
    f = _fakt_map(spec)
    n = _var.zug_von(f)
    rolle = f.get("fuer_wen", "") or spec.detail
    wer = _fuer_wen.phrase(rolle)
    wem = _fuer_wen.phrase(rolle, fall="wem")
    if fid == "anrufer_check":
        if f.get("name"):
            return _var.waehle(
                "anrufer_check", n,
                anrede=f.get("anrede") or "",
                name=f.get("name") or "",
            )
        return _var.waehle("anrufer_check_kurz", n)
    if fid == "auskunft_klar":
        return _var.waehle("auskunft_klar", n)
    if fid == "fach_weiter":
        return _var.waehle("fachfrage", n, thema=f.get("thema") or "Ihre Frage")
    if wer and fid == "schonmal":
        return _vorsatz(spec) + f"War {wer} denn schon einmal bei uns in der Praxis?"
    if wer and fid == "behandler":
        return _vorsatz(spec) + f"Zu welchem Behandler soll {wer} denn?"
    if wem and fid == "besuchsgrund":
        return _vorsatz(spec) + f"Worum geht es bei {wem}?"
    if wer and fid == "nachname":
        return f"Wie heißt {wer} mit Nachnamen?"
    if wer and fid == "vorname":
        return f"Und wie heißt {wer} mit Vornamen?"
    if wer and fid == "versicherung":
        return f"Ist {wer} gesetzlich oder privat versichert?"
    if fid == "mehrfach_ok":
        return "Soll ich das wirklich tun?"
    if fid == "auswahl":
        optionen = _fakt_liste(spec, "option")
        if optionen:
            zeilen = "; ".join(f"{i + 1}. {o}" for i, o in enumerate(optionen))
            verfehlt = f.get("wunsch_verfehlt")
            vorsatz = (
                f"Zu {verfehlt} sehe ich keinen passenden Termin. "
                if verfehlt else ""
            )
            rolle = f.get("zuordnung_rolle") or ""
            if f.get("zuordnung") == "leer" and rolle:
                wem_z = _fuer_wen.phrase(rolle, fall="wem") or rolle
                return (
                    f"{vorsatz}Für {wem_z} sehe ich unter diesen Terminen keinen "
                    f"eigenen Eintrag. Alle stehen auf Ihre Akte: {zeilen}. "
                    "Welchen von Ihren meinen Sie?"
                )
            if f.get("zuordnung") == "treffer" and rolle:
                wer_z = _fuer_wen.phrase(rolle) or rolle
                return f"{vorsatz}Von {wer_z} sehe ich: {zeilen}. Ist das der?"
            return (
                f"{vorsatz}Ich habe mehrere Termine gefunden: {zeilen}. "
                "Welchen meinen Sie?"
            )
    if fid == "rueckruf_ja" and spec.detail == "unterlagen":
        return _var.waehle("unterlagen", n)
    if fid == "rueckruf_ja" and spec.detail == "dokument":
        return _var.waehle("rueckruf_ja", n)
    if fid == "anmeldung_rueckruf":
        return _FRAGE["anmeldung_rueckruf"]
    if fid == "arzt_notiz":
        return _var.waehle("arzt_notiz", n)
    if fid == "termin_hinweis":
        return _var.waehle("termin_hinweis", n)
    if fid == "wunschzeit" and f.get("wunsch_verfehlt"):
        return (
            f"{f['wunsch_verfehlt']} ist leider nichts frei. "
            "Wann sonst würde es Ihnen passen?"
        )
    kern = _var.waehle(fid, n) or _FRAGE.get(fid) or (
        "Können Sie mir das bitte genauer sagen?"
    )
    if fid in ("schonmal", "behandler", "besuchsgrund", "wunschzeit"):
        return _vorsatz(spec) + kern
    return kern


def _ruecklesen(spec: SpeakSpec) -> str:
    f = _fakt_map(spec)
    # Buchung: Termin + Behandler + Grund.
    if "terminwahl" in f:
        kern = _lesbar(f, "terminwahl", "behandler", "besuchsgrund")
        return f"Ich fasse zusammen — {kern}. Soll ich das so eintragen?"
    # Telefon-Ruecklese.
    if "telefon" in f:
        return f"Ich wiederhole die Nummer: {f['telefon']}. Stimmt das so?"
    # Bestandstermin (absagen/verschieben).
    if "gefunden_iso" in f or "gefunden_arzt" in f:
        kern = _lesbar(f, "gefunden_iso", "gefunden_arzt", "gefunden_grund")
        return f"Ich habe folgenden Termin gefunden — {kern}. Ist das der richtige?"
    # Nachname-Ruecklese (buchstabiert).
    if "nachname" in f:
        return f"Ich habe den Namen {f['nachname']} notiert. Ist das so richtig?"
    return "Habe ich das richtig verstanden?"


def _angebot(spec: SpeakSpec) -> str:
    slots = _fakt_liste(spec, "slot")
    f = _fakt_map(spec)
    vorsatz = _vorsatz(spec)
    if f.get("naechstbestes"):
        vorsatz = "Genau dann ist leider nichts frei. " + vorsatz
    if not slots:
        return vorsatz + "Ich schaue nach freien Terminen."
    anrede = " ".join(x for x in (f.get("anrede") or "", f.get("name") or "") if x).strip()
    n = _var.zug_von(f)
    if anrede and len(slots) == 1:
        satz = _var.waehle(
            "angebot_persoenlich", n,
            anrede=f.get("anrede") or "", name=f.get("name") or "", slot=slots[0],
        )
        if satz:
            return vorsatz + satz
        return vorsatz + f"Ich koennte Ihnen anbieten: {slots[0]}. Passt das?"
    aufzaehlung = "; ".join(f"{i + 1}. {s}" for i, s in enumerate(slots))
    if anrede:
        return vorsatz + f"{anrede}, ich habe {aufzaehlung}. Welcher passt Ihnen?"
    if len(slots) == 1:
        return vorsatz + f"Ich koennte Ihnen anbieten: {slots[0]}. Passt das?"
    return vorsatz + f"Ich kann Ihnen anbieten: {aufzaehlung}. Welcher passt Ihnen?"


def _erfolg(spec: SpeakSpec) -> str:
    f = _fakt_map(spec)
    weiter = f.get("weiter_rolle") or ""
    bruecke = ""
    if weiter:
        wen = _fuer_wen.phrase(weiter, fall="wen") or "die andere Person"
        if f.get("weiter_typ") == "absagen":
            bruecke = f" Als Nächstes sage ich den Termin für {wen} ab."
        else:
            bruecke = f" Als Nächstes der Termin für {wen}."
    if spec.detail == "uebertragen":
        kern = _lesbar(f, "gefunden_iso", "gefunden_arzt")
        rolle = _fuer_wen.phrase(f.get("fuer_wen") or "", fall="wen") or "die andere Person"
        vn = f.get("vorname") or ""
        ziel = f"{rolle} {vn}".strip()
        if kern:
            return f"Alles klar — {kern} übertrage ich auf {ziel}. Die Praxis trägt das um."
        return f"Alles klar — ich übertrage den Termin auf {ziel}. Die Praxis trägt das um."
    if spec.detail == "absagen":
        n = f.get("anzahl") or ""
        wort = _ZAHL_WORT.get(str(n), n)
        if wort:
            return f"Erledigt — alle {wort} Termine sind abgesagt.{bruecke}"
        kern = _lesbar(f, "gefunden_iso", "gefunden_arzt")
        if kern:
            return f"Erledigt — {kern} ist abgesagt.{bruecke}"
        return f"Erledigt — der Termin ist abgesagt.{bruecke}"
    if spec.detail == "verschieben":
        kern = _lesbar(f, "terminwahl")
        if kern:
            return f"Erledigt — {kern} ist verschoben. Sie bekommen eine Bestätigung per SMS.{bruecke}"
        return f"Erledigt — der Termin ist verschoben. Sie bekommen eine Bestätigung per SMS.{bruecke}"
    kern = _lesbar(f, "terminwahl", "behandler", "besuchsgrund")
    if "gefunden_iso" in f and not kern:
        kern = _lesbar(f, "gefunden_iso")
    notiz = f.get("notiz")
    extra = " Eine Notiz für die Ärztin habe ich hinterlegt." if notiz == "ja" else ""
    if kern:
        return f"Erledigt — {kern} ist eingetragen. Sie bekommen eine Bestätigung per SMS.{extra}"
    return f"Das habe ich für Sie eingetragen. Sie bekommen eine Bestätigung per SMS.{extra}"


def _ehrlich_kein(spec: SpeakSpec) -> str:
    d = spec.detail or ""
    if d == "kein_transfer":
        return ("Durchstellen kann ich in dieser Praxis leider nicht — aber ich "
                "kümmere mich direkt um Ihr Anliegen. Worum geht es?")
    if d == "kein_termin":
        return "Zu Ihrem Namen sehe ich aktuell keinen Termin bei uns."
    if d == "notiz_fehler":
        return ("Das hat technisch leider nicht geklappt. Bitte melden Sie sich "
                "direkt bei uns in der Praxis.")
    return ("Das kann ich telefonisch leider nicht anbieten. Gerne notiere ich "
            "Ihr Anliegen fuer die Praxis.")


def _rueckruf(spec: SpeakSpec) -> str:
    f = _fakt_map(spec)
    wer = f.get("nachname") or f.get("name") or ""
    zusatz = f" ({wer})" if wer else ""
    if spec.detail == "stocken":
        return ("Das bekommen wir hier am Telefon gerade nicht rund. Ich habe eine "
                f"Notiz fuer die Praxis gemacht{zusatz} — man meldet sich bei Ihnen "
                "zurueck.")
    return (f"Ich habe eine Notiz fuer die Praxis gemacht{zusatz} — "
            "man meldet sich bei Ihnen zurueck.")


def _uebergeben(spec: SpeakSpec) -> str:
    ziel = spec.detail or _fakt_map(spec).get("ziel") or "die Praxis"
    return f"Einen Moment, ich verbinde Sie mit {ziel}."


def _notfall(_spec: SpeakSpec) -> str:
    return ("Das klingt dringend. Bitte kommen Sie sofort in die Praxis — wir "
            "kuemmern uns schnellstmoeglich um Sie. Bei Lebensgefahr waehlen Sie 112.")


def _info(spec: SpeakSpec) -> str:
    n = _var.zug_von(_fakt_map(spec))
    if spec.detail == "anmeldung":
        return _var.waehle("anmeldung", n)
    if spec.detail == "anmeldung_besteht":
        return _FRAGE["anmeldung_rueckruf"]
    if spec.detail == "unklar":
        return _var.waehle("unklar", n)
    if spec.detail == "hilfe":
        return _var.waehle("hilfe", n)
    if spec.detail == "hallo":
        return _var.waehle("hallo", n)
    if spec.detail == "anstand_selber":
        return "Ähm — selber! Sonst noch was?"
    if spec.detail == "anstand_schimpf":
        return "Boah, das war nicht nett. Ich gebe mir echt Mühe. Worum geht es?"
    if spec.detail == "anmeldung_nein":
        return _var.waehle("unklar", n + 1)
    if spec.detail == "anzahl":
        f = _fakt_map(spec)
        z = f.get("anzahl") or f.get("gehoert_anzahl") or ""
        wort = _ZAHL_WORT.get(str(z), z)
        if wort:
            return f"Ja, {wort} Termine."
        return "Ja, mehrere Termine."
    if spec.detail == "sms":
        f = _fakt_map(spec)
        art = f.get("write_art") or ""
        tel = f.get("telefon") or ""
        ziel = f" an die {tel}" if tel else " an die hinterlegte Nummer"
        if art == "absagen":
            return f"Ja — die Absage-Bestätigung geht per SMS{ziel}."
        if art == "verschieben":
            return f"Ja — die Verschiebe-Bestätigung geht per SMS{ziel}."
        if art == "buchen":
            return f"Ja — die Terminbestätigung geht per SMS{ziel}."
        return f"Ja — eine Bestätigung geht per SMS{ziel}, sobald etwas feststeht."
    termine = _fakt_liste(spec, "termin")
    if termine:
        f = _fakt_map(spec)
        rolle = f.get("fuer_wen") or f.get("gehoert_rolle") or ""
        wer = _fuer_wen.phrase(rolle) if rolle else ""
        vorsatz = f"Für {wer}: " if wer else "Ihr nächster Termin: "
        return vorsatz + "; ".join(termine) + "."
    return "Ich habe Ihre Angaben geprüft."


def _abschied(spec: SpeakSpec) -> str:
    d = spec.detail or ""
    if d == "nichts_geaendert":
        return "In Ordnung, dann bleibt alles wie es ist. Auf Wiederhoeren!"
    if d == "dokument_persoenlich":
        return ("Alles klar, dann besprechen wir das persoenlich in der Praxis. "
                "Auf Wiederhoeren!")
    return "Gerne. Auf Wiederhoeren!"


# --------------------------------------------------------------------------- #
# Dispatch.
# --------------------------------------------------------------------------- #
_RENDER = {
    SprechAkt.FRAGE: _frage,
    SprechAkt.RUECKLESEN: _ruecklesen,
    SprechAkt.ANGEBOT: _angebot,
    SprechAkt.ERFOLG: _erfolg,
    SprechAkt.EHRLICH_KEIN: _ehrlich_kein,
    SprechAkt.RUECKRUF: _rueckruf,
    SprechAkt.UEBERGEBEN: _uebergeben,
    SprechAkt.NOTFALL: _notfall,
    SprechAkt.INFO: _info,
    SprechAkt.ABSCHIED: _abschied,
    SprechAkt.WARTEN: lambda _s: "",
}


def rendern(spec: SpeakSpec | None) -> str:
    """Vorbezug + belegte Fakten. ``None`` -> leer."""
    if spec is None:
        return ""
    fn = _RENDER.get(spec.akt)
    text = fn(spec) if fn else ""
    if spec.akt in (SprechAkt.FRAGE, SprechAkt.RUECKLESEN, SprechAkt.ANGEBOT):
        text = _plan_vorsatz(spec) + text
    vz = _vorbezug(spec)
    if vz and vz.strip() not in text:
        text = vz + text
    return text


__all__ = ["rendern"]
