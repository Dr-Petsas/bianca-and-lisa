"""DialogPolicyV1 — der EINE versionierte, streng validierte Praxis-Policy-Vertrag.

Dieses Modul ist ABSICHTLICH abhaengigkeitsfrei (nur stdlib), damit es sowohl im
Dialogkern (``bianca/controller``) als auch spaeter im Portal-Arbeitspaket als
kanonische Wahrheit dient. Es beschreibt GENAU die Praxisunterschiede, die eine
Praxis-Administration konfigurieren darf — nicht mehr.

Zwei streng getrennte Ebenen:

1. KONFIGURIERBAR (``DialogPolicyV1``): aktive Anliegen, Pflichtfeld-Reihenfolge,
   Behandlerwahl, Namens-Ruecklese, Transferziele, fachliche Regelpakete,
   Antwortknappheit sowie begrenzte Rueckfrage-/Zusammenfassungsstrategien.
2. UNVERAENDERLICH (``INVARIANTEN`` / ``GRENZEN``): hoechstens eine Frage pro
   Zug, keine Frage zu belegten Daten, Telefonnummer zuletzt, explizites Ja vor
   destruktiven Aktionen, Schreiberfolg nur nach Tool-Beleg, Datenschutz-/
   Notfallgrenzen und ein harter Schleifen-/Retry-Deckel. Diese Grenzen kann
   KEINE veroeffentlichte Policy aufweichen — die Zahlen werden beim Parsen hart
   in ihre Spanne geklemmt, alles Unbekannte verworfen.

``parse()`` ist der einzige Eingang: er nimmt beliebiges (auch feindliches oder
veraltetes) JSON entgegen und liefert IMMER eine gueltige, sichere
``DialogPolicyV1`` plus eine Liste menschenlesbarer Warnungen. Ungueltige Werte
fuehren nie zu einem Fehler, sondern zum sicheren Default fuer genau dieses Feld.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

# --------------------------------------------------------------------------- #
# Version + kanonisches Vokabular.
# --------------------------------------------------------------------------- #
SCHEMA_VERSION = 1

# Die vom Kern gefuehrten Anliegen. Nichts ausserhalb dieser Menge wird als
# Aufgabe akzeptiert (Rest -> Legacy-Uebergabe).
ANLIEGEN = (
    "buchen", "absagen", "verschieben", "auskunft", "verbinden", "dokument", "rueckruf",
)

# Erlaubte Sammel-/Pflicht-Slots je Familie. Unbekannte Slot-Namen einer
# veroeffentlichten Policy werden verworfen (nie an den Reducer weitergereicht).
_BUCHEN_SLOTS = frozenset(
    {"schonmal", "behandler", "besuchsgrund", "wunschzeit", "nachname", "versicherung"}
)
_IDENTIFY_SLOTS = frozenset({"nachname", "vorname"})

# Kanonische Basis-Reihenfolge der Buchungs-Pflichtfelder (Telefon NIE hier:
# es kommt zuletzt, W-TELEFON-ZULETZT ist unveraenderlich).
_BUCHEN_PFLICHT_STD = (
    "schonmal", "behandler", "besuchsgrund", "wunschzeit", "nachname", "versicherung",
)


# --------------------------------------------------------------------------- #
# Unveraenderliche Sicherheitsgrenzen — NIE konfigurierbar.
# --------------------------------------------------------------------------- #
# Diese Invarianten sind im Reducer strukturell erzwungen (I1..I6, W-*). Sie
# stehen hier NUR als lesbare, testbare Wahrheit, damit ein Portal/Reviewer
# sieht, was eine Policy NICHT verschieben darf.
INVARIANTEN: Mapping[str, str] = {
    "eine_frage_pro_zug": "Je Zug hoechstens eine offene Frage und hoechstens ein Werkzeug.",
    "keine_frage_zu_belegtem_feld": "Nie nach einem bereits belegten (ggf. rueckbestaetigten) Feld fragen.",
    "telefon_zuletzt": "Die Telefonnummer ist nie Sammel-Pflichtfeld; sie kommt zuletzt vor dem Schreiben.",
    "ja_vor_destruktiv": "Absage/Verschiebung/Buchung erst nach ausdruecklichem Ja.",
    "erfolg_nur_mit_beleg": "Erfolg wird nur nach einem committeten Werkzeug-Beleg gesprochen.",
    "datenschutz_notfall": "Datenschutz- und Notfallgrenzen bleiben im Kern; eine Policy lockert sie nie.",
    "harter_retry_deckel": "Jede Aufgabe wird in endlich vielen Zuegen terminal (Retry-Obergrenzen).",
}

# Harte Spannen fuer konfigurierbare Zahlen. Werte ausserhalb werden geklemmt.
GRENZEN: Mapping[str, tuple[int, int]] = {
    "max_commit_retries": (0, 2),
    "max_phone_retries": (0, 1),
    "max_such_retries": (0, 2),
    "max_stupse": (1, 3),
    "max_rueckfragen": (0, 3),
    "max_pflicht": (1, len(_BUCHEN_SLOTS)),
}


def _klemme(name: str, wert: Any, default: int) -> int:
    lo, hi = GRENZEN[name]
    try:
        i = int(wert)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, i))


# --------------------------------------------------------------------------- #
# Konfigurierbare Unterbloecke (Verhalten = DATEN).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GespraechPolicy:
    """Gespraechsfuehrung: Knappheit, Presence, Eingehen, Stups-Deckel."""

    knapp: bool = False
    ein_thema: bool = True             # eine Sache pro Zug (unveraenderlich empfohlen)
    presence_einmal: bool = True       # nur EIN Presence-Stups je Anruf
    eingehen: bool = True              # kurzer Bezug vor reiner Frage
    max_stupse: int = 2

    def as_dict(self) -> dict[str, Any]:
        return {
            "knapp": self.knapp,
            "ein_thema": self.ein_thema,
            "presence_einmal": self.presence_einmal,
            "eingehen": self.eingehen,
            "max_stupse": self.max_stupse,
        }


@dataclass(frozen=True)
class IdentitaetPolicy:
    """Identitaet/Rueckbestaetigung des Namens."""

    nachname_ruecklese: bool = False       # Nachname buchstabieren + rueckbestaetigen
    nachname_direkt_buchstabieren: bool = False
    anrufer_check: bool = True             # erkannten Anrufer bestaetigen statt neu fragen

    def as_dict(self) -> dict[str, Any]:
        return {
            "nachname_ruecklese": self.nachname_ruecklese,
            "nachname_direkt_buchstabieren": self.nachname_direkt_buchstabieren,
            "anrufer_check": self.anrufer_check,
        }


@dataclass(frozen=True)
class AnliegenPolicy:
    """Ein Anliegen: gefuehrt? + optionale Feld-Reihenfolge."""

    an: bool = True
    pflicht: tuple[str, ...] = ()      # nur BUCHEN/RUECKRUF; () = Standard
    identify: tuple[str, ...] = ()     # nur VERWALTEN/AUSKUNFT; () = Standard

    def as_dict(self) -> dict[str, Any]:
        return {"an": self.an, "pflicht": list(self.pflicht), "identify": list(self.identify)}


@dataclass(frozen=True)
class VerwaltungPolicy:
    """Verwaltung (Absage/Verschieben/Auskunft)."""

    mehrfach_absage: bool = True       # 'beide/alle absagen' zulassen
    termin_zuerst: bool = True         # Termin ueber Datum/Uhrzeit suchen, nicht nur Name

    def as_dict(self) -> dict[str, Any]:
        return {"mehrfach_absage": self.mehrfach_absage, "termin_zuerst": self.termin_zuerst}


@dataclass(frozen=True)
class MundPolicy:
    """Sprech-/Antwortverhalten."""

    antwort_knapp: bool = False        # kurze Antworten, kein Nachgeplauder
    sonst_noch_nur_nach_erfolg: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "antwort_knapp": self.antwort_knapp,
            "sonst_noch_nur_nach_erfolg": self.sonst_noch_nur_nach_erfolg,
        }


@dataclass(frozen=True)
class TransferPolicy:
    """Weiterleitung: erlaubte Ziele (leer = telefonisch nie durchstellen)."""

    erlaubt: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"erlaubt": list(self.erlaubt)}


@dataclass(frozen=True)
class FachPolicy:
    """Fach-/Notfallregeln (DB-Marker); fach_id kommt aus dem Fachprofil."""

    notfall_sofort: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"notfall_sofort": self.notfall_sofort}


@dataclass(frozen=True)
class RueckfragePolicy:
    """Begrenzte Rueckfrage-/Zusammenfassungsstrategie gegen Schleifen."""

    max_rueckfragen: int = 2
    zusammenfassung_bei_stocken: bool = True  # Rueckblick + erneute Analyse statt Schleife

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_rueckfragen": self.max_rueckfragen,
            "zusammenfassung_bei_stocken": self.zusammenfassung_bei_stocken,
        }


# --------------------------------------------------------------------------- #
# Der Vertrag.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DialogPolicyV1:
    """Die einzige konfigurierbare Ebene des Dialogkerns — versioniert und sicher."""

    schema_version: int = SCHEMA_VERSION
    revision: int = 0
    updated_at: str = ""
    updated_by: str = ""

    gespraech: GespraechPolicy = field(default_factory=GespraechPolicy)
    identitaet: IdentitaetPolicy = field(default_factory=IdentitaetPolicy)
    anliegen: Mapping[str, AnliegenPolicy] = field(default_factory=dict)
    verwaltung: VerwaltungPolicy = field(default_factory=VerwaltungPolicy)
    mund: MundPolicy = field(default_factory=MundPolicy)
    transfer: TransferPolicy = field(default_factory=TransferPolicy)
    fach: FachPolicy = field(default_factory=FachPolicy)
    rueckfrage: RueckfragePolicy = field(default_factory=RueckfragePolicy)

    def anliegen_pol(self, typ: str) -> AnliegenPolicy:
        got = self.anliegen.get(typ)
        return got if isinstance(got, AnliegenPolicy) else AnliegenPolicy()

    def fuehrt(self, typ: str) -> bool:
        return typ in ANLIEGEN and self.anliegen_pol(typ).an

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "revision": self.revision,
            "updatedAt": self.updated_at,
            "updatedBy": self.updated_by,
            "gespraech": self.gespraech.as_dict(),
            "identitaet": self.identitaet.as_dict(),
            "anliegen": {k: v.as_dict() for k, v in self.anliegen.items()},
            "verwaltung": self.verwaltung.as_dict(),
            "mund": self.mund.as_dict(),
            "transfer": self.transfer.as_dict(),
            "fach": self.fach.as_dict(),
            "rueckfrage": self.rueckfrage.as_dict(),
        }


def sicher_default() -> DialogPolicyV1:
    """Die immer gueltige Basis: alle Anliegen an, Standard-Reihenfolge, keine
    Ruecklese, kein Transfer, kein Notfall-Sonderweg."""
    return DialogPolicyV1(
        anliegen={typ: AnliegenPolicy(an=True) for typ in ANLIEGEN},
    )


# --------------------------------------------------------------------------- #
# Parser: beliebiges JSON -> gueltige, sichere DialogPolicyV1 + Warnungen.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ParseErgebnis:
    policy: DialogPolicyV1
    warnungen: tuple[str, ...] = ()
    ok: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"policy": self.policy.as_dict(), "warnungen": list(self.warnungen), "ok": self.ok}


def _bool(cfg: Mapping[str, Any], key: str, default: bool) -> bool:
    if not isinstance(cfg, Mapping) or key not in cfg:
        return default
    v = cfg[key]
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "on", "yes", "ja"}
    return default


def _an_flag(cfg: Any, default: bool = True) -> bool:
    if not isinstance(cfg, Mapping):
        return default
    for key in ("an", "enabled", "aktiv"):
        if key in cfg:
            return _bool(cfg, key, default)
    return default


def _slots(val: Any, erlaubt: frozenset[str], warn: list[str], wo: str) -> tuple[str, ...]:
    if not isinstance(val, (list, tuple)):
        return ()
    out: list[str] = []
    for x in val:
        s = str(x).strip()
        if not s:
            continue
        if s not in erlaubt:
            warn.append(f"{wo}: unbekannter Slot {s!r} verworfen")
            continue
        if s == "telefon":  # unveraenderlich: nie Sammel-Pflichtfeld
            warn.append(f"{wo}: 'telefon' ist nie Pflichtfeld (zuletzt) — verworfen")
            continue
        if s not in out:
            out.append(s)
    return tuple(out)


def _ziele(val: Any) -> tuple[str, ...]:
    if isinstance(val, (list, tuple)):
        return tuple(str(x).strip() for x in val if str(x).strip())
    return ()


def parse(raw: Any) -> ParseErgebnis:
    """Beliebiges JSON in eine gueltige, sichere ``DialogPolicyV1`` ueberfuehren.

    Nie werfend. Unbekannte/ungueltige Werte werden verworfen und der sichere
    Default fuer genau dieses Feld eingesetzt; jede solche Entscheidung steht in
    ``warnungen``. Fehlt die Eingabe ganz, kommt ``sicher_default()`` mit ok=False
    (Signal an den Aufrufer: nichts Konfiguriertes vorhanden)."""
    warn: list[str] = []
    if not isinstance(raw, Mapping):
        return ParseErgebnis(sicher_default(), (), ok=False)

    ver = raw.get("schemaVersion", raw.get("schema_version"))
    try:
        ver_i = int(ver)
    except (TypeError, ValueError):
        ver_i = SCHEMA_VERSION
        if ver is not None:
            warn.append("schemaVersion ungueltig -> als v1 gelesen")
    if ver_i > SCHEMA_VERSION:
        warn.append(f"schemaVersion {ver_i} > {SCHEMA_VERSION}: nur bekannte Felder gelesen")
    elif ver_i < SCHEMA_VERSION and ver is not None:
        warn.append(f"schemaVersion {ver_i} < {SCHEMA_VERSION}: sichere Defaults ergaenzt")

    g = raw.get("gespraech") if isinstance(raw.get("gespraech"), Mapping) else {}
    gespraech = GespraechPolicy(
        knapp=_bool(g, "knapp", False),
        ein_thema=_bool(g, "ein_thema", True),
        presence_einmal=_bool(g, "presence_einmal", True),
        eingehen=_bool(g, "eingehen", True),
        max_stupse=_klemme("max_stupse", g.get("max_stupse"), 2),
    )

    i = raw.get("identitaet") if isinstance(raw.get("identitaet"), Mapping) else {}
    identitaet = IdentitaetPolicy(
        nachname_ruecklese=_bool(i, "nachname_ruecklese", False),
        nachname_direkt_buchstabieren=_bool(i, "nachname_direkt_buchstabieren", False),
        anrufer_check=_bool(i, "anrufer_check", True),
    )

    anliegen: dict[str, AnliegenPolicy] = {}
    roh_anl = raw.get("anliegen") if isinstance(raw.get("anliegen"), Mapping) else {}
    for typ in ANLIEGEN:
        cfg = roh_anl.get(typ)
        an = _an_flag(cfg, True)
        pflicht: tuple[str, ...] = ()
        identify: tuple[str, ...] = ()
        if isinstance(cfg, Mapping):
            pflicht = _slots(cfg.get("pflicht"), _BUCHEN_SLOTS, warn, f"anliegen.{typ}.pflicht")
            identify = _slots(cfg.get("identify"), _IDENTIFY_SLOTS, warn, f"anliegen.{typ}.identify")
        anliegen[typ] = AnliegenPolicy(an=an, pflicht=pflicht, identify=identify)
    for schluessel in roh_anl:
        if schluessel not in ANLIEGEN:
            warn.append(f"anliegen: unbekanntes Anliegen {schluessel!r} verworfen")

    v = raw.get("verwaltung") if isinstance(raw.get("verwaltung"), Mapping) else {}
    verwaltung = VerwaltungPolicy(
        mehrfach_absage=_bool(v, "mehrfach_absage", True),
        termin_zuerst=_bool(v, "termin_zuerst", True),
    )

    m = raw.get("mund") if isinstance(raw.get("mund"), Mapping) else {}
    mund = MundPolicy(
        antwort_knapp=_bool(m, "antwort_knapp", False),
        sonst_noch_nur_nach_erfolg=_bool(m, "sonst_noch_nur_nach_erfolg", False),
    )

    t = raw.get("transfer") if isinstance(raw.get("transfer"), Mapping) else {}
    transfer = TransferPolicy(erlaubt=_ziele(t.get("erlaubt")))

    f = raw.get("fach") if isinstance(raw.get("fach"), Mapping) else {}
    fach = FachPolicy(notfall_sofort=_bool(f, "notfall_sofort", False))

    r = raw.get("rueckfrage") if isinstance(raw.get("rueckfrage"), Mapping) else {}
    rueckfrage = RueckfragePolicy(
        max_rueckfragen=_klemme("max_rueckfragen", r.get("max_rueckfragen"), 2),
        zusammenfassung_bei_stocken=_bool(r, "zusammenfassung_bei_stocken", True),
    )

    def _int(key: str, default: int) -> int:
        try:
            return int(raw.get(key, default))
        except (TypeError, ValueError):
            if raw.get(key) is not None:
                warn.append(f"{key} ungueltig -> {default}")
            return default

    pol = DialogPolicyV1(
        schema_version=SCHEMA_VERSION,
        revision=max(0, _int("revision", 0)),
        updated_at=str(raw.get("updatedAt") or raw.get("updated_at") or ""),
        updated_by=str(raw.get("updatedBy") or raw.get("updated_by") or ""),
        gespraech=gespraech,
        identitaet=identitaet,
        anliegen=anliegen,
        verwaltung=verwaltung,
        mund=mund,
        transfer=transfer,
        fach=fach,
        rueckfrage=rueckfrage,
    )
    return ParseErgebnis(pol, tuple(warn), ok=True)


__all__ = [
    "SCHEMA_VERSION", "ANLIEGEN", "INVARIANTEN", "GRENZEN",
    "GespraechPolicy", "IdentitaetPolicy", "AnliegenPolicy", "VerwaltungPolicy",
    "MundPolicy", "TransferPolicy", "FachPolicy", "RueckfragePolicy",
    "DialogPolicyV1", "ParseErgebnis", "parse", "sicher_default", "replace",
]
