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


# --- Anfahrt und ÖPNV (Chef 27.08.2026, Folgeauftrag) -----------------------

def test_meddent_traegt_anfahrt_und_oepnv():
    import re
    w = laden("meddent").get("wissen") or {}
    a = w.get("anfahrt") or ""
    for kern in ("Düsseldorf-Grafenberg", "Grafenberger Allee", "BMW-Autohaus",
                 "Luise-Rainer-Straße", "Arbeitsamt", "Medical Center",
                 "Haus B", "zweite Etage", "Pförtner"):
        assert kern in a, kern
    o = w.get("oepnv") or ""
    for kern in ("U zweiundsiebzig", "U dreiundsiebzig", "U dreiundachtzig",
                 "siebenhundertneun", "Schlüterstraße", "Arbeitsamt"):
        assert kern in o, kern
    assert not re.search(r"\d", o), "Linien-Nummern müssen Wortform bleiben"
    assert not re.search(r"\d", a), "Anfahrtstext muss ziffernfrei sprechbar sein"


def test_wissen_block_traegt_anfahrt_und_oepnv():
    block = wissen_block(laden("meddent").get("wissen"))
    assert "ANFAHRT" in block and "Luise-Rainer-Straße" in block
    assert "AUSNAHMSWEISE" in block, "voller Text muss ausdrücklich erlaubt sein"
    assert "KEINE Parkplatz-Aussagen" in block
    assert "ÖPNV" in block and "U zweiundsiebzig" in block and "Schlüterstraße" in block


def test_langtext_erkennung_nur_bei_wegfragen():
    """Anfahrtsfragen heben das Antwort-Limit an — der volle Text riss sonst
    am Standard-max_tokens mitten im Wort ab ('zweite Et', E2E 27.08.)."""
    from kern.wissen import braucht_langtext
    for satz in ["Ähm, und wie komme ich denn zu Ihnen?", "Wie ist Ihre Adresse?",
                 "Können Sie mir die Anfahrt beschreiben?", "Wo finde ich Sie denn?",
                 "Wie kommt man zu Ihnen?", "Wo sind Sie genau?"]:
        assert braucht_langtext(satz), satz
    for satz in ["Was kostet eine Zahnreinigung?", "Ich hätte gern einen Termin.",
                 "Ja, die Nummer stimmt.", "Welche Bahnlinie fährt zu Ihnen?", ""]:
        assert not braucht_langtext(satz), satz


def test_wissen_block_ohne_anfahrt_kein_abschnitt():
    block = wissen_block({"preise": ["Zahnreinigung: circa 150 Euro."]})
    assert "ANFAHRT" not in block and "ÖPNV" not in block
    for wissen in (None, {}):
        block = wissen_block(wissen)
        assert "ANFAHRT" not in block and "ÖPNV" not in block


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


def test_bianca_prompt_traegt_politik_leitplanke():
    """Chef 29.08.2026: Abschweifer über Trump/Iran/Fußball — Bianca plaudert
    kurz mit, äußert aber NIE eine politische Meinung und führt zurück."""
    for p in (bianca_prompt(praxis="Testpraxis", behandler=""),
              bianca_prompt(praxis="med dent Zahnklinik", behandler="Dr. Petsas",
                            wissen=laden("meddent").get("wissen"))):
        assert "HEIKLE THEMEN" in p
        assert "KEINE Meinung" in p
        assert "Trump" in p and "Iran" in p
        assert "Fußball" in p
        assert "keine Seite Partei" in p
        assert "Rabatt" in p


def test_bianca_agent_reicht_tenant_wissen_durch():
    from bianca.agent import system_prompt_aktuell
    sit = {"tenant": laden("meddent"), "messages": []}
    p = system_prompt_aktuell(sit)
    assert "1600 bis 1800 Euro" in p and VERWEIS_SATZ in p
    assert "Luise-Rainer-Straße" in p and "U zweiundsiebzig" in p


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
