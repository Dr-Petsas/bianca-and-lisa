"""Mandanten-Politik bauen: Tenant/Context -> ``Policy`` (DATEN).

Hier — und NUR hier — wird aus einem Mandanten das Verhalten des Dialogkerns
abgeleitet. Der Reducer bleibt dadurch mandantenagnostisch und beweisbar; jeder
Praxis-Unterschied ist ein Wert in der ``Policy``, kein Code-Zweig.

Die heutigen verstreuten Mandanten-Booleans (``einArztOhneBehandlerfrage``,
``nachnameReadbackNachBuchstabieren``, ``nachnameDirektBuchstabieren``,
``verbindenErlaubt``, der DB-Notfall-Marker …) werden hier an EINER Stelle in
typisierte Policy-Felder uebersetzt. Kommt eine Praxis dazu, entsteht ihre
Politik aus ihren DATEN — kein geteilter Code wird angefasst.

Der Kern fuehrt dieselben Aufgaben-Familien fuer jeden Mandanten (buchen,
absagen, verschieben, auskunft, verbinden, dokument, rueckruf). Was sich je
Praxis unterscheidet, sind nur die DATEN: Slot-Reihenfolge, Ruecklese-Politik,
Transfer-Whitelist, Notfall-Marker.

``default()`` ist rein (stdlib) und dient den Property-Tests. ``aus_tenant()``
liest die echten Praxis-Felder; schwergewichtige Helfer (praxisregeln,
fachprofil) werden bewusst LAZY importiert, damit der Kern ohne sie testbar bleibt.

Schaerfung PRO MANDANT (spaeter Einstellungen-UI, heute Tenant-JSON)::

    "dialog": {
      "anliegen": {
        "buchen": {"pflicht": ["schonmal", "besuchsgrund", "wunschzeit", "nachname"]},
        "absagen": {"identify": ["nachname"]},
        "verbinden": {"an": false},
        "notfall": {"sofort": true}
      }
    }

Der Reducer bleibt derselbe. Nur diese Daten aendern Reihenfolge, Suche und
ob eine Aufgabe ueberhaupt gefuehrt wird.
"""

from __future__ import annotations

from dataclasses import replace as _replace
from typing import Any

from bianca.controller import dialog_policy as _dp
from bianca.controller.typen import Familie, Policy, TaskSpec

# Basis-Reihenfolge der Buchungs-Pflichtfelder. Telefon ist bewusst KEIN
# Pflicht-Slot der Sammelphase — es kommt zuletzt (W-TELEFON-ZULETZT) und wird
# vom Reducer in der Bestaetigungsphase gefuehrt.
_BUCHEN_PFLICHT = (
    "schonmal", "behandler", "besuchsgrund", "wunschzeit", "nachname", "versicherung",
)

# Aufgaben, die der Kern selbst fuehrt. Der Rest (praxisinfo, smalltalk …) bleibt
# beim Legacy-Pfad (UEBERGEBEN).
_EIGENE = frozenset(
    {"buchen", "absagen", "verschieben", "auskunft", "verbinden", "dokument", "rueckruf"}
)


def _baue_specs(
    buchen_pflicht: tuple[str, ...],
    nachname_ruecklese: bool,
) -> dict[str, TaskSpec]:
    """Die sieben Familien-Specs eines Mandanten aus seinen DATEN bauen."""
    nn_rl: tuple[str, ...] = ("nachname",) if nachname_ruecklese else ()
    return {
        "buchen": TaskSpec(
            typ="buchen",
            familie=Familie.BUCHEN,
            pflicht=buchen_pflicht,
            offer_tool="offer_slots",
            commit_tool="book_slot",
            telefon_slot="telefon",
            ruecklese_slots=nn_rl,
        ),
        "absagen": TaskSpec(
            typ="absagen",
            familie=Familie.VERWALTEN,
            identify=("nachname",),
            such_tool="list_appointments",
            commit_tool="cancel_appointment",
            destruktiv=True,
            ruecklese_slots=nn_rl,
        ),
        "verschieben": TaskSpec(
            typ="verschieben",
            familie=Familie.VERWALTEN,
            identify=("nachname",),
            such_tool="list_appointments",
            offer_tool="offer_slots",
            commit_tool="move_appointment",
            destruktiv=True,
            neue_zeit=True,
            ruecklese_slots=nn_rl,
        ),
        "auskunft": TaskSpec(
            typ="auskunft",
            familie=Familie.AUSKUNFT,
            identify=("nachname",),
            such_tool="list_appointments",
            ruecklese_slots=nn_rl,
        ),
        "verbinden": TaskSpec(typ="verbinden", familie=Familie.VERBINDEN),
        "dokument": TaskSpec(typ="dokument", familie=Familie.DOKUMENT),
        "rueckruf": TaskSpec(
            typ="rueckruf",
            familie=Familie.RUECKRUF,
            pflicht=("nachname", "telefon"),
            notiz_tool="praxis_notiz",
            ruecklese_slots=(("nachname", "telefon") if nachname_ruecklese else ("telefon",)),
        ),
    }


def default() -> Policy:
    """Standard-Politik des isolierten Test-Docks (kein Transfer, Notfall selbst)."""
    return Policy(
        mandant="",
        fach_id="allgemein",
        specs=_baue_specs(_BUCHEN_PFLICHT, nachname_ruecklese=False),
        eigene_tasks=_EIGENE,
        transfer_erlaubt=(),
        notfall_sofort=True,
    )


# --------------------------------------------------------------------------- #
# Aus dem echten Mandanten.
# --------------------------------------------------------------------------- #
def _behandler_anzahl(tenant: dict[str, Any]) -> int:
    for pfad in ("calendars", ("booking", "calendars")):
        node: Any = tenant
        if isinstance(pfad, tuple):
            for k in pfad:
                node = node.get(k, {}) if isinstance(node, dict) else {}
        else:
            node = tenant.get(pfad)
        if isinstance(node, (list, tuple)) and node:
            return len([c for c in node if c])
    return 0


def _readback_nachname(tenant: dict[str, Any]) -> bool:
    return bool(
        tenant.get("nachnameReadbackNachBuchstabieren")
        or tenant.get("nachnameDirektBuchstabieren")
    )


def _transfer_ziele(tenant: dict[str, Any]) -> tuple[str, ...]:
    roh = tenant.get("verbindenErlaubt")
    if isinstance(roh, (list, tuple)):
        return tuple(str(x).strip() for x in roh if str(x).strip())
    return ()


def _anliegen_block(tenant: dict[str, Any]) -> dict[str, Any]:
    d = tenant.get("dialog")
    if not isinstance(d, dict):
        return {}
    a = d.get("anliegen")
    return a if isinstance(a, dict) else {}


def _an_flag(cfg: Any, default: bool = True) -> bool:
    if not isinstance(cfg, dict):
        return default
    if "an" in cfg:
        return bool(cfg["an"])
    if "enabled" in cfg:
        return bool(cfg["enabled"])
    return default


def _tup(val: Any) -> tuple[str, ...] | None:
    if isinstance(val, (list, tuple)) and val:
        out = tuple(str(x).strip() for x in val if str(x).strip())
        return out or None
    return None


def _dialog_anwenden(
    tenant: dict[str, Any],
    specs: dict[str, TaskSpec],
    notfall: bool,
) -> tuple[dict[str, TaskSpec], frozenset[str], bool]:
    """Tenant-``dialog.anliegen`` ueberschreibt die Basis-Specs, nie den Reducer."""
    block = _anliegen_block(tenant)
    eigene = set(_EIGENE)
    neu = dict(specs)
    for typ, cfg in block.items():
        if not isinstance(cfg, dict):
            continue
        if typ == "notfall":
            if "sofort" in cfg:
                notfall = bool(cfg["sofort"])
            continue
        if not _an_flag(cfg, typ in eigene):
            eigene.discard(typ)
            continue
        eigene.add(typ)
        spec = neu.get(typ)
        if spec is None:
            continue
        pflicht = _tup(cfg.get("pflicht"))
        identify = _tup(cfg.get("identify"))
        if pflicht or identify:
            neu[typ] = TaskSpec(
                typ=spec.typ,
                familie=spec.familie,
                pflicht=pflicht or spec.pflicht,
                identify=identify or spec.identify,
                such_tool=spec.such_tool,
                offer_tool=spec.offer_tool,
                commit_tool=spec.commit_tool,
                notiz_tool=spec.notiz_tool,
                telefon_slot=spec.telefon_slot,
                ruecklese_slots=spec.ruecklese_slots,
                destruktiv=spec.destruktiv,
                neue_zeit=spec.neue_zeit,
                max_commit_retries=spec.max_commit_retries,
                max_phone_retries=spec.max_phone_retries,
                max_such_retries=spec.max_such_retries,
            )
    return neu, frozenset(eigene), notfall


def _pflicht_aus_dp(
    dp: _dp.DialogPolicyV1, typ: str, basis: tuple[str, ...], ein_behandler: bool
) -> tuple[str, ...]:
    """Explizite Policy-Reihenfolge gewinnt; sonst Basis + Ein-Behandler-Regel."""
    ap = dp.anliegen_pol(typ)
    if ap.pflicht:
        return ap.pflicht
    return tuple(s for s in basis if s != "behandler") if ein_behandler else basis


def _specs_aus_dp(dp: _dp.DialogPolicyV1, ein_behandler: bool) -> dict[str, TaskSpec]:
    """Die sieben Familien-Specs aus dem validierten Vertrag bauen."""
    rl = dp.identitaet.nachname_ruecklese or dp.identitaet.nachname_direkt_buchstabieren
    specs = _baue_specs(_pflicht_aus_dp(dp, "buchen", _BUCHEN_PFLICHT, ein_behandler), rl)
    # Explizite identify-Reihenfolge je Verwaltungs-/Auskunfts-Anliegen.
    for typ in ("absagen", "verschieben", "auskunft"):
        ap = dp.anliegen_pol(typ)
        spec = specs.get(typ)
        if spec is not None and ap.identify:
            specs[typ] = _replace(spec, identify=ap.identify)
    return specs


def aus_dialog_policy(
    tenant: dict[str, Any],
    dp: _dp.DialogPolicyV1,
    *,
    fach_id: str = "allgemein",
    notfall_basis: bool = False,
) -> Policy:
    """Validierten ``DialogPolicyV1``-Vertrag auf die Reducer-``Policy`` abbilden."""
    ein_behandler = _behandler_anzahl(tenant) == 1
    specs = _specs_aus_dp(dp, ein_behandler)
    eigene = frozenset(typ for typ in _EIGENE if dp.fuehrt(typ))
    # Transferziele: DB-Vertrag gewinnt; leerer Vertrag faellt auf verbindenErlaubt.
    ziele = dp.transfer.erlaubt or _transfer_ziele(tenant)
    notfall = notfall_basis or dp.fach.notfall_sofort
    return Policy(
        mandant=str(tenant.get("clientId") or tenant.get("id") or ""),
        fach_id=fach_id,
        specs=specs,
        eigene_tasks=eigene,
        transfer_erlaubt=ziele,
        notfall_sofort=notfall,
        knapp=dp.gespraech.knapp,
        ein_thema=dp.gespraech.ein_thema,
        presence_einmal=dp.gespraech.presence_einmal,
        eingehen=dp.gespraech.eingehen,
        max_stupse=dp.gespraech.max_stupse,
        mehrfach_absage=dp.verwaltung.mehrfach_absage,
        termin_zuerst=dp.verwaltung.termin_zuerst,
        antwort_knapp=dp.mund.antwort_knapp,
        sonst_noch_nur_nach_erfolg=dp.mund.sonst_noch_nur_nach_erfolg,
        max_rueckfragen=dp.rueckfrage.max_rueckfragen,
        zusammenfassung_bei_stocken=dp.rueckfrage.zusammenfassung_bei_stocken,
        policy_revision=dp.revision,
    )


def aus_tenant(tenant: dict[str, Any] | None) -> Policy:
    """Vollstaendige Policy aus einem Praxis-Datensatz ableiten.

    Vorrang (Chef 30.08.2026 — DB ist die Wahrheit): liegt ein veroeffentlichter,
    validierter ``dialogPolicy``-Vertrag am Tenant, wird ER abgebildet. Sonst gilt
    der bisherige Weg (Basis-Specs + optionaler ``dialog.anliegen``-Block).
    """
    t = tenant if isinstance(tenant, dict) else {}

    # Lazy: nur wenn ein echter Mandant vorliegt.
    fach = "allgemein"
    notfall = False
    try:  # pragma: no cover - reine Verdrahtung
        from kern import fachprofil, praxisregeln

        fach = fachprofil.fach_id(t) or "allgemein"
        notfall = bool(praxisregeln.notfall_sofort_aktiv(t))
    except Exception:
        pass

    # Veroeffentlichter Vertrag? -> ER gewinnt (mandantenscharf, versioniert).
    roh = t.get("dialogPolicy")
    if isinstance(roh, dict) and roh:
        erg = _dp.parse(roh)
        if erg.ok:
            return aus_dialog_policy(t, erg.policy, fach_id=fach, notfall_basis=notfall)

    # Slot-Reihenfolge datengetrieben: nur EIN Behandler -> Frage entfaellt
    # (ersetzt das Flag ``einArztOhneBehandlerfrage``).
    pflicht = _BUCHEN_PFLICHT
    if _behandler_anzahl(t) == 1:
        pflicht = tuple(s for s in pflicht if s != "behandler")

    specs, eigene, notfall = _dialog_anwenden(
        t, _baue_specs(pflicht, nachname_ruecklese=_readback_nachname(t)), notfall
    )
    return Policy(
        mandant=str(t.get("clientId") or t.get("id") or ""),
        fach_id=fach,
        specs=specs,
        eigene_tasks=eigene,
        transfer_erlaubt=_transfer_ziele(t),
        notfall_sofort=notfall,
    )


def aus_context(ctx: dict[str, Any] | None) -> Policy:
    """Policy aus einem ``TurnContextV1``-Snapshot ableiten (bevorzugt, herkunftsrein)."""
    c = ctx if isinstance(ctx, dict) else {}
    praxis = c.get("praxis") if isinstance(c.get("praxis"), dict) else {}
    fachtemplate = c.get("fachtemplate") if isinstance(c.get("fachtemplate"), dict) else {}

    anbieter = praxis.get("anbieter")
    behandler_n = len(anbieter) if isinstance(anbieter, (list, tuple)) else 0
    pflicht = _BUCHEN_PFLICHT
    if behandler_n == 1:
        pflicht = tuple(s for s in pflicht if s != "behandler")

    return Policy(
        mandant=str(praxis.get("clientId") or ""),
        fach_id=str(fachtemplate.get("id") or "allgemein"),
        specs=_baue_specs(pflicht, nachname_ruecklese=False),
        eigene_tasks=_EIGENE,
        transfer_erlaubt=(),
        notfall_sofort=False,
    )


__all__ = ["default", "aus_tenant", "aus_context"]
