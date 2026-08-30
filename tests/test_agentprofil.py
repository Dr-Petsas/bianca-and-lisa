"""W-MANDANT (30.08.2026): DID -> Mandant, offline.

Geprueft wird die ganze Kette ohne Netz: Nummern-Normalisierung, lokale
DID-Zuordnung (tenants/*.json, dids-Feld), das Mapping der Cloud-Function-
Antwort (onPickadocPhoneCall phase=pre) auf Biancas Tenant-Schema samt
Basis-Overlay ueber die clientId, der TTL-Cache und die UUID->DID-
Uebersetzung der SIP-Bruecke.
"""

from __future__ import annotations

import copy

from bianca import session
from kern import agentprofil, tenants

# Beispiel-Antwort im Format des alten phone_agent (firestore_agent_profile).
CF_PRE = {
    "enabled": True,
    "phoneCallId": "pc-1",
    "clientId": "client-fremd",
    "locationId": "loc-fremd",
    "doctors": ["Doktor Beispiel"],
    "calendars": [{"id": "cal-1", "name": "Doktor Beispiel", "gender": ""}],
    "visitMotives": [
        {"id": "vm-1", "name": "Kontrolle", "nameForPatient": "Kontrolluntersuchung",
         "duration": 30},
        {"id": "vm-2", "name": "", "nameForPatient": "Beratung", "duration": 15},
    ],
    "agent": {
        "id": "agent-1",
        "name": "Bianca",
        "phoneNumber": "+4930111222",
        "clientId": "client-fremd",
        "locationId": "loc-fremd",
        "firstMessage": "Praxis Beispiel, guten Tag! Mein Name ist Bianca.",
        "keywords": "Beispiel, Narval; Aligner",
        "mainLanguage": "de",
        "locationPrompt": "Adresse: Beispielweg 1, 10999 Berlin.",
        "referrerPrompt": "Überweiser: Dr. Muster (Kieferorthopädie).",
    },
}


def test_nummer_norm_varianten():
    soll = "4921154244101"
    assert tenants.nummer_norm("+49 211 54244101") == soll
    assert tenants.nummer_norm("004921154244101") == soll
    assert tenants.nummer_norm("0211 54244101") == soll
    assert tenants.nummer_norm("4921154244101") == soll
    assert tenants.nummer_norm("") == ""


def test_lokaler_tenant_traegt_die_dids():
    t = tenants.von_did("+4921154244101")
    assert t is not None and t["_id"] == "meddent"
    t2 = tenants.von_did("021154244110")
    assert t2 is not None and t2["_id"] == "meddent"
    assert tenants.von_did("+49999999999") is None


def test_fuer_did_ohne_cf_faellt_auf_lokale_datei(monkeypatch):
    # CF aus (kein Token / DID_AGENT=0): die kuratierte Datei traegt den Anruf.
    def _knall(*a, **k):
        raise AssertionError("CF darf bei enabled()=False nicht angefragt werden")
    monkeypatch.setattr(agentprofil, "_cf_pre", _knall)
    monkeypatch.setattr(agentprofil, "enabled", lambda: False)
    t = agentprofil.fuer_did("+4921154244110")
    assert t is not None and t["_id"] == "meddent"
    assert t["clientId"] == "MEe4ZQHEzOPzLcexyhdT"


def test_fuer_did_db_gewinnt_vor_lokaler_datei(monkeypatch):
    """Chef 30.08.2026: die Konfig und somit die Begruessung MUSS aus der DB
    kommen — auch fuer DIDs, die eine lokale tenants/*.json traegt."""
    agentprofil.cache_leeren()
    pre = copy.deepcopy(CF_PRE)
    pre["clientId"] = pre["agent"]["clientId"] = "MEe4ZQHEzOPzLcexyhdT"
    pre["agent"]["firstMessage"] = "Zahnfeen im Medical Center, guten Tag!"
    monkeypatch.setattr(agentprofil, "_cf_pre", lambda did, caller="": copy.deepcopy(pre))
    monkeypatch.setattr(agentprofil, "enabled", lambda: True)
    t = agentprofil.fuer_did("+4921154244110")
    assert t is not None
    assert t["_quelle"] == "cf+datei"
    assert t["begruessungText"].startswith("Zahnfeen im Medical Center")
    assert "Beispielweg 1" in t["dbPrompt"]
    agentprofil.cache_leeren()


def test_fuer_did_cf_down_faellt_auf_lokale_datei(monkeypatch):
    # CF nicht erreichbar: der Anruf laeuft ueber die kuratierte Datei weiter.
    agentprofil.cache_leeren()

    def _kaputt(did, caller=""):
        raise RuntimeError("CF down")

    monkeypatch.setattr(agentprofil, "_cf_pre", _kaputt)
    monkeypatch.setattr(agentprofil, "enabled", lambda: True)
    t = agentprofil.fuer_did("+4921154244110")
    assert t is not None and t["_id"] == "meddent"
    agentprofil.cache_leeren()


def test_cf_mapping_fremder_mandant():
    t = agentprofil.tenant_von_pre(copy.deepcopy(CF_PRE), did="4930111222")
    assert t is not None
    assert t["clientId"] == "client-fremd"
    assert t["locationId"] == "loc-fremd"
    assert t["_quelle"] == "cf"
    assert t["calendars"] == [{"id": "cal-1", "name": "Doktor Beispiel"}]
    assert t["defaultCalendarId"] == "cal-1"
    # Motiv ohne internen Namen faellt auf nameForPatient zurueck.
    assert {"id": "vm-1", "name": "Kontrolle", "duration": 30} in t["visitMotives"]
    assert {"id": "vm-2", "name": "Beratung", "duration": 15} in t["visitMotives"]
    assert t["behandler"] == "Doktor Beispiel"
    assert t["telefon"] == "+4930111222"
    assert t["sttHotwords"] == ["Beispiel", "Narval", "Aligner"]
    # Ohne kuratierte Datei spricht Bianca die DB-Begruessung.
    assert t["begruessungText"].startswith("Praxis Beispiel")


def test_cf_mapping_bekannte_clientid_nutzt_lokale_basis():
    pre = copy.deepcopy(CF_PRE)
    pre["clientId"] = pre["agent"]["clientId"] = "MEe4ZQHEzOPzLcexyhdT"
    t = agentprofil.tenant_von_pre(pre, did="4930111222")
    assert t is not None
    assert t["_quelle"] == "cf+datei"
    assert t["_id"] == "meddent"
    # Kuratierte Sprechformen und Wissen bleiben als Basis erhalten ...
    assert t["praxisNameMelde"] == "Zahnärzte im Medical Center"
    assert "wissen" in t
    # ... aber Begruessung und Agent-Prompt kommen IMMER aus der DB
    # (Chef 30.08.2026 — sein Marker-Text validiert genau das).
    assert t["begruessungText"].startswith("Praxis Beispiel")
    assert "# Standort:" in t["dbPrompt"] and "Beispielweg 1" in t["dbPrompt"]
    # ... und die dynamischen DB-Daten legen sich darueber.
    assert t["calendars"] == [{"id": "cal-1", "name": "Doktor Beispiel"}]
    # Mandanten-Hotwords werden gemerged, nicht ersetzt.
    assert "Grüger" in t["sttHotwords"] and "Narval" in t["sttHotwords"]


def test_cf_mapping_lehnt_disabled_und_leere_antwort_ab():
    aus = copy.deepcopy(CF_PRE)
    aus["enabled"] = False
    assert agentprofil.tenant_von_pre(aus) is None
    assert agentprofil.tenant_von_pre({}) is None
    assert agentprofil.tenant_von_pre(None) is None  # type: ignore[arg-type]


def test_fuer_did_cf_weg_mit_cache(monkeypatch):
    agentprofil.cache_leeren()
    zaehler = {"n": 0}

    def _fake_pre(did, caller=""):
        zaehler["n"] += 1
        return copy.deepcopy(CF_PRE)

    monkeypatch.setattr(agentprofil, "_cf_pre", _fake_pre)
    monkeypatch.setattr(agentprofil, "enabled", lambda: True)
    t1 = agentprofil.fuer_did("+4930111222")
    t2 = agentprofil.fuer_did("004930111222")  # gleiche Nummer, andere Schreibform
    assert t1 is not None and t2 is not None
    assert t1["clientId"] == t2["clientId"] == "client-fremd"
    assert zaehler["n"] == 1  # zweiter Anruf kam aus dem Cache
    # W-CALLSTATUS: die phoneCallId gehoert zum ERSTEN Anruf — der frische
    # Wurf traegt sie, der Cache-Treffer darf sie NIE wiederverwenden.
    assert t1["_phoneCallId"] == "pc-1"
    assert "_phoneCallId" not in t2
    agentprofil.cache_leeren()


def test_fuer_did_cf_fehler_faellt_auf_none(monkeypatch):
    agentprofil.cache_leeren()

    def _kaputt(did, caller=""):
        raise RuntimeError("CF down")

    monkeypatch.setattr(agentprofil, "_cf_pre", _kaputt)
    monkeypatch.setattr(agentprofil, "enabled", lambda: True)
    assert agentprofil.fuer_did("+4930111299") is None
    agentprofil.cache_leeren()


def test_session_neu_traegt_cf_tenant():
    t = agentprofil.tenant_von_pre(copy.deepcopy(CF_PRE), did="4930111222")
    sit = session.neu(tenant=t)
    assert sit["tenant"]["clientId"] == "client-fremd"
    assert sit["tenantId"] == t["_id"]
    # Alter Weg unveraendert:
    sit2 = session.neu(tenant_id="meddent")
    assert sit2["tenant"]["_id"] == "meddent"


def test_bruecke_uebersetzt_uuid_in_did():
    from sip_bridge.server import did_von_uuid

    u4101 = bytes.fromhex("b1a2ca000000000000000000" + "00004101")
    u4110 = bytes.fromhex("b1a2ca000000000000000000" + "00004110")
    u4120 = bytes.fromhex("b1a2ca000000000000000000" + "00004120")
    fremd = bytes.fromhex("deadbeefdeadbeefdeadbeefdeadbeef")
    assert did_von_uuid(u4101) == "+4921154244101"
    assert did_von_uuid(u4110) == "+4921154244110"
    assert did_von_uuid(u4120) == "+4921154244120"  # Blessing (30.08.2026)
    assert did_von_uuid(fremd) == ""
    assert did_von_uuid(b"") == ""


def test_bruecke_liest_anrufer_aus_uuid_kopf():
    """W-ANRUFER: der Dialplan packt die CALLERID-Ziffern rechtsbuendig in
    die ersten 20 Hex-Zeichen (links 'f'-Polster); das DID-Ende bleibt."""
    from sip_bridge.server import caller_von_uuid, did_von_uuid

    # Zaluma-Format 004915253904756 (15 Ziffern) + DID-Ende 4101.
    u = bytes.fromhex("fffff004915253904756" + "000000004101")
    assert caller_von_uuid(u) == "004915253904756"
    assert did_von_uuid(u) == "+4921154244101"  # DID-Erkennung unveraendert
    # Unterdrueckte Nummer: reines f-Polster.
    assert caller_von_uuid(bytes.fromhex("f" * 20 + "000000004101")) == ""
    # Alte feste Dialplan-UUID und Zufalls-UUIDs (Proben) -> keine Nummer.
    assert caller_von_uuid(bytes.fromhex("b1a2ca000000400080000000" + "00004101")) == ""
    assert caller_von_uuid(bytes.fromhex("deadbeefdeadbeefdeadbeefdeadbeef")) == ""
    # Zu kurze Ziffernreste zaehlen nicht als Nummer.
    assert caller_von_uuid(bytes.fromhex("f" * 16 + "1234" + "000000004101")) == ""
    assert caller_von_uuid(b"") == ""


def test_cf_pre_normalisiert_anrufer_auf_e164(monkeypatch):
    """Die CF matcht Patienten ueber trimPhoneNumber ("+49…") — die Bruecke
    liefert die Nummer roh (00-/0-Praefix), _cf_pre macht +E164 daraus."""
    gesehen: list[dict] = []
    monkeypatch.setattr(agentprofil, "_cf_senden",
                        lambda body: gesehen.append(body) or {})
    agentprofil._cf_pre("4921154244101", caller="004915253904756")
    agentprofil._cf_pre("4921154244101", caller="015253904756")
    agentprofil._cf_pre("4921154244101", caller="")
    assert gesehen[0]["callerPhone"] == "+4915253904756"
    assert gesehen[1]["callerPhone"] == "+4915253904756"
    assert gesehen[2]["callerPhone"] == "anonymous"


def test_begruessung_nutzt_db_text_wenn_gesetzt():
    from bianca import agent

    t = agentprofil.tenant_von_pre(copy.deepcopy(CF_PRE), did="4930111222")
    sit = session.neu(tenant=t)
    reply = agent.start_reply(sit)
    assert reply["text"].startswith("Praxis Beispiel")
    # Kuratierte Mandanten OHNE DB-Agent melden sich wie bisher.
    sit2 = session.neu(tenant_id="meddent")
    reply2 = agent.start_reply(sit2)
    assert "Zahnärzte im Medical Center" in reply2["text"]


def test_db_prompt_aus_fragmenten_mit_platzhaltern():
    agent = {
        "rolePrompt": "Du bist die Assistentin der Praxis Beispiel.",
        "locationPrompt": "Adresse: Beispielweg 1. Heute ist {{current_week_day}}.",
        "systemPrompt": "DARF NICHT ERSCHEINEN (Fragmente gewinnen).",
    }
    text = agentprofil.db_prompt_von_agent(agent)
    assert text.startswith("# Rolle:\nDu bist die Assistentin")
    assert "# Standort:" in text and "Beispielweg 1" in text
    assert "{{current_week_day}}" not in text  # Platzhalter eingeloest
    assert "DARF NICHT ERSCHEINEN" not in text
    # Unbekannte Platzhalter bleiben stehen (kein stilles Wegschneiden).
    assert "{{voodoo}}" in agentprofil.db_prompt_von_agent({"rolePrompt": "x {{voodoo}}"})


def test_db_prompt_blob_rueckfall_wenn_fragmente_leer():
    # Manche Betreiber pflegen alles im systemPrompt-Feld.
    agent = {"rolePrompt": "", "systemPrompt": "Kompletter Blob-Prompt."}
    assert agentprofil.db_prompt_von_agent(agent) == "Kompletter Blob-Prompt."
    assert agentprofil.db_prompt_von_agent({}) == ""


class _SofortThread:
    """Testdouble: fuehrt das Thread-Target synchron aus."""

    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        if self._target:
            self._target()


def test_call_erfassen_frische_cf_antwort_traegt_phonecallid(monkeypatch):
    monkeypatch.setattr(agentprofil, "enabled", lambda: True)
    t = agentprofil.tenant_von_pre(copy.deepcopy(CF_PRE), did="4930111222")
    sit = session.neu(tenant=t)
    agentprofil.call_erfassen(sit, did="+4930111222")
    assert sit["phoneCallId"] == "pc-1"
    assert "_phoneCallId" not in sit["tenant"]  # nie persistieren/cachen
    assert sit["did"] == "+4930111222"


def test_call_erfassen_cache_hit_registriert_nach(monkeypatch):
    monkeypatch.setattr(agentprofil, "enabled", lambda: True)
    monkeypatch.setattr(agentprofil, "_cf_pre",
                        lambda did, caller="": {"phoneCallId": "pc-neu"})
    monkeypatch.setattr(agentprofil.threading, "Thread", _SofortThread)
    t = agentprofil.tenant_von_pre(copy.deepcopy(CF_PRE), did="4930111222")
    t.pop("_phoneCallId", None)  # wie ein Cache-Treffer
    sit = session.neu(tenant=t)
    agentprofil.call_erfassen(sit, did="+4930111222")
    assert sit["phoneCallId"] == "pc-neu"


def test_call_erfassen_lokaler_mandant_ohne_datensatz(monkeypatch):
    monkeypatch.setattr(agentprofil, "enabled", lambda: True)

    def _knall(*a, **k):
        raise AssertionError("lokale Mandanten haben keinen PhoneCall-Datensatz")
    monkeypatch.setattr(agentprofil, "_cf_pre", _knall)
    monkeypatch.setattr(agentprofil.threading, "Thread", _SofortThread)
    sit = session.neu(tenant_id="meddent")  # _quelle fehlt -> Datei-Mandant
    agentprofil.call_erfassen(sit, did="+4921154244101")
    assert "phoneCallId" not in sit


def test_cf_kategorien_aus_der_sitzung():
    assert agentprofil._cf_kategorien({}) == []
    assert agentprofil._cf_kategorien({"lastBook": {"ok": True}}) == ["appointment"]
    assert agentprofil._cf_kategorien({"lastMove": {"ok": True}}) == ["appointment"]
    assert agentprofil._cf_kategorien(
        {"lastCancel": {"ok": True}, "praxisNotiz": {"x": 1}},
    ) == ["cancellation", "callbackRequest"]
    # Fehlgeschlagene Werkzeuge zaehlen nicht.
    assert agentprofil._cf_kategorien({"lastBook": {"ok": False}}) == []


def test_call_abschliessen_sendet_post_und_analysis(monkeypatch):
    monkeypatch.setattr(agentprofil, "enabled", lambda: True)
    gesendet: list[dict] = []

    def _fake_senden(body):
        gesendet.append(body)
        return {"status": "success"}

    monkeypatch.setattr(agentprofil, "_cf_senden", _fake_senden)
    monkeypatch.setattr(agentprofil, "_analyse_llm", lambda transcript: {
        "summary": "Anrufer wollte einen Termin; wurde gebucht.",
        "categories": ["question", "quatsch-kategorie"],
        "patientSatisfaction": 5,
        "patientSatisfactionReason": "freundlich",
        "agentError": False,
        "agentErrorDetails": [],
        "dissatisfactionCause": "none",
        "dissatisfactionCauseReason": "Termin gebucht",
    })
    t = agentprofil.tenant_von_pre(copy.deepcopy(CF_PRE), did="4930111222")
    sit = session.neu(tenant=t)
    sit["phoneCallId"] = "pc-1"
    sit["lastBook"] = {"ok": True, "booked": True}
    sit["messages"] = [
        {"role": "system", "content": "x"},
        {"role": "user", "content": "(Ein Anrufer ist in der Leitung.)"},
        {"role": "assistant", "content": "Praxis Beispiel, guten Tag!"},
        {"role": "user", "content": "Ich brauche einen Termin."},
    ]
    agentprofil.call_abschliessen(sit)

    assert [b["phase"] for b in gesendet] == ["post", "analysis"]
    post = gesendet[0]
    assert post["phoneCallId"] == "pc-1"
    assert post["clientId"] == "client-fremd" and post["locationId"] == "loc-fremd"
    assert post["endReason"] == "hangup"
    assert post["categories"] == ["appointment"]
    # Transkript ohne System-/Regie-Zeilen, Rollen im DocGenda-Format.
    rollen = [(x["role"], x["message"]) for x in post["transcript"]]
    assert rollen == [("agent", "Praxis Beispiel, guten Tag!"),
                      ("user", "Ich brauche einen Termin.")]
    analysis = gesendet[1]
    assert analysis["summary"].startswith("Anrufer wollte")
    # Harte + erlaubte weiche Kategorien, Fantasie-Namen fliegen raus.
    assert analysis["categories"] == ["appointment", "question"]
    # Die CF baut IMMER ein evaluation-Update — JEDES Feld muss belegt sein,
    # sonst wirft ihr Firestore-Write still (live erlebt 30.08.2026).
    ev = analysis["evaluation"]
    assert set(ev) == {"patientSatisfaction", "patientSatisfactionReason",
                       "toolError", "toolErrorDetails", "agentError",
                       "agentErrorDetails", "dissatisfactionCause",
                       "dissatisfactionCauseReason"}
    assert ev["patientSatisfaction"] == 5 and ev["dissatisfactionCause"] == "none"
    assert ev["toolError"] is False and ev["toolErrorDetails"] == []
    assert not any(v is None for v in ev.values())


def test_call_abschliessen_ohne_llm_faellt_auf_neutrale_bewertung(monkeypatch):
    monkeypatch.setattr(agentprofil, "enabled", lambda: True)
    gesendet: list[dict] = []
    monkeypatch.setattr(agentprofil, "_cf_senden",
                        lambda body: gesendet.append(body) or {"status": "success"})
    monkeypatch.setattr(agentprofil, "_analyse_llm", lambda transcript: {})
    import kern.gedaechtnis as ged
    monkeypatch.setattr(ged, "zusammenfassung",
                        lambda sit: "Laut Anruf (Bianca): Termin vereinbart.")
    t = agentprofil.tenant_von_pre(copy.deepcopy(CF_PRE), did="4930111222")
    sit = session.neu(tenant=t)
    sit["phoneCallId"] = "pc-1"
    sit["tools"] = [{"name": "book_slot", "ok": False}]
    agentprofil.call_abschliessen(sit)
    analysis = gesendet[1]
    assert analysis["summary"].startswith("Laut Anruf")  # deterministischer Rueckfall
    ev = analysis["evaluation"]
    assert ev["patientSatisfaction"] == 3
    assert ev["patientSatisfactionReason"] == "keine automatische Bewertung"
    assert ev["dissatisfactionCause"] == "unknown"
    assert ev["toolError"] is True and ev["toolErrorDetails"] == ["book_slot"]
    assert not any(v is None for v in ev.values())


def test_json_objekt_aus_llm_antwort():
    roh = 'Hier:\n```json\n{"summary": "ok", "patientSatisfaction": 4}\n```'
    obj = agentprofil._json_objekt(roh)
    assert obj and obj["summary"] == "ok" and obj["patientSatisfaction"] == 4
    assert agentprofil._json_objekt("kein json") is None


def test_call_abschliessen_ohne_phonecallid_schweigt(monkeypatch):
    monkeypatch.setattr(agentprofil, "enabled", lambda: True)

    def _knall(body):
        raise AssertionError("ohne phoneCallId darf nichts gesendet werden")
    monkeypatch.setattr(agentprofil, "_cf_senden", _knall)
    sit = session.neu(tenant_id="meddent")
    agentprofil.call_abschliessen(sit)  # darf nicht werfen, nicht senden


def test_system_prompt_merged_db_profil_und_bleibt_neutral():
    """Chef 30.08.2026: DB-Prompt + fester Verhaltens-Prompt gemerged; im
    festen Prompt duerfen KEINE Praxis-Spezifika stehen (Namen, Adressen,
    Telefonnummern) — die kommen aus der DB."""
    from bianca.prompt import system_prompt

    mit = system_prompt(praxis="Praxis Beispiel", behandler="",
                        db_prompt="# Standort:\nBeispielweg 1, Berlin.")
    assert "PRAXIS-PROFIL" in mit and "Beispielweg 1" in mit
    assert "gelten die Regeln dieses Prompts" in mit

    ohne = system_prompt(praxis="X", behandler="")
    assert "PRAXIS-PROFIL" not in ohne
    # Der feste Prompt-Text ist praxis-neutral (keine echten Behandler/Orte).
    for wort in ("Petsas", "Patrikis", "Nikolaou", "Medical Center", "Düsseldorf"):
        assert wort not in ohne
