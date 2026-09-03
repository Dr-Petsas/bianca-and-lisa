"""W-MOTIV-KATALOG (Chef 03.09.2026): Besuchsgrund generisch mappen.

"bianca muss den besuchsgrund besser mappen lernen auf die realen
besuchsgründe in der Praxis. die besuchsgründe müssen auf jeden fall parat
stehen in einem RAG oder ähnlichem, weil viele user eigene besuchsgründe
editieren oder erstellen. [...] bei Besuchsgründen mit xy klein oder xy gross
[...] nehmen wir grundsätzlich die klein variante"

Laeuft ohne Netz: der Katalog wird als Liste hereingereicht (im Betrieb
kommt er frisch von masVisitMotives, inkl. der Erklärtexte von
Einstellungsseite und Landingpage).
"""

from bianca import besuchsgrund, gehirn
from kern.tenants import laden


# Nachgebauter Kunden-Katalog: eigene Namen, klein/gross-Varianten,
# Erklärtexte mit HTML-Entities (so liefert die Landingpage sie).
_KATALOG = [
    {"id": "f-klein", "name": "Füllung klein", "nameForPatient": "",
     "duration": 30, "calendarIds": [], "allowOnlineBooking": True},
    {"id": "f-gross", "name": "Füllung groß", "nameForPatient": "",
     "duration": 60, "calendarIds": [], "allowOnlineBooking": True},
    {"id": "funk", "name": "KB klin. Funktionsanalyse", "nameForPatient": "",
     "duration": 45, "calendarIds": [], "allowOnlineBooking": True,
     "patientInfo": "Die Funktionsanalyse ist ein Diagnoseverfahren für das "
                    "Zusammenspiel von Kiefergelenk und Muskulatur."},
    {"id": "versiegel", "name": "PRO Versiegelung", "nameForPatient": "",
     "duration": 15, "calendarIds": [], "allowOnlineBooking": True,
     "landingPageDescription": "Die Fissurenversiegelung sch&uuml;tzt Ihre "
                               "Backenz&auml;hne vor Karies."},
    {"id": "haut", "name": "Hautkrebsscreening", "nameForPatient": "Hautkrebs-Vorsorge",
     "duration": 20, "calendarIds": [], "allowOnlineBooking": True},
    {"id": "nur-cal2", "name": "Füllung Spezial", "nameForPatient": "",
     "duration": 30, "calendarIds": ["cal2"], "allowOnlineBooking": True},
    {"id": "intern", "name": "Füllung Labor intern", "nameForPatient": "",
     "duration": 30, "calendarIds": [], "allowOnlineBooking": False},
    {"id": "kontrolle", "name": "KCH Kontrolluntersuchung", "nameForPatient": "",
     "duration": 15, "calendarIds": [], "allowOnlineBooking": True},
]


def _t(**kw):
    kw.setdefault("katalog", _KATALOG)
    return besuchsgrund.katalog_treffer(kw.pop("text"), **kw)


# --- Klein-Regel: "xy klein oder xy gross -> grundsätzlich klein" -------------

def test_fuellung_nimmt_immer_die_kleine_variante():
    vm = _t(text="Ich hätte gern einen Termin für eine Füllung.")
    assert vm and vm["id"] == "f-klein"


def test_explizit_gross_bleibt_trotzdem_klein():
    # Chef: "nehmen wir GRUNDSÄTZLICH die klein variante" — auch wenn der
    # Anrufer gross sagt, entscheidet die Praxis vor Ort über den Umfang.
    vm = _t(text="Eine große Füllung bitte.")
    assert vm and vm["id"] == "f-klein"


# --- Kundeneigene Gründe: Name, Patientenname, Erklärtexte --------------------

def test_kundeneigener_grund_ueber_namen():
    vm = _t(text="Ich möchte zur Funktionsanalyse kommen.")
    assert vm and vm["id"] == "funk"


def test_dermatologie_grund_ueber_patientennamen():
    vm = _t(text="Ich brauche ein Hautkrebsscreening.")
    assert vm and vm["id"] == "haut"
    vm2 = _t(text="Einen Termin zur Hautkrebs-Vorsorge, bitte.")
    assert vm2 and vm2["id"] == "haut"


def test_erklaertext_hilft_beim_mapping():
    # "Fissuren" steht NUR in der Landingpage-Beschreibung (mit HTML-Entity),
    # "versiegeln" trifft den Namen wortstamm-tolerant.
    vm = _t(text="Ich will die Fissuren versiegeln lassen.")
    assert vm and vm["id"] == "versiegel"


def test_wortstamm_reparieren_trifft_reparatur():
    kat = [{"id": "rep", "name": "KB Korrektur/Reparatur", "duration": 30,
            "calendarIds": [], "allowOnlineBooking": True}]
    vm = besuchsgrund.katalog_treffer("Meine Schiene muss man reparieren.", katalog=kat)
    assert vm and vm["id"] == "rep"


# --- Grenzen: nicht raten ------------------------------------------------------

def test_unbekannter_grund_liefert_none():
    assert _t(text="Ich muss mein Holzbein absägen lassen.") is None


def test_floskel_liefert_none():
    assert _t(text="Ich hätte gerne einen Termin.") is None
    assert _t(text="Guten Tag, hier ist Müller.") is None


def test_kalender_filter_greift():
    vm = _t(text="Füllung Spezial bitte.", calendar_id="cal1")
    # "Füllung Spezial" gehoert nur cal2 — auf cal1 gewinnt die kleine Füllung.
    assert vm and vm["id"] == "f-klein"
    vm2 = _t(text="Füllung Spezial bitte.", calendar_id="cal2")
    assert vm2 and vm2["id"] == "nur-cal2"


def test_interne_motive_stehen_hinten():
    # "Füllung Labor intern" ist nicht online buchbar — buchbare gewinnen.
    vm = _t(text="Füllung bitte.")
    assert vm and vm["id"] == "f-klein"


# --- Durchgriff: deute() nutzt den Katalog nach den Konzepten ------------------

def test_deute_faellt_auf_katalog_zurueck():
    tenant = {"visitMotives": _KATALOG}
    kern, vm = besuchsgrund.deute(tenant, "Termin für eine Füllung, bitte.")
    assert vm and vm["id"] == "f-klein"
    assert kern == "Füllung klein"


def test_deute_konzept_hat_vorrang():
    # "Zahnreinigung" ist kuratiertes Konzept — der Katalog-Weg kommt danach.
    tenant = {"visitMotives": _KATALOG + [
        {"id": "pzr", "name": "PRO professionelle Zahnreinigung",
         "duration": 45, "calendarIds": [], "allowOnlineBooking": True},
    ]}
    kern, vm = besuchsgrund.deute(tenant, "Ich brauche eine Zahnreinigung.")
    assert kern == "professionelle Zahnreinigung"
    assert vm and vm["id"] == "pzr"


# --- gehirn: Ernte + behandlerspezifische Aufloesung ---------------------------

def _sit():
    sit = {"tenant": laden("meddent"), "messages": []}
    sit["motivKatalog"] = list(_KATALOG)
    return sit


def test_einsammeln_erntet_kundeneigenen_grund():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "grund"
    gehirn.einsammeln(sit, "Eine Füllung bitte.")
    assert s["motivId"] == "f-klein"
    assert s["grund"] == "Füllung klein"
    assert "Füllung" in s["grundWortlaut"]


def test_motiv_fuer_kalender_nutzt_katalog_treffer():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["grund"] = "Füllung"
    s["grundWortlaut"] = "Ich brauche eine Füllung."
    vm = gehirn.motiv_fuer_kalender(sit, "cal2")
    assert vm and vm["id"] == "nur-cal2" or vm["id"] == "f-klein"
    # Ohne Kalender-Bindung: die kleine Füllung.
    vm2 = gehirn.motiv_fuer_kalender(sit, "")
    assert vm2 and vm2["id"] == "f-klein"


# --- Kurznotiz-Wache: deckt_ab -------------------------------------------------

def test_deckt_ab_erkennt_redundanz_und_abweichung():
    # "Kontrolle" geht im gebuchten Motiv auf -> KEINE Extra-Notiz noetig.
    assert besuchsgrund.deckt_ab("KCH Kontrolluntersuchung Kontrolluntersuchung", "Kontrolle")
    # O-Ton mit eigenem Inhalt -> Notiz ans Terminpopup.
    assert not besuchsgrund.deckt_ab("KCH akute Beschwerden/Notfall", "Der Zahn pocht so komisch")
    assert not besuchsgrund.deckt_ab("KCH Kontrolluntersuchung", "Holzbein absägen")
