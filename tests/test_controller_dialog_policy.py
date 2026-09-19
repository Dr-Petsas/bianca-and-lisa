"""DialogPolicyV1: versionierter Vertrag + unveraenderliche Sicherheitsgrenzen.

Diese Tests nageln die EINE konfigurierbare Ebene des Dialogkerns fest:

  * ``parse()`` ist nie werfend und liefert IMMER eine gueltige Policy.
  * Unbekannte/feindliche/veraltete Eingaben landen im sicheren Default.
  * Die harten Zahlen werden in ihre Spanne geklemmt (nie ausserhalb GRENZEN).
  * ``telefon`` ist nie ein Pflicht-Slot (W-TELEFON-ZULETZT, unveraenderlich).
  * Der Vertrag bildet sauber auf die Reducer-``Policy`` ab und der bestehende
    Legacy-Weg (kein ``dialogPolicy`` am Tenant) bleibt byte-genau erhalten.

Offline, kein Netz, nur das Controller-Paket + stdlib.
"""

from __future__ import annotations

from bianca.controller import dialog_policy as DP
from bianca.controller import policy as P


# --------------------------------------------------------------------------- #
# parse(): nie werfend, immer gueltig.
# --------------------------------------------------------------------------- #
def test_parse_leer_liefert_sicheren_default_mit_ok_false():
    for roh in (None, "", 0, [], "kaputt", 42):
        erg = DP.parse(roh)
        assert erg.ok is False
        assert isinstance(erg.policy, DP.DialogPolicyV1)
        # sicher_default fuehrt alle Anliegen.
        for typ in DP.ANLIEGEN:
            assert erg.policy.fuehrt(typ)


def test_parse_leeres_dict_ist_ok_aber_alle_defaults():
    erg = DP.parse({})
    assert erg.ok is True
    p = erg.policy
    assert p.schema_version == DP.SCHEMA_VERSION
    assert p.gespraech.knapp is False
    assert p.gespraech.max_stupse == 2
    assert p.verwaltung.mehrfach_absage is True
    assert p.transfer.erlaubt == ()
    assert p.fach.notfall_sofort is False


def test_parse_nimmt_bekannte_felder_an():
    erg = DP.parse(
        {
            "schemaVersion": 1,
            "revision": 7,
            "updatedBy": "admin@praxis",
            "gespraech": {"knapp": True, "max_stupse": 3, "eingehen": False},
            "identitaet": {"nachname_ruecklese": True},
            "verwaltung": {"mehrfach_absage": False, "termin_zuerst": False},
            "mund": {"antwort_knapp": True, "sonst_noch_nur_nach_erfolg": True},
            "transfer": {"erlaubt": ["Doktor Petsas", "Doktor Patrikis"]},
            "fach": {"notfall_sofort": True},
            "rueckfrage": {"max_rueckfragen": 1},
        }
    )
    assert erg.ok is True
    p = erg.policy
    assert p.revision == 7
    assert p.updated_by == "admin@praxis"
    assert p.gespraech.knapp is True
    assert p.gespraech.max_stupse == 3
    assert p.gespraech.eingehen is False
    assert p.identitaet.nachname_ruecklese is True
    assert p.verwaltung.mehrfach_absage is False
    assert p.verwaltung.termin_zuerst is False
    assert p.mund.antwort_knapp is True
    assert p.mund.sonst_noch_nur_nach_erfolg is True
    assert p.transfer.erlaubt == ("Doktor Petsas", "Doktor Patrikis")
    assert p.fach.notfall_sofort is True
    assert p.rueckfrage.max_rueckfragen == 1


# --------------------------------------------------------------------------- #
# Unveraenderliche Sicherheitsgrenzen — nie konfigurierbar.
# --------------------------------------------------------------------------- #
def test_zahlen_werden_in_die_spanne_geklemmt():
    erg = DP.parse(
        {
            "gespraech": {"max_stupse": 999},
            "rueckfrage": {"max_rueckfragen": -5},
        }
    )
    lo_s, hi_s = DP.GRENZEN["max_stupse"]
    lo_r, hi_r = DP.GRENZEN["max_rueckfragen"]
    assert erg.policy.gespraech.max_stupse == hi_s
    assert erg.policy.rueckfrage.max_rueckfragen == lo_r
    assert lo_s <= erg.policy.gespraech.max_stupse <= hi_s
    assert lo_r <= erg.policy.rueckfrage.max_rueckfragen <= hi_r


def test_kaputte_zahl_faellt_auf_default():
    erg = DP.parse({"gespraech": {"max_stupse": "viele"}})
    assert erg.policy.gespraech.max_stupse == 2  # Default


def test_telefon_ist_nie_ein_pflicht_slot():
    erg = DP.parse({"anliegen": {"buchen": {"pflicht": ["telefon", "nachname"]}}})
    pflicht = erg.policy.anliegen_pol("buchen").pflicht
    assert "telefon" not in pflicht
    assert "nachname" in pflicht
    assert any("telefon" in w for w in erg.warnungen)


def test_unbekannte_slots_werden_verworfen():
    erg = DP.parse({"anliegen": {"buchen": {"pflicht": ["quatsch", "nachname"]}}})
    assert erg.policy.anliegen_pol("buchen").pflicht == ("nachname",)
    assert any("quatsch" in w for w in erg.warnungen)


def test_unbekanntes_anliegen_wird_verworfen():
    erg = DP.parse({"anliegen": {"zaubern": {"an": True}}})
    assert any("zaubern" in w for w in erg.warnungen)
    # zaubern taucht nie als gefuehrtes Anliegen auf.
    assert not erg.policy.fuehrt("zaubern")


def test_anliegen_kann_abgeschaltet_werden():
    erg = DP.parse({"anliegen": {"verbinden": {"an": False}}})
    assert erg.policy.fuehrt("verbinden") is False
    assert erg.policy.fuehrt("buchen") is True


def test_zukuenftige_version_wird_defensiv_gelesen():
    erg = DP.parse({"schemaVersion": 99, "gespraech": {"knapp": True}})
    assert erg.ok is True
    assert erg.policy.schema_version == DP.SCHEMA_VERSION
    assert erg.policy.gespraech.knapp is True
    assert any("schemaVersion" in w for w in erg.warnungen)


def test_as_dict_roundtrip_bleibt_stabil():
    erg = DP.parse(
        {
            "revision": 3,
            "gespraech": {"knapp": True, "max_stupse": 3},
            "transfer": {"erlaubt": ["Doktor A"]},
        }
    )
    d = erg.policy.as_dict()
    erg2 = DP.parse(d)
    assert erg2.policy.as_dict() == d


# --------------------------------------------------------------------------- #
# Abbildung auf die Reducer-Policy.
# --------------------------------------------------------------------------- #
def test_aus_tenant_ohne_dialogpolicy_bleibt_legacy():
    # Kein dialogPolicy -> bisheriger Weg, Defaults der Projektion.
    pol = P.aus_tenant({"clientId": "x", "verbindenErlaubt": ["Doktor Petsas"]})
    assert pol.transfer_erlaubt == ("Doktor Petsas",)
    assert pol.policy_revision == 0
    assert pol.ein_thema is True
    assert set(pol.eigene_tasks)  # fuehrt Aufgaben
    assert pol.spec("buchen") is not None


def test_aus_tenant_mit_dialogpolicy_gewinnt():
    tenant = {
        "clientId": "praxis1",
        "verbindenErlaubt": ["ignoriert"],  # DB-Vertrag schlaegt das
        "dialogPolicy": {
            "revision": 5,
            "gespraech": {"knapp": True, "max_stupse": 1},
            "mund": {"antwort_knapp": True},
            "transfer": {"erlaubt": ["Doktor Neu"]},
            "anliegen": {"verbinden": {"an": False}},
        },
    }
    pol = P.aus_tenant(tenant)
    assert pol.policy_revision == 5
    assert pol.knapp is True
    assert pol.max_stupse == 1
    assert pol.antwort_knapp is True
    # DB-Vertrag gewinnt gegen verbindenErlaubt.
    assert pol.transfer_erlaubt == ("Doktor Neu",)
    # verbinden abgeschaltet -> nicht in eigene_tasks.
    assert "verbinden" not in pol.eigene_tasks
    assert "buchen" in pol.eigene_tasks


def test_leerer_transfer_im_vertrag_faellt_auf_verbindenErlaubt():
    tenant = {
        "clientId": "p",
        "verbindenErlaubt": ["Doktor Fallback"],
        "dialogPolicy": {"revision": 1},
    }
    pol = P.aus_tenant(tenant)
    assert pol.transfer_erlaubt == ("Doktor Fallback",)


def test_explizite_pflicht_reihenfolge_wird_uebernommen():
    tenant = {
        "clientId": "p",
        "dialogPolicy": {
            "anliegen": {"buchen": {"pflicht": ["schonmal", "nachname"]}},
        },
    }
    pol = P.aus_tenant(tenant)
    assert pol.spec("buchen").pflicht == ("schonmal", "nachname")


def test_explizite_identify_reihenfolge_bei_verwaltung():
    tenant = {
        "clientId": "p",
        "dialogPolicy": {
            "anliegen": {"absagen": {"identify": ["nachname", "vorname"]}},
        },
    }
    pol = P.aus_tenant(tenant)
    assert pol.spec("absagen").identify == ("nachname", "vorname")


def test_notfall_marker_aus_vertrag():
    tenant = {"clientId": "p", "dialogPolicy": {"fach": {"notfall_sofort": True}}}
    pol = P.aus_tenant(tenant)
    assert pol.notfall_sofort is True


def test_nachname_ruecklese_setzt_ruecklese_slots():
    tenant = {
        "clientId": "p",
        "dialogPolicy": {"identitaet": {"nachname_ruecklese": True}},
    }
    pol = P.aus_tenant(tenant)
    assert "nachname" in pol.spec("buchen").ruecklese_slots


# --------------------------------------------------------------------------- #
# Laufzeit-Adapter: DB-Vertrag reicht bis in den Reducer durch (agentprofil).
# --------------------------------------------------------------------------- #
def test_agentprofil_reicht_db_dialogpolicy_durch():
    from kern import agentprofil

    pre = {
        "clientId": "praxisX",
        "agent": {
            "clientId": "praxisX",
            "name": "Bianca",
            "dialogPolicy": {
                "revision": 4,
                "gespraech": {"knapp": True},
                "transfer": {"erlaubt": ["Doktor Y"]},
            },
        },
    }
    t = agentprofil.tenant_von_pre(pre, did="+49000")
    assert isinstance(t, dict)
    assert isinstance(t.get("dialogPolicy"), dict)
    assert t["dialogPolicy"].get("revision") == 4
    # Und der Vertrag bildet sich in der Reducer-Policy ab.
    pol = P.aus_tenant(t)
    assert pol.policy_revision == 4
    assert pol.knapp is True
    assert pol.transfer_erlaubt == ("Doktor Y",)


def test_agentprofil_ohne_dialogpolicy_traegt_keins():
    from kern import agentprofil

    pre = {"clientId": "praxisZ", "agent": {"clientId": "praxisZ", "name": "Bianca"}}
    t = agentprofil.tenant_von_pre(pre, did="+49111")
    assert isinstance(t, dict)
    assert "dialogPolicy" not in t or not t.get("dialogPolicy")
    pol = P.aus_tenant(t)
    assert pol.policy_revision == 0  # Legacy-Weg
