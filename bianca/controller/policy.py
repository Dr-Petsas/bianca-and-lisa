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
"""

from __future__ import annotations

from typing import Any

from bianca.controller.typen import Familie, Policy, TaskSpec

# Basis-Reihenfolge der Buchungs-Pflichtfelder. Telefon ist bewusst KEIN
# Pflicht-Slot der Sammelphase — es kommt zuletzt (W-TELEFON-ZULETZT) und wird
# vom Reducer in der Bestaetigungsphase gefuehrt.
_BUCHEN_PFLICHT = ("behandler", "besuchsgrund", "wunschzeit", "nachname", "versicherung")

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
    """Neutrale Standard-Politik (Buchung mit Behandlerfrage, kein Transfer)."""
    return Policy(
        mandant="",
        fach_id="allgemein",
        specs=_baue_specs(_BUCHEN_PFLICHT, nachname_ruecklese=False),
        eigene_tasks=_EIGENE,
        transfer_erlaubt=(),
        notfall_sofort=False,
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


def aus_tenant(tenant: dict[str, Any] | None) -> Policy:
    """Vollstaendige Policy aus einem Praxis-Datensatz ableiten."""
    t = tenant if isinstance(tenant, dict) else {}

    # Slot-Reihenfolge datengetrieben: nur EIN Behandler -> Frage entfaellt
    # (ersetzt das Flag ``einArztOhneBehandlerfrage``).
    pflicht = _BUCHEN_PFLICHT
    if _behandler_anzahl(t) == 1:
        pflicht = tuple(s for s in pflicht if s != "behandler")

    # Lazy: nur wenn ein echter Mandant vorliegt.
    fach = "allgemein"
    notfall = False
    try:  # pragma: no cover - reine Verdrahtung
        from kern import fachprofil, praxisregeln

        fach = fachprofil.fach_id(t) or "allgemein"
        notfall = bool(praxisregeln.notfall_sofort_aktiv(t))
    except Exception:
        pass

    return Policy(
        mandant=str(t.get("clientId") or t.get("id") or ""),
        fach_id=fach,
        specs=_baue_specs(pflicht, nachname_ruecklese=_readback_nachname(t)),
        eigene_tasks=_EIGENE,
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
