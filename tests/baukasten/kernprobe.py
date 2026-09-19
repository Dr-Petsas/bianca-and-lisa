"""Dialogkern-Probe fuers Studio — mandantenscharf, isoliert, ohne Telefon.

Ersetzt das fruehere Einzel-Dock (``bianca.controller.dock``, Port 8199). Die
spielbare Kern-Strecke ist dieselbe, der entscheidende Unterschied ist die
Politik: sie kommt aus dem ECHTEN Mandanten (``policy.aus_tenant``) statt aus
einem neutralen Default. Dazu eine Superuser-Maske, die

  * die WIRKSAME ``DialogPolicyV1`` je Praxis zeigt (inklusive der noch aus
    Legacy-Mandantenflags abgeleiteten Werte),
  * sie fuer den Testlauf uebersteuern laesst, ohne irgendwo zu schreiben,
  * die Validierung sichtbar macht (Warnungen, geklemmte Zahlen, verworfene
    Felder) und daneben die UNVERAENDERLICHEN Grenzen auflistet.

Damit wird die Praxis-Einstellungsmaske erst hier im Studio erprobt, bevor eine
Kunden-Oberflaeche ins Pickadoc-Portal geht.

Werkzeuge bleiben simuliert (``gateway_sim``): kein MAS, keine Cloud Function,
kein Firestore, kein Kalender-Schreiben. Live-Bianca (8096) und Lisa (8095)
werden nicht beruehrt.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from bianca.controller import dialog_policy as _dp
from bianca.controller import policy as _pol
from bianca.controller.gateway_sim import Szenario
from bianca.controller.orchestrator import TestGespraech
from bianca.controller.typen import Policy
from kern import tenants

# --------------------------------------------------------------------------- #
# Szenarien: steuern NUR den Werkzeug-Simulator (Retry-, Ruecklese- und
# Ehrlich-nein-Pfade ohne echte Systeme).
# --------------------------------------------------------------------------- #
SZENARIEN: tuple[tuple[str, str, Szenario], ...] = (
    (
        "glueck",
        "Erkannte Anruferin mit Vorbesuch",
        Szenario(
            anrufer_anrede="Frau",
            anrufer_nachname="Meier",
            anrufer_telefon="01701234567",
            anrufer_versicherung="gesetzlich",
            letzter_arzt="Doktor Blessing",
            letzter_grund="Hautscreening",
            letzter_wann="4 Monaten",
            termine=3,
        ),
    ),
    ("unbekannt", "Unbekannter Anrufer (Nummer unterdrueckt)", Szenario()),
    ("keine_slots", "Keine freien Slots", Szenario(freie_slots=0)),
    ("nicht_buchbar", "Telefonisch nicht buchbar", Szenario(slots_denied=True)),
    ("needs_phone", "Buchung braucht Handynummer", Szenario(buchung="needs_phone")),
    ("slot_weg", "Buchung: Slot schon vergeben", Szenario(buchung="slot_taken")),
    ("kein_termin", "Verwaltung: kein Termin gefunden", Szenario(termine=0)),
    ("mehrere_termine", "Verwaltung: mehrere Termine", Szenario(termine=3)),
)
_SZ: dict[str, Szenario] = {sid: sz for sid, _t, sz in SZENARIEN}
STANDARD_SZENARIO = SZENARIEN[0][0]


# --------------------------------------------------------------------------- #
# Maske: EINE deklarative Beschreibung, die das Frontend generisch rendert.
# Jedes Feld traegt seinen Pfad im ``DialogPolicyV1``-JSON — damit ist der
# Rueckweg (Maske -> parse()) trivial und es gibt keine zweite Wahrheit.
# --------------------------------------------------------------------------- #
_ANLIEGEN_TEXT: dict[str, str] = {
    "buchen": "Termin buchen",
    "absagen": "Termin absagen",
    "verschieben": "Termin verschieben",
    "auskunft": "Termin-Auskunft geben",
    "verbinden": "Weiterleiten",
    "dokument": "Unterlagen / Rezept",
    "rueckruf": "Rueckruf notieren",
}


def _zahl(pfad: list[str], grenze: str, text: str, hinweis: str = "") -> dict[str, Any]:
    lo, hi = _dp.GRENZEN[grenze]
    return {
        "pfad": pfad,
        "typ": "zahl",
        "text": text,
        "hinweis": hinweis,
        "min": lo,
        "max": hi,
    }


MASKE: tuple[dict[str, Any], ...] = (
    {
        "id": "anliegen",
        "titel": "Gefuehrte Anliegen",
        "hinweis": (
            "Aus heisst nicht unbeantwortet: der Kern uebergibt das Anliegen an "
            "den bisherigen Pfad."
        ),
        "felder": tuple(
            {"pfad": ["anliegen", typ, "an"], "typ": "bool", "text": _ANLIEGEN_TEXT[typ]}
            for typ in _dp.ANLIEGEN
        ),
    },
    {
        "id": "reihenfolge",
        "titel": "Pflichtfelder und Identifikation",
        "hinweis": (
            "Nichts ausgewaehlt = Standardreihenfolge. Die Telefonnummer ist nie "
            "Pflichtfeld der Sammelphase — sie kommt zuletzt."
        ),
        "felder": (
            {
                "pfad": ["anliegen", "buchen", "pflicht"],
                "typ": "liste",
                "text": "Buchung: abzufragende Felder",
                "auswahl": list(_dp.BUCHEN_SLOTS),
            },
            {
                "pfad": ["anliegen", "absagen", "identify"],
                "typ": "liste",
                "text": "Absage: Identifikation",
                "auswahl": list(_dp.IDENTIFY_SLOTS),
            },
            {
                "pfad": ["anliegen", "verschieben", "identify"],
                "typ": "liste",
                "text": "Verschieben: Identifikation",
                "auswahl": list(_dp.IDENTIFY_SLOTS),
            },
            {
                "pfad": ["anliegen", "auskunft", "identify"],
                "typ": "liste",
                "text": "Auskunft: Identifikation",
                "auswahl": list(_dp.IDENTIFY_SLOTS),
            },
        ),
    },
    {
        "id": "rueckfrage",
        "titel": "Schleifen-Aufsicht",
        "hinweis": (
            "Kommt dieselbe inhaltliche Frage oefter als erlaubt, fasst Bianca "
            "zusammen und knuepft neu an; hilft das nicht, uebergibt sie ehrlich "
            "mit Notiz. Ohne Zusammenfassung geht sie direkt in die Uebergabe."
        ),
        "felder": (
            _zahl(
                ["rueckfrage", "max_rueckfragen"],
                "max_rueckfragen",
                "Dieselbe Frage hoechstens",
                "danach Rueckblick statt Wiederholung",
            ),
            {
                "pfad": ["rueckfrage", "zusammenfassung_bei_stocken"],
                "typ": "bool",
                "text": "Rueckblick auf das Gespraech, wenn es stockt",
            },
        ),
    },
    {
        "id": "gespraech",
        "titel": "Gespraechsfuehrung",
        "felder": (
            {"pfad": ["gespraech", "knapp"], "typ": "bool", "text": "Knapp fuehren"},
            {
                "pfad": ["gespraech", "ein_thema"],
                "typ": "bool",
                "text": "Ein Thema pro Zug",
            },
            {
                "pfad": ["gespraech", "presence_einmal"],
                "typ": "bool",
                "text": "Nur einmal nachfassen, ob jemand dran ist",
            },
            {
                "pfad": ["gespraech", "eingehen"],
                "typ": "bool",
                "text": "Kurzer Bezug vor einer reinen Frage",
            },
            _zahl(["gespraech", "max_stupse"], "max_stupse", "Stupse bei Stille"),
        ),
    },
    {
        "id": "identitaet",
        "titel": "Identitaet",
        "hinweis": (
            "Direkt buchstabieren zieht die Rueckbestaetigung mit — der Kern "
            "behandelt beides als eine gesicherte Schreibweise. Einen erkannten "
            "Anrufer bestaetigt er immer."
        ),
        "felder": (
            {
                "pfad": ["identitaet", "anrufer_check"],
                "typ": "bool",
                "text": "Erkannten Anrufer bestaetigen statt neu erfragen",
            },
            {
                "pfad": ["identitaet", "nachname_ruecklese"],
                "typ": "bool",
                "text": "Nachname rueckbestaetigen",
            },
            {
                "pfad": ["identitaet", "nachname_direkt_buchstabieren"],
                "typ": "bool",
                "text": "Nachname direkt buchstabieren lassen",
            },
        ),
    },
    {
        "id": "verwaltung",
        "titel": "Verwaltung",
        "felder": (
            {
                "pfad": ["verwaltung", "termin_zuerst"],
                "typ": "bool",
                "text": "Termin ueber Datum und Uhrzeit suchen, nicht nur ueber den Namen",
            },
            {
                "pfad": ["verwaltung", "mehrfach_absage"],
                "typ": "bool",
                "text": "„beide/alle absagen“ zulassen",
            },
        ),
    },
    {
        "id": "mund",
        "titel": "Antwortverhalten",
        "felder": (
            {"pfad": ["mund", "antwort_knapp"], "typ": "bool", "text": "Kurze Antworten"},
            {
                "pfad": ["mund", "sonst_noch_nur_nach_erfolg"],
                "typ": "bool",
                "text": "„Sonst noch etwas?“ nur nach einem Erfolg",
            },
        ),
    },
    {
        "id": "transfer",
        "titel": "Weiterleitung",
        "hinweis": "Leer = telefonisch wird nie durchgestellt.",
        "felder": (
            {
                "pfad": ["transfer", "erlaubt"],
                "typ": "text",
                "text": "Erlaubte Ziele (mit Komma trennen)",
            },
        ),
    },
    {
        "id": "fach",
        "titel": "Fach und Notfall",
        "felder": (
            {
                "pfad": ["fach", "notfall_sofort"],
                "typ": "bool",
                "text": "Notfall sofort (fester Sofortweg statt Termin)",
            },
        ),
    },
)


def maske() -> dict[str, Any]:
    """Maskenschema plus die Grenzen, die keine Praxis aufweichen kann."""
    return {
        "schemaVersion": _dp.SCHEMA_VERSION,
        "gruppen": [
            {
                "id": g["id"],
                "titel": g["titel"],
                "hinweis": g.get("hinweis", ""),
                "felder": [dict(f) for f in g["felder"]],
            }
            for g in MASKE
        ],
        "invarianten": [
            {"id": k, "text": v} for k, v in _dp.INVARIANTEN.items()
        ],
        "szenarien": [{"id": sid, "text": text} for sid, text, _sz in SZENARIEN],
    }


# --------------------------------------------------------------------------- #
# Policy: veroeffentlichter Vertrag + tatsaechliche Wirkung.
# --------------------------------------------------------------------------- #
def _wirkung_ueberlagern(basis: dict[str, Any], p: Policy, tenant: dict) -> dict[str, Any]:
    """Den gebauten Reducer-``Policy``-Stand ueber den Vertrag legen.

    Der Vertrag sagt, was KONFIGURIERT ist; die gebaute Policy sagt, was WIRKT
    (bei Praxen ohne veroeffentlichten Vertrag stammt das aus Legacy-Flags und
    aus Daten, etwa „nur ein Behandler -> keine Behandlerfrage“). Gezeigt wird
    die Wirkung — sonst behauptet die Maske etwas, das der Kern nicht tut.
    """
    d = {k: (dict(v) if isinstance(v, dict) else v) for k, v in basis.items()}
    d["revision"] = p.policy_revision
    d["gespraech"] = dict(
        d.get("gespraech", {}),
        knapp=p.knapp,
        ein_thema=p.ein_thema,
        presence_einmal=p.presence_einmal,
        eingehen=p.eingehen,
        max_stupse=p.max_stupse,
    )
    d["verwaltung"] = dict(
        d.get("verwaltung", {}),
        mehrfach_absage=p.mehrfach_absage,
        termin_zuerst=p.termin_zuerst,
    )
    d["mund"] = dict(
        d.get("mund", {}),
        antwort_knapp=p.antwort_knapp,
        sonst_noch_nur_nach_erfolg=p.sonst_noch_nur_nach_erfolg,
    )
    d["rueckfrage"] = dict(
        d.get("rueckfrage", {}),
        max_rueckfragen=p.max_rueckfragen,
        zusammenfassung_bei_stocken=p.zusammenfassung_bei_stocken,
    )
    d["transfer"] = {"erlaubt": list(p.transfer_erlaubt)}
    d["fach"] = dict(d.get("fach", {}), notfall_sofort=p.notfall_sofort)

    buchen = p.spec("buchen")
    ident = dict(d.get("identitaet", {}))
    if buchen is not None:
        # Ruecklese ist im Spec verankert (auch wenn sie aus einem Legacy-Flag kommt).
        ident["nachname_ruecklese"] = "nachname" in buchen.ruecklese_slots
    # Der Kern faltet „direkt buchstabieren" in die Ruecklese; die Absicht steht
    # nur in der Konfiguration — also von dort lesen statt falsch „aus" zeigen.
    if not isinstance(basis.get("identitaet"), dict) or "dialogPolicy" not in tenant:
        ident["nachname_direkt_buchstabieren"] = bool(
            tenant.get("nachnameDirektBuchstabieren")
        )
    d["identitaet"] = ident

    anl: dict[str, Any] = {}
    for typ in _dp.ANLIEGEN:
        spec = p.spec(typ)
        alt = d.get("anliegen", {}).get(typ) if isinstance(d.get("anliegen"), dict) else None
        vor = alt if isinstance(alt, dict) else {}
        anl[typ] = {
            "an": p.fuehrt(typ),
            "pflicht": list(spec.pflicht) if spec is not None else list(vor.get("pflicht") or []),
            "identify": (
                list(spec.identify) if spec is not None else list(vor.get("identify") or [])
            ),
        }
    # Nur dort Pflicht/Identify zeigen, wo die Familie sie wirklich fuehrt.
    for typ in ("verbinden", "dokument"):
        anl[typ] = {"an": anl[typ]["an"], "pflicht": [], "identify": []}
    for typ in ("absagen", "verschieben", "auskunft"):
        anl[typ]["pflicht"] = []
    anl["buchen"]["identify"] = []
    d["anliegen"] = anl
    return d


def policy_bauen(tenant_id: str, roh: Any = None) -> dict[str, Any]:
    """Mandanten-Policy bauen — optional mit uebersteuerter ``DialogPolicyV1``.

    Geht bewusst den PRODUKTIVEN Weg (``policy.aus_tenant`` liest
    ``tenant["dialogPolicy"]``), damit die Probe genau das prueft, was live
    gelten wuerde. Es wird nichts gespeichert; der Mandant wird nur als Kopie
    im Speicher angereichert.
    """
    t = dict(tenants.laden(tenant_id) or {})
    warn: list[str] = []
    veroeffentlicht = t.get("dialogPolicy")
    quelle = "vertrag" if isinstance(veroeffentlicht, dict) and veroeffentlicht else "legacy"

    if isinstance(roh, dict) and roh:
        erg = _dp.parse(roh)
        warn.extend(erg.warnungen)
        if erg.ok:
            t["dialogPolicy"] = erg.policy.as_dict()
            quelle = "uebersteuert"
    elif quelle == "vertrag":
        warn.extend(_dp.parse(veroeffentlicht).warnungen)

    p = _pol.aus_tenant(t)
    vertrag = _dp.parse(t.get("dialogPolicy"))
    basis = vertrag.policy.as_dict() if vertrag.ok else _dp.sicher_default().as_dict()
    return {
        "tenant": str(t.get("_id") or t.get("id") or tenant_id),
        "praxis": str(t.get("praxisName") or t.get("_id") or tenant_id),
        "fachId": p.fach_id,
        "quelle": quelle,
        "revision": p.policy_revision,
        "policy": _wirkung_ueberlagern(basis, p, t),
        "warnungen": warn,
        "_reducer": p,
    }


# --------------------------------------------------------------------------- #
# Hirn (vLLM) — lazy, damit der Studio-Start nie auf das Netz wartet.
# --------------------------------------------------------------------------- #
_hirn_geprueft = False
_hirn_fn: Any = None


def hirn() -> Any:
    """``hirn.deuten`` wenn das LLM erreichbar ist, sonst None (Probe bleibt tippbar)."""
    global _hirn_geprueft, _hirn_fn
    if _hirn_geprueft:
        return _hirn_fn
    _hirn_geprueft = True
    try:
        from kern import llm as _llm

        if _llm.health(timeout=2.0).get("ok"):
            from bianca.controller import hirn as _h

            _hirn_fn = _h.deuten
    except Exception:
        _hirn_fn = None
    return _hirn_fn


# --------------------------------------------------------------------------- #
# Eine Probe = ein spielbares Gespraech.
# --------------------------------------------------------------------------- #
class Probe:
    """Ein Kern-Gespraech mit fester Mandanten-Policy und festem Szenario."""

    def __init__(self, tenant_id: str, szenario: str = "", roh_policy: Any = None) -> None:
        self.sid = uuid.uuid4().hex[:12]
        self.szenario = szenario if szenario in _SZ else STANDARD_SZENARIO
        self.roh_policy = roh_policy if isinstance(roh_policy, dict) else None
        self.gebaut = policy_bauen(tenant_id, self.roh_policy)
        self.tenant_id = self.gebaut["tenant"]
        self.policy: Policy = self.gebaut.pop("_reducer")
        self.hirn_an = hirn() is not None
        self.gespraech = TestGespraech(self.policy, _SZ[self.szenario], llm=hirn())
        self.beruehrt = time.time()

    # ------------------------------------------------------------------ #
    def start(self) -> dict[str, Any]:
        satz = self.gespraech.start()
        return self._antwort({"antwort": satz, "llm": "— Begruessung, noch kein Zug —"})

    def zug(self, text: str) -> dict[str, Any]:
        self.beruehrt = time.time()
        return self._antwort(self.gespraech.eingabe(text).as_dict())

    # ------------------------------------------------------------------ #
    def _antwort(self, d: dict[str, Any]) -> dict[str, Any]:
        out = dict(d)
        out["sid"] = self.sid
        out["zustand"] = self.zustand()
        return out

    def zustand(self) -> dict[str, Any]:
        st = self.gespraech.state
        aktiv = st.aktiv()
        slots = {}
        if aktiv is not None:
            slots = {
                k: v.wert + (" ✓" if v.bestaetigt else "")
                for k, v in aktiv.slots.items()
                if v and v.wert
            }
        return {
            "zugNr": st.zug_nr,
            "terminal": st.terminal,
            "task": aktiv.typ if aktiv is not None else "",
            "phase": aktiv.phase.value if aktiv is not None else "",
            "slots": slots,
            "stockFrage": aktiv.stock_frage if aktiv is not None else "",
            "stockZahl": aktiv.stock_zahl if aktiv is not None else 0,
            "stockBudget": self.policy.max_rueckfragen,
            "geparkt": [t.typ for t in st.geparkt()],
            "bekannt": {k: v.wert for k, v in st.bekannt.items() if v and v.wert},
            "ledger": [
                {"name": o.name, "status": o.status.value, "committed": bool(o.committed)}
                for o in st.ledger
            ],
            "letzterWrite": st.letzter_write(),
        }

    def kopf(self) -> dict[str, Any]:
        """Alles, was der Browser ueber diese Probe wissen muss."""
        d = dict(self.gebaut)
        d.update(
            {
                "sid": self.sid,
                "szenario": self.szenario,
                "hirn": self.hirn_an,
                "uebersteuert": self.roh_policy is not None,
            }
        )
        return d


# --------------------------------------------------------------------------- #
# Registry (das Studio ist mehrbenutzerfaehig, aber klein).
# --------------------------------------------------------------------------- #
_MAX_PROBEN = 12
_TTL_S = 3 * 3600
_proben: dict[str, Probe] = {}
_sperre = threading.Lock()


def _aufraeumen() -> None:
    jetzt = time.time()
    alt = [sid for sid, p in _proben.items() if jetzt - p.beruehrt > _TTL_S]
    for sid in alt:
        _proben.pop(sid, None)
    while len(_proben) > _MAX_PROBEN:
        aeltester = min(_proben.items(), key=lambda kv: kv[1].beruehrt)[0]
        _proben.pop(aeltester, None)


def starten(tenant_id: str, szenario: str = "", roh_policy: Any = None) -> Probe:
    p = Probe(tenant_id, szenario, roh_policy)
    with _sperre:
        _proben[p.sid] = p
        _aufraeumen()
    return p


def hole(sid: str) -> Probe | None:
    with _sperre:
        return _proben.get(str(sid or ""))


__all__ = [
    "MASKE",
    "SZENARIEN",
    "STANDARD_SZENARIO",
    "Probe",
    "hirn",
    "hole",
    "maske",
    "policy_bauen",
    "starten",
]
