"""Mandanten- und Fachfallbacks dürfen niemals einen anderen Kunden laden."""

from __future__ import annotations

import copy

from bianca import agent, besuchsgrund, flow, gehirn, session
from kern import agentprofil, fachprofil, task_router, tenants


def test_alle_produktiven_dids_haben_eigenen_lokalen_fallback():
    erwartung = {
        "+4921154244101": ("meddent", "MEe4ZQHEzOPzLcexyhdT"),
        "+4921154244110": ("meddent", "MEe4ZQHEzOPzLcexyhdT"),
        "+4921154244105": ("thaler", "7tTnJZfJkb801r2rmYed"),
        "+4921154244120": ("blessing", "UUJnPzoYPa4yYyzcaGlm"),
    }
    for did, (tenant_id, client_id) in erwartung.items():
        t = tenants.von_did(did)
        assert t and t["_id"] == tenant_id, did
        assert t["clientId"] == client_id, did


def test_cf_aus_bleibt_blessing_blessing_und_thaler_thaler(monkeypatch):
    monkeypatch.setattr(agentprofil, "enabled", lambda: False)
    blessing = agentprofil.fuer_did("+4921154244120")
    thaler = agentprofil.fuer_did("+4921154244105")
    assert blessing and blessing["_id"] == "blessing"
    assert blessing["fachgebiet"] == "dermatologie"
    assert thaler and thaler["_id"] == "thaler"
    assert thaler["clientId"] == "7tTnJZfJkb801r2rmYed"
    assert thaler["clientId"] != tenants.laden("meddent")["clientId"]


def test_db_profile_wird_auf_richtige_lokale_fachbasis_gemerged():
    for client_id, did, tenant_id, fach in (
        ("UUJnPzoYPa4yYyzcaGlm", "+4921154244120", "blessing", "dermatologie"),
        ("7tTnJZfJkb801r2rmYed", "+4921154244105", "thaler", "zahnmedizin"),
    ):
        pre = {
            "enabled": True,
            "clientId": client_id,
            "locationId": "loc-db",
            "calendars": [{"id": "cal-db", "name": "Doktor DB"}],
            "visitMotives": [{"id": "vm-db", "name": "Kontrolle", "duration": 10}],
            "agent": {
                "clientId": client_id,
                "locationId": "loc-db",
                "firstMessage": "Begrüßung aus der DB.",
            },
        }
        t = agentprofil.tenant_von_pre(copy.deepcopy(pre), did=did)
        assert t and t["_quelle"] == "cf+datei"
        assert t["_id"] == tenant_id and t["fachgebiet"] == fach
        assert t["begruessungText"] == "Begrüßung aus der DB."


def test_unbekannter_tenant_und_did_fallen_neutral_statt_auf_meddent(monkeypatch):
    unbekannt = tenants.laden("gibt-es-nicht")
    assert unbekannt["_id"] == "fallback-allgemein"
    assert unbekannt["_quelle"] == "fachfallback"
    assert unbekannt["_fallbackOnly"] is True
    assert not unbekannt.get("clientId")
    assert "Petsas" not in str(unbekannt)

    monkeypatch.setattr(agentprofil, "enabled", lambda: False)
    per_did = agentprofil.fuer_did("+493012345678")
    assert per_did and per_did["_id"] == "fallback-allgemein"
    assert per_did["dids"] == ["+493012345678"]


def test_neutraler_fallback_ruft_weder_llm_noch_flow_auf(monkeypatch):
    sit = session.neu(tenant=tenants.laden("gibt-es-nicht"))
    agent.start_reply(sit)
    monkeypatch.setattr(
        agent.tasks,
        "zug",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Flow darf nicht laufen")),
    )
    monkeypatch.setattr(
        agent.llm,
        "chat",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM darf nicht laufen")),
        raising=False,
    )
    z = agent.user_turn(sit, "Ich brauche einen Termin.")
    assert "nicht sicher verfügbar" in z["text"]
    assert not z.get("book")


def test_blessing_prompt_und_warmcache_sind_frei_von_dental_und_meddent():
    t = tenants.laden("blessing")
    sit = session.neu(tenant=t)
    prompt = agent.system_prompt_aktuell(sit)
    router = task_router.prompt(sit)
    warm = "\n".join(gehirn.feste_saetze(t))
    for fremd in (
        "Petsas", "Medical Center", "SCHIENE ABHOLEN",
        "Zahnreinigung", "Bleaching", "Implantat",
    ):
        assert fremd.lower() not in prompt.lower(), fremd
        assert fremd.lower() not in router.lower(), fremd
        assert fremd.lower() not in warm.lower(), fremd


def test_blessing_exakte_und_spezifische_motivwahl():
    t = tenants.laden("blessing")
    kat = t["visitMotives"]
    faelle = {
        "Hautkrebsscreening": "d8gQBR3fJiE0tAAR5c7t",
        "Akne-Sprechstunde": "Hr7bt89rKrK3BDK4BnK4",
        "Venensprechstunde": "YON77rLGke1FMj29PuNH",
        "Kontrolle": "UnfQ5DOaMx9FLiTC3L9b",
    }
    for gesagt, motiv_id in faelle.items():
        _kern, vm = besuchsgrund.deute(t, gesagt, katalog=kat)
        assert vm and vm["id"] == motiv_id, (gesagt, vm)


def test_blessing_lehnt_zahnwunsch_statt_kontrollfallback_ab():
    for gesagt in (
        "Ich brauche einen Termin zur Zahnreinigung.",
        "Ich möchte ein Implantat.",
        "Ich möchte Bleaching machen lassen.",
    ):
        t = tenants.laden("blessing")
        sit = session.neu(tenant=t)
        s = gehirn.sammler(sit)
        s.update({"modus": "buchen", "frage": "grund"})
        z = flow.zug(sit, gesagt)
        assert z and "nicht angeboten" in z["text"]
        assert "Hautkontrolle" in z["text"]
        assert not s["grund"] and not s["motivId"]


def test_blessing_verneinter_zahnwunsch_blockiert_hautgrund_nicht():
    t = tenants.laden("blessing")
    kat = t["visitMotives"]
    gesagt = "Keine Zahnreinigung, ich brauche eine Akne-Sprechstunde."
    assert not besuchsgrund.fachfremder_zahngrund(t, gesagt, katalog=kat)
    _kern, vm = besuchsgrund.deute(t, gesagt, katalog=kat)
    assert vm and vm["id"] == "Hr7bt89rKrK3BDK4BnK4"


def test_blessing_altsitzung_ohne_motiv_startet_keine_slotsuche(monkeypatch):
    t = tenants.laden("blessing")
    sit = session.neu(tenant=t)
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "grund": "Knieoperation",
        "grundWortlaut": "Knieoperation",
        "motivId": "",
        "motivName": "",
        "wunsch": {},
        "frage": "",
    })
    monkeypatch.setattr(
        flow.kal,
        "find_slots",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Keine Slotsuche ohne Dermatologie-Motiv")),
    )
    z = flow._angebot(sit)
    assert z and "nicht angeboten" in z["text"]
    assert not s["grund"] and s["frage"] == "grund"


def test_thaler_unerlaubter_grund_bleibt_im_thaler_template():
    t = tenants.laden("thaler")
    sit = session.neu(tenant=t)
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "grund"})
    z = flow.zug(sit, "Ich brauche eine Wurzelbehandlung.")
    assert z and "Frau Thaler" in z["text"]
    assert "Neupatienten" in z["text"]
    assert "Petsas" not in z["text"] and "Medical Center" not in z["text"]
    assert not s["grund"] and not s["motivId"]


def test_fachtemplates_haben_eigene_grundfragen():
    derma = fachprofil.besuchsgrund_frage({"tenant": tenants.laden("blessing")})
    zahn = fachprofil.besuchsgrund_frage({"tenant": tenants.laden("meddent")})
    allgemein = fachprofil.besuchsgrund_frage(
        {"tenant": tenants.laden("gibt-es-nicht")})
    assert "Haut" in derma
    assert "Schmerzen" in zahn
    assert allgemein == "Worum geht es bei Ihrem Termin?"
