"""Praxiswissen (Chef 27.08.2026): grobe Preise nennen, alles andere ehrlich
an den Zahnarzt verweisen — Wissen liegt im Mandanten, nicht im Code.

Läuft ohne Netz: Tenant kommt aus tenants/meddent.json, Prompts sind pur.
"""

from bianca.prompt import system_prompt as bianca_prompt
from kern.sprech import betrag_wort, sanitize
from kern.tenants import laden
from kern.wissen import VERWEIS_SATZ, wissen_block
from lisa.prompt import system_prompt as lisa_prompt

PREIS_KERNE = ("120 Euro", "900 bis 1400 Euro", "1600 bis 1800 Euro", "150 Euro", "80 Euro")


# --- Mandant trägt das Wissen ----------------------------------------------

def test_meddent_traegt_preiswissen():
    w = laden("meddent").get("wissen") or {}
    preise = w.get("preise") or []
    assert len(preise) == 5
    alles = " ".join(preise)
    for kern in PREIS_KERNE:
        assert kern in alles, kern
    assert "Narval" in alles
    assert (w.get("preiseSonst") or "") == VERWEIS_SATZ


def test_wissen_block_mit_preisen():
    block = wissen_block(laden("meddent").get("wissen"))
    for kern in PREIS_KERNE:
        assert kern in block, kern
    assert "NUR diese" in block
    assert VERWEIS_SATZ in block
    assert "keine Diagnosen" in block


def test_wissen_block_ohne_preise_verweist_ehrlich():
    for wissen in (None, {}, {"preise": []}):
        block = wissen_block(wissen)
        assert VERWEIS_SATZ in block
        assert "Euro" not in block  # nichts erfunden
        assert "keine Diagnosen" in block


# --- Prompt-Einbau: Bianca und Lisa -----------------------------------------

def test_bianca_prompt_traegt_preise_und_verweisregel():
    p = bianca_prompt(praxis="med dent Zahnklinik", behandler="Dr. Petsas",
                      wissen=laden("meddent").get("wissen"))
    for kern in PREIS_KERNE:
        assert kern in p, kern
    assert "Narval" in p
    assert VERWEIS_SATZ in p
    assert "ZAHNMEDIZIN UND PREISE" in p
    assert "NUR diese" in p


def test_bianca_prompt_ohne_wissen_erfindet_nichts():
    p = bianca_prompt(praxis="Testpraxis", behandler="")
    assert VERWEIS_SATZ in p
    assert "1600" not in p and "Narval" not in p


def test_bianca_agent_reicht_tenant_wissen_durch():
    from bianca.agent import system_prompt_aktuell
    sit = {"tenant": laden("meddent"), "messages": []}
    p = system_prompt_aktuell(sit)
    assert "1600 bis 1800 Euro" in p and VERWEIS_SATZ in p


def test_lisa_prompt_traegt_preise_und_verweisregel():
    p = lisa_prompt(praxis="med dent Zahnklinik", behandler="Dr. Petsas",
                    auftrag="Bitte an den Termin erinnern.", patient="Herr Berger",
                    wissen=laden("meddent").get("wissen"))
    for kern in PREIS_KERNE:
        assert kern in p, kern
    assert VERWEIS_SATZ in p and "ZAHNMEDIZIN UND PREISE" in p


def test_lisa_prompt_ohne_wissen_erfindet_nichts():
    p = lisa_prompt(praxis="Testpraxis", behandler="", auftrag="Kurze Nachricht.", patient="")
    assert VERWEIS_SATZ in p
    assert "1600" not in p and "Narval" not in p


# --- Sprech-Schicht: Euro-Beträge in Worten ---------------------------------

def test_betrag_wort_reihe():
    assert betrag_wort(80) == "achtzig"
    assert betrag_wort(120) == "einhundertzwanzig"
    assert betrag_wort(150) == "einhundertfünfzig"
    assert betrag_wort(900) == "neunhundert"
    assert betrag_wort(1400) == "vierzehnhundert"
    assert betrag_wort(1600) == "sechzehnhundert"
    assert betrag_wort(1800) == "achtzehnhundert"
    assert betrag_wort(1000) == "eintausend"
    assert betrag_wort(1650) == "eintausendsechshundertfünfzig"
    assert betrag_wort(2500) == "zweitausendfünfhundert"
    assert betrag_wort(21) == "einundzwanzig"
    assert betrag_wort(1_000_000) == "1000000"  # außerhalb: Ziffern lassen


def test_sanitize_euro_einzelbetrag():
    assert sanitize("Das kostet ca. 120 Euro.") == "Das kostet circa einhundertzwanzig Euro."
    assert sanitize("Die Zahnreinigung kostet circa 150 Euro.") == \
        "Die Zahnreinigung kostet circa einhundertfünfzig Euro."
    assert sanitize("Ein Beitrag von rund 80 € fällt an.") == \
        "Ein Beitrag von rund achtzig Euro fällt an."
    assert sanitize("Das sind 1.400 Euro.") == "Das sind vierzehnhundert Euro."


def test_sanitize_euro_spannen():
    s = sanitize("Eine Vollkeramik-Krone kostet circa 900 bis 1400 Euro, je nach Kasse.")
    assert "neunhundert bis vierzehnhundert Euro" in s and "900" not in s
    s = sanitize("Ein Implantat kostet in der Regel 1600 bis 1800 Euro.")
    assert "sechzehnhundert bis achtzehnhundert Euro" in s
    s = sanitize("Das liegt zwischen 900 und 1400 Euro.")
    assert "zwischen neunhundert und vierzehnhundert Euro" in s


def test_sanitize_euro_neben_zeit_und_telefon():
    s = sanitize("Die Kontrolle um 09:15 kostet 150 Euro.")
    assert "neun Uhr fünfzehn" in s and "einhundertfünfzig Euro" in s
    s = sanitize("Ihre Nummer 0177 6004600, der Preis ist 150 Euro.")
    assert "0177 6004600" in s and "einhundertfünfzig Euro" in s
    # Dezimalbeträge bleiben unangetastet (kein ',50' -> 'fünfzig'):
    assert "149,50" in sanitize("Das macht 149,50 Euro.")
