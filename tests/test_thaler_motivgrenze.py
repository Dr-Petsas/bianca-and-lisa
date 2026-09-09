"""Thaler: harte Telefon-Freigabe der sechs Besuchsgrund-Gruppen (09.09.2026).

Andere Katalogtermine duerfen nicht angeboten oder still als Kontrolle
gebucht werden. Fuellung ist die ausdrueckliche Ausnahme: ZE-Besprechung.
MedDent/Blessing bleiben von der Thaler-Grenze unberuehrt.
"""

from bianca import flow, gehirn
from kern import zimmer_map


EVA = "cal-eva"
KAT = [
    {"id": "kch-erstuntersuchung-neupatient-30min",
     "name": "KCH Erstuntersuchung / Neupatient", "allowOnlineBooking": False},
    {"id": "kch-kontrolluntersuchung-15min",
     "name": "KCH Kontrolluntersuchung", "allowOnlineBooking": False},
    {"id": "kch-akute-beschwerden-notfall-30min",
     "name": "KCH Akute Beschwerden / Notfall", "allowOnlineBooking": True},
    {"id": "imp-besprechung-30min",
     "name": "IMP Besprechung", "nameForPatient": "Implantat-Beratung",
     "allowOnlineBooking": True},
    {"id": "ze-besprechung-25min",
     "name": "ZE Besprechung", "nameForPatient": "Zahnersatz-Beratung",
     "allowOnlineBooking": True},
    {"id": "pro-professionelle-zahnreinigung-recall-6m",
     "name": "PRO Professionelle Zahnreinigung",
     "nameForPatient": "Professionelle Zahnreinigung (PZR)",
     "allowOnlineBooking": True},
    # Nicht telefonisch freigegeben:
    {"id": "kch-fuellung-klein-30min", "name": "KCH Fuellung klein"},
    {"id": "kch-endo-klein-40min", "name": "KCH Endo klein"},
    {"id": "kfo-besprechung-30min", "name": "KFO Besprechung"},
    {"id": "pro-zahnaufhellung-45min", "name": "PRO Zahnaufhellung"},
    {"id": "ze-reparatur-klein-45min", "name": "ZE Reparatur klein"},
    {"id": "imp-kontrolluntersuchung-15min", "name": "IMP Kontrolluntersuchung"},
]


def _tenant() -> dict:
    return {
        "clientId": zimmer_map.THALER_CLIENT,
        "praxisName": "Zahnarztpraxis Eva Thaler",
        "defaultCalendarId": EVA,
        "zimmerMap": dict(zimmer_map.DEFAULT_MAP),
        "calendars": [
            {"id": EVA, "name": "Dr. Eva Thaler"},
            {"id": "cal-pro", "name": "Prophylaxe"},
        ],
    }


def _sit() -> dict:
    return {
        "tenant": _tenant(),
        "motivKatalog": [dict(x) for x in KAT],
        "messages": [{"role": "system", "content": "x"}],
    }


def test_katalog_hat_exakt_sechs_freigegebene_motive():
    erlaubt = zimmer_map.buchbarer_katalog(_tenant(), KAT)
    assert len(erlaubt) == 6
    ids = {x["id"] for x in erlaubt}
    assert "kch-fuellung-klein-30min" not in ids
    assert "kfo-besprechung-30min" not in ids
    assert "imp-kontrolluntersuchung-15min" not in ids


def test_andere_praxis_wird_nicht_gefiltert():
    fremd = {"clientId": "andere-praxis"}
    assert zimmer_map.buchbarer_katalog(fremd, KAT) == KAT


def test_die_sechs_patientenwuensche_mappen_auf_die_sechs_freigaben():
    faelle = [
        ("Ich bin Neupatient.", "kch-erstuntersuchung-neupatient"),
        ("Ich möchte zur Kontrolle.", "kch-kontrolluntersuchung"),
        ("Ich habe starke Zahnschmerzen.", "kch-akute-beschwerden-notfall"),
        ("Ich brauche eine Implantatbesprechung.", "imp-besprechung"),
        ("Ich möchte Zahnersatz besprechen.", "ze-besprechung"),
        ("Ich möchte zur professionellen Zahnreinigung.", "pro-professionelle-zahnreinigung"),
    ]
    for satz, id_teil in faelle:
        _kern, vm = gehirn._grund_deuten(_tenant(), satz, katalog=KAT)
        assert vm and id_teil in vm["id"], (satz, vm)


def test_fuellung_wird_ze_besprechung_nicht_fuellung():
    for satz in (
        "Ich brauche eine Füllung.",
        "Meine Prothese ist kaputt und muss repariert werden.",
        "Die Krone ist herausgefallen.",
    ):
        kern, vm = gehirn._grund_deuten(_tenant(), satz, katalog=KAT)
        assert kern == "Zahnersatz-Beratung", (satz, kern)
        assert vm and vm["id"] == "ze-besprechung-25min", (satz, vm)


def test_implantat_eingriff_wird_nur_besprechung():
    _kern, vm = gehirn._grund_deuten(
        _tenant(), "Ich brauche eine Implantation mit Knochenaufbau.", katalog=KAT)
    assert vm and vm["id"] == "imp-besprechung-30min"


def test_neupatient_mit_behandlungswort_bleibt_neupatient():
    _kern, vm = gehirn._grund_deuten(
        _tenant(), "Ich bin Neupatient und brauche eine Wurzelbehandlung.",
        katalog=KAT,
    )
    assert vm and vm["id"] == "kch-erstuntersuchung-neupatient-30min"


def test_nicht_freigegebener_wunsch_bleibt_bei_grundfrage():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "grund", "warSchonMal": False,
              "arzt": {"typ": "default", "calendarId": EVA,
                       "calendarName": "Dr. Eva Thaler"}})
    res = flow.zug(sit, "Ich möchte eine Wurzelbehandlung.")
    assert res and "Neupatienten" in res["text"]
    assert "Zahnersatz" in res["text"] and "Implantaten" in res["text"]
    assert s["frage"] == "grund"
    assert not s["grund"] and not s["motivId"]
    assert not sit.get("offered")


def test_thaler_grundfrage_nennt_nur_freigegebene_gruppen():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False,
              "arzt": {"typ": "default", "calendarId": EVA,
                       "calendarName": "Dr. Eva Thaler"}})
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "grund"
    for wort in ("Neupatient", "Kontrolle", "Schmerzen", "Zahnersatz",
                 "Implantaten", "Zahnreinigung"):
        assert wort in frage
    for verboten in ("Wurzelbehandlung", "Kieferorthopädie", "Bleaching"):
        assert verboten not in frage
