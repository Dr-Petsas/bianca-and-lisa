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

def test_meddent_heisst_zahnaerzte_im_medical_center():
    t = laden("meddent")
    assert t.get("praxisName") == "Zahnärzte im Medical Center"
    assert "Medical Center" in (t.get("locationName") or "")
    assert "med dent" not in (t.get("praxisName") or "").lower()
    assert "Zahnklinik" not in (t.get("praxisName") or "")
    namen = [v.get("name") for v in (t.get("visitMotives") or [])]
    assert "KCH Endo klein" in namen
    assert "ZE Reparatur klein" in namen


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
    assert "PARKEN" in block and "Tiefgarage" in block
    assert "KEINE Parkplatz-Aussagen" not in block
    assert "ÖPNV" in block and "U zweiundsiebzig" in block and "Schlüterstraße" in block
    assert "KONTAKT" in block and "0211 30293029" in block
    assert "ÖFFNUNGSZEITEN" in block and "achtzehn Uhr" in block
    assert "ADRESSE" in block and "CeraWhite" in block


def test_langtext_erkennung_nur_bei_wegfragen():
    """Anfahrtsfragen heben das Antwort-Limit an — der volle Text riss sonst
    am Standard-max_tokens mitten im Wort ab ('zweite Et', E2E 27.08.)."""
    from kern.wissen import braucht_langtext
    for satz in ["Ähm, und wie komme ich denn zu Ihnen?", "Wie ist Ihre Adresse?",
                 "Können Sie mir die Anfahrt beschreiben?", "Wo finde ich Sie denn?",
                 "Wie kommt man zu Ihnen?", "Wo sind Sie genau?",
                 "Wo kann ich parken?", "Wie sind Ihre Öffnungszeiten?"]:
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
    p = bianca_prompt(praxis="Zahnärzte im Medical Center", behandler="Dr. Petsas",
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
    assert "Luise-Rainer-Straße" in p and "U zweiundsiebzig" in p
    assert "HEUTE IST" in p and "2026" in p
    assert "Dr. Patrikis" in p and "Dr. Nikolaou" in p
    assert "unbekannt abtun" in p
    assert "Praxis von" not in p
    assert "BEHANDLER:" not in p
    assert "DREI gleichgestellte" in p
    assert "Zahnärzte im Medical Center" in p
    assert "med dent" not in p.lower() and "MedDent" not in p


def test_heute_frage_und_antwort_kommen_aus_der_uhr():
    from datetime import date
    from kern.wissen import heute_antwort, ist_heute_frage
    for satz in ["Welcher Tag es heute?", "Welches Datum haben wir?",
                 "Was ist heute für ein Tag?", "Der wievielte ist heute?",
                 "Ich würde gerne wissen, welcher Tacken.",
                 "Welcher Tag?"]:
        assert ist_heute_frage(satz), satz
    for satz in ["Heute Nachmittag hätte ich Zeit.", "Passt es heute?",
                 "Ich war heute schon da.", "Welcher Tag passt Ihnen?",
                 "Welcher Tag nächste Woche?", ""]:
        assert not ist_heute_frage(satz), satz
    a = heute_antwort(heute=date(2026, 8, 28))
    assert a == "Heute ist Freitag, den achtundzwanzigsten August 2026."


def test_bianca_datumsfrage_ohne_llm():
    """Live 28.08.2026: Modell erfand 'Mittwoch, 25. Mai 2025'."""
    from bianca.agent import user_turn
    from kern.tenants import laden
    sit = {
        "tenant": laden("meddent"),
        "sammler": {},
        "messages": [
            {"role": "system", "content": "x"},
            {"role": "assistant", "content": "Was kann ich für Sie tun?"},
        ],
    }
    from kern import wissen as w
    alt = w.heute_antwort
    w.heute_antwort = lambda heute=None: "Heute ist Freitag, den achtundzwanzigsten August 2026."
    try:
        r = user_turn(sit, "Welcher Tag es heute?")
        r2 = user_turn(sit, "Ich würde gerne wissen, welcher Tacken.")
    finally:
        w.heute_antwort = alt
    assert "Freitag" in r["text"] and "2026" in r["text"]
    assert "2025" not in r["text"] and "Mai" not in r["text"]
    assert "Freitag" in r2["text"] and "Tacken" not in r2["text"] and "Neckar" not in r2["text"]


def test_lisa_prompt_traegt_preise_und_verweisregel():
    p = lisa_prompt(praxis="Zahnärzte im Medical Center", behandler="Dr. Petsas",
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
