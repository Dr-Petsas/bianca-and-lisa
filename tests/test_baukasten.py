"""Katalog-Wachen des Baukasten-Tests: jede Variante muss von Biancas
Deutern verstanden werden, BEVOR sie als Audio in einen Testanruf geht."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bianca import besuchsgrund, telefon  # noqa: E402
from kern import slots, tenants  # noqa: E402
from tests.baukasten import saetze  # noqa: E402


def test_telefon_varianten_parsen_auf_testnummer():
    for satz in saetze.TELEFON + saetze.READBACK_NEIN:
        assert telefon.aus_satz(satz) == saetze.TESTNUMMER, satz


def test_gruende_mappen_aufs_erwartete_motiv():
    tenant = tenants.laden("meddent")
    for gid, (varianten, erwartet) in saetze.GRUENDE.items():
        assert len(varianten) == 10, f"{gid}: {len(varianten)} statt 10 Varianten"
        for satz in varianten:
            _, vm = besuchsgrund.deute(tenant, satz)
            assert vm, f"{gid}: kein Motiv fuer {satz!r}"
            assert erwartet.lower() in vm["name"].lower(), \
                f"{gid}: {satz!r} -> {vm['name']!r}, erwartet {erwartet!r}"


def test_stt_verhoerer_treffen_das_motiv():
    """Reale Parakeet-Verhoerer aus Testlaeufen muessen aufs Motiv mappen
    (live 29.08.2026: "Aligner-Behandlung mit Invisalign" kam als
    "Alleinerbehandlung in Wissalein" an)."""
    tenant = tenants.laden("meddent")
    for satz, erwartet in [
        ("Es geht um eine Alleinerbehandlung in Wissalein.", "KFO"),
        ("Ich interessiere mich für Wissalein.", "KFO"),
        ("Ich hätte gern eine Invisalin-Beratung.", "KFO"),
    ]:
        _, vm = besuchsgrund.deute(tenant, satz)
        assert vm and erwartet.lower() in vm["name"].lower(), \
            f"{satz!r} -> {vm and vm['name']!r}"


def test_wunsch_saetze_werden_als_slotwunsch_verstanden():
    for tag in ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"):
        for nr in range(len(saetze.WUNSCH_MUSTER)):
            satz = saetze.wunsch_satz(tag, nr)
            wunsch = slots.parse_slot_wish(satz)
            assert wunsch, f"kein Slot-Wunsch: {satz!r}"


def test_buchstabier_alphabet_traegt_alle_nachnamen():
    for name in saetze.NACHNAMEN:
        for stil in range(3):
            satz = saetze.buchstabier_satz(name, stil)
            assert satz and name.lower()[0] in satz.lower()
    # Umlaute und Eszett nicht vergessen:
    assert "Ü wie Übermut" in saetze.buchstabier_satz("Müller", 0)


def test_zehn_varianten_je_kernbaustein():
    kern = [
        saetze.EROEFFNUNG_MACHEN, saetze.EROEFFNUNG_ABSAGEN,
        saetze.EROEFFNUNG_VERSCHIEBEN, saetze.EROEFFNUNG_ERFAHREN,
        saetze.SCHONMAL_JA, saetze.SCHONMAL_NEIN, saetze.ARZT_MUSTER,
        saetze.ARZT_EGAL, saetze.WUNSCH_MUSTER, saetze.SLOT_FRUEHER,
        saetze.SLOT_SPAETER, saetze.SLOT_ANNAHME, saetze.NAME_MUSTER,
        saetze.TELEFON, saetze.READBACK_JA, saetze.BESTAETIGUNG_JA,
        saetze.ABSCHIED, saetze.VERSICHERUNG_PRIVAT_MUSTER,
        saetze.VERSICHERUNG_GESETZLICH_MUSTER,
    ]
    for liste in kern:
        assert len(liste) == 10, f"{liste[0]!r}...: {len(liste)} statt 10"
    for gid, varianten in saetze.ANLIEGEN.items():
        assert len(varianten) == 10, f"Anliegen {gid}: {len(varianten)} statt 10"
    for thema in ("wehgetan", "verschoben2x", "rechnung_teuer", "pzr_schlecht",
                  "fussball", "trump", "iran", "kosten_hoch", "hartz4",
                  "ratenzahlung", "taxi"):
        assert len(saetze.ABSCHWEIFER[thema]) == 10, thema


def test_versicherung_saetze_bauen():
    for nr in range(10):
        p = saetze.versicherung_satz(True, nr)
        g = saetze.versicherung_satz(False, nr)
        assert "{" not in p and "{" not in g
        assert p != g


def test_abschweifer_ernten_keinen_grund():
    """Batch 29.08.2026: Meinungs-/Beschwerde-Saetze ("Zahngesundheit ist
    Luxus geworden", "Die letzte Zahnreinigung war nicht gut") wurden auf
    die Grund-Frage als Besuchsgrund verbucht. Kein Abschweifer darf einen
    Grund setzen — und JEDER echte Katalog-Grund muss weiter durchkommen."""
    from bianca import gehirn
    tenant = tenants.laden("meddent")

    def _ernte(satz: str) -> str:
        sit = {"tenant": tenant, "messages": [{"role": "system", "content": "x"}]}
        s = gehirn.sammler(sit)
        s["modus"] = "buchen"
        s["frage"] = "grund"
        gehirn.einsammeln(sit, satz)
        return s["grund"]

    for thema, varianten in saetze.ABSCHWEIFER.items():
        for satz in varianten:
            g = _ernte(satz)
            assert not g, f"Abschweifer {thema}: {satz!r} -> Grund {g!r}"
    for gid, (varianten, _erwartet) in saetze.GRUENDE.items():
        for satz in varianten:
            assert _ernte(satz), f"Katalog-Grund {gid}: {satz!r} kam nicht durch"


def test_schonmal_saetze_ernten_keinen_namen():
    """Live 29.08.2026: "ich bin gerade erst hergezogen" wurde als Name
    "Gerade Hergezogen" verbucht — kein Schonmal-Satz darf Namen setzen."""
    from bianca import gehirn
    tenant = tenants.laden("meddent")
    for satz in saetze.SCHONMAL_JA + saetze.SCHONMAL_NEIN:
        sit = {"tenant": tenant, "messages": [{"role": "system", "content": "x"}]}
        s = gehirn.sammler(sit)
        s["modus"] = "buchen"
        s["frage"] = "schonmal"
        gehirn.einsammeln(sit, satz)
        assert not s["vorname"] and not s["nachname"], \
            f"{satz!r} -> Name {s['vorname']!r} {s['nachname']!r}"


def test_wav_schliessen_macht_stream_header_abspielbar():
    """Stream-WAVs (0xFFFFFFFF) muss der Browser als echte Datei spielen koennen."""
    import struct

    from kern import tts
    from tests.baukasten import klang

    pcm = b"\x00\x00" * 80
    offen = tts.wav_header_offen() + pcm
    assert struct.unpack_from("<I", offen, 40)[0] == 0xFFFFFFFF
    fest = klang.wav_schliessen(offen)
    assert fest[:4] == b"RIFF"
    assert struct.unpack_from("<I", fest, 4)[0] == 36 + len(pcm)
    assert struct.unpack_from("<I", fest, 40)[0] == len(pcm)
    assert klang.wav_schliessen(fest) == fest


def test_telefon_wav_ist_g711_schmalband_nicht_studio():
    """Studio 24 kHz/16 bit -> 8 kHz, μ-law-Dreck, nicht lineare 8-bit-Stufen."""
    import struct

    from tests.baukasten import klang

    n = 24000  # 1 s
    pcm = b"".join(struct.pack("<h", 12000 if (i // 80) % 2 == 0 else -12000)
                   for i in range(n))
    studio = klang._wav_pcm16_header(len(pcm), 24000) + pcm
    tel = klang.telefon_wav(studio)
    assert tel[:4] == b"RIFF"
    assert struct.unpack_from("<I", tel, 24)[0] == 8000
    assert struct.unpack_from("<H", tel, 34)[0] == 16
    samples = (len(tel) - 44) // 2
    assert 7900 <= samples <= 8100
    werte = [struct.unpack_from("<h", tel, 44 + 2 * i)[0] for i in range(80)]
    assert any(v % 256 for v in werte), "μ-law darf keine reinen 256er-Stufen sein"
    assert max(abs(v) for v in werte) > 0


def test_testtermine_werden_erst_nach_2_stunden_reif():
    """Frisch gebuchter Testtermin bleibt 2 Stunden, danach ist er loeschreif."""
    import tempfile
    from datetime import datetime, timedelta
    from pathlib import Path

    from tests.baukasten import aufraeumen

    t0 = datetime(2026, 8, 29, 10, 0, 0)
    with tempfile.TemporaryDirectory() as d:
        basis = Path(d)
        schlange = basis / "autoloesch.json"
        merkliste = basis / "aufgeraeumt.json"
        aufraeumen.vormerken(
            [{"id": "apt-1", "story": "s01", "slotIso": "2026-09-02T09:00:00",
              "gebuchtUm": t0.isoformat(timespec="seconds")}],
            jetzt=t0, pfad=schlange)
        assert aufraeumen.reife(jetzt=t0 + timedelta(hours=1, minutes=59),
                                pfad=schlange, merkliste=merkliste) == []
        reif = aufraeumen.reife(jetzt=t0 + timedelta(hours=2),
                                pfad=schlange, merkliste=merkliste)
        assert [e["id"] for e in reif] == ["apt-1"]
        geraeumt = []
        erg = aufraeumen.reife_ausfuehren(
            jetzt=t0 + timedelta(hours=2), pfad=schlange, merkliste=merkliste,
            cancel_fn=lambda tid: geraeumt.append(tid) or {"cancelled": True})
        assert geraeumt == ["apt-1"] and erg["abgesagt"] == 1
        assert aufraeumen.reife(jetzt=t0 + timedelta(hours=3),
                                pfad=schlange, merkliste=merkliste) == []


def test_vormerken_aus_bericht_nimmt_lastbook():
    from tests.baukasten import aufraeumen

    bericht = {
        "id": "s01-markus-kontrolle",
        "start": "2026-08-29T10:00:00",
        "lastCall": {"lastBook": {
            "booked": True, "appointmentId": "xyz",
            "slotIso": "2026-09-02T09:00:00",
        }},
    }
    funde = aufraeumen.funde_aus_bericht(bericht)
    assert funde[0]["id"] == "xyz"
    assert funde[0]["art"] == "termin"
    assert funde[0]["gebuchtUm"] == "2026-08-29T10:00:00"


def test_neu_angelegte_testakte_wird_nach_2_stunden_reif():
    """Nur createdPatient/lastCreate — Bestandspatienten bleiben in der Kartei."""
    import tempfile
    from datetime import datetime, timedelta
    from pathlib import Path

    from tests.baukasten import aufraeumen

    t0 = datetime(2026, 8, 29, 10, 0, 0)
    bericht = {
        "id": "s02-markus-kontrolle",
        "start": t0.isoformat(timespec="seconds"),
        "lastCall": {
            "patientId": "pat-neu",
            "patientName": "Markus Berger",
            "lastBook": {
                "booked": True, "appointmentId": "apt-2",
                "slotIso": "2026-09-02T09:00:00",
                "createdPatient": True, "patientId": "pat-neu",
            },
            "lastCreate": {"created": True, "patientId": "pat-neu"},
        },
    }
    bestand = {
        "id": "s03-bestand",
        "start": t0.isoformat(timespec="seconds"),
        "lastCall": {
            "patientId": "pat-echt",
            "lastBook": {"booked": True, "appointmentId": "apt-3",
                         "slotIso": "2026-09-03T09:00:00"},
        },
    }
    funde = aufraeumen.funde_aus_bericht(bericht) + aufraeumen.funde_aus_bericht(bestand)
    assert {f["id"] for f in funde if f.get("art") == "patient"} == {"pat-neu"}
    with tempfile.TemporaryDirectory() as d:
        schlange = Path(d) / "autoloesch.json"
        merkliste = Path(d) / "aufgeraeumt.json"
        aufraeumen.vormerken(funde, jetzt=t0, pfad=schlange)
        assert aufraeumen.reife(jetzt=t0 + timedelta(hours=1),
                                pfad=schlange, merkliste=merkliste) == []
        geloescht = []
        erg = aufraeumen.reife_ausfuehren(
            jetzt=t0 + timedelta(hours=2), pfad=schlange, merkliste=merkliste,
            cancel_fn=lambda tid: {"cancelled": True},
            delete_fn=lambda pid: geloescht.append(pid) or {"deleted": True})
        assert "pat-neu" in geloescht
        assert "pat-echt" not in geloescht
        assert erg["abgesagt"] >= 2  # Termin + Akte des neuen, Termin des Bestands


def test_einzelwort_achtet_auf_anzahl():
    from tests.baukasten import geschichten

    story = {
        "einzelwoerter": ["Anmeldung", "Rezept", "Mitarbeiter", "Rückruf"],
        "einzelwortAnzahl": 2,
        "seed": 7,
    }
    lage = geschichten.lage_neu()
    lage["frage"] = "schonmal"
    lage["zaehler"]["antworten"] = 1
    treffer = []
    for _ in range(8):
        lage["letzterBaustein"] = "schonmal"
        w = geschichten._einzelwort(story, lage)
        if w:
            treffer.append(w["text"])
    assert len(treffer) == 2
    assert geschichten.einzelwort_anzahl({"einzelwoerter": ["A", "B"]}) == 2
    assert geschichten.einzelwort_anzahl({"einzelwoerter": ["A"], "einzelwortAnzahl": 0}) == 0
    assert geschichten.einzelwort_anzahl({"einzelwoerter": ["A"], "einzelwortAnzahl": 5}) == 5


def test_lasttest_kappe_auf_acht():
    from tests.baukasten import lasttest

    assert lasttest._kappe(0, 8) == 1
    assert lasttest._kappe(99, lasttest.MAX_PARALLEL) == lasttest.MAX_PARALLEL
    assert lasttest._kappe("4", 8) == 4
    assert lasttest.MAX_PARALLEL == 18


def test_lasttest_verteilt_auf_drei_praxen():
    from tests.baukasten import lasttest

    p = lasttest.verteile(5)
    assert sum(p["counts"].values()) == 5
    assert all(p["counts"][x] >= 1 for x in ("meddent", "thaler", "blessing"))
    assert {s["tenant"] for s in p["sitze"]} == {
        "meddent", "thaler", "blessing",
    }
    sechs = lasttest.verteile(6)
    assert sum(sechs["counts"].values()) == 6
    assert all(sechs["counts"][x] >= 1 for x in ("meddent", "thaler", "blessing"))


def test_lasttest_offset_und_dropout_blase():
    from tests.baukasten import lasttest

    off = lasttest.latenz_offset(1.6, 0.8)
    assert off["offsetS"] == 0.8
    assert off["offsetPct"] == 100.0
    drops = lasttest.dropouts_von_zug(
        tS=2.0, ersterTonS=2.0, antwortS=4.5, leer=False,
        nr=3, tenant="thaler")
    arten = {d["art"] for d in drops}
    assert "ersterTon" in arten
    assert "luecke" in arten
    assert all(d["kurz"] == "Thaler" for d in drops)
    assert max(d["dauerS"] for d in drops) >= 1.2


def test_lasttest_zusammenfassung_zaehlt():
    from tests.baukasten import lasttest

    laeufe = [
        {"nr": 1, "ok": True, "startS": 0.4, "ersterTonS": 0.8, "antwortS": 1.2},
        {"nr": 2, "ok": True, "startS": 0.6, "ersterTonS": 1.5, "antwortS": 2.0},
        {"nr": 3, "ok": False, "startS": 0, "ersterTonS": 0, "antwortS": 0, "fehler": "timeout"},
    ]
    s = lasttest.zusammenfassung(laeufe, n=3, sekunden=5.1)
    assert s["gehalten"] == 2
    assert s["fehler"] == 1
    assert s["dauerS"] == 5.1
    assert s["ersterTonP50"] in (0.8, 1.5)
    assert s["ersterTonP95"] == 1.5
    assert any("kein Buchen" in h.lower() or "Kein Buchen" in h for h in s["hinweise"])
    assert "blasen" in s
    assert s["plan"]["n"] == 3


def test_dauer_s_liest_8khz_header():
    import tempfile
    from pathlib import Path

    from tests.baukasten import klang

    pcm = b"\x00\x00" * 8000  # 1 s bei 8 kHz
    wav = klang._wav_pcm16_header(len(pcm), 8000) + pcm
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "tel.wav"
        p.write_bytes(wav)
        assert 0.95 <= klang.dauer_s(p) <= 1.05


def test_leitungseffekte_veraendern_die_stimme_nicht_den_hintergrund():
    import array
    import struct

    from tests.baukasten import klang

    rate = 8000
    still = [0] * 800
    stimme = [9000 if (i // 10) % 2 else -9000 for i in range(4000)]
    samples = array.array("h", still + stimme + still)
    wav = klang._wav_pcm16_header(len(samples) * 2, rate) + samples.tobytes()
    basis = {
        "hz": rate, "rauschen": 0, "artefakte": 0,
        "dropouts": 0, "pegel": 50, "g711": False,
    }
    roh = klang.telefon_wav(wav, leitung=basis)
    start = 44
    stille_bytes = len(still) * 2
    stimme_start = start + stille_bytes
    stimme_ende = stimme_start + len(stimme) * 2
    for effekt in ("rauschen", "artefakte", "dropouts", "pegel"):
        einstellung = dict(basis)
        einstellung[effekt] = 100
        kaputt = klang.telefon_wav(wav, leitung=einstellung)
        assert kaputt[start:stimme_start] == roh[start:stimme_start], effekt
        assert kaputt[stimme_start:stimme_ende] != roh[stimme_start:stimme_ende], effekt
    noisy = klang.telefon_wav(wav, leitung={**basis, "rauschen": 100})
    delta = [
        struct.unpack_from("<h", noisy, i)[0] - struct.unpack_from("<h", roh, i)[0]
        for i in range(stimme_start, stimme_ende, 2)
    ]
    assert min(delta) < 0 < max(delta)
    assert len(set(delta)) > 100, "Rauschen muss breitbandig statt periodisch sein"


def test_sprechereigenschaften_verfremden_deterministisch():
    from tests.baukasten import deutlichkeit

    text = "Ich beginne die Behandlung gleich und freundlich."
    einstellung = {
        "staerke": 100,
        "kategorien": ["chsch", "hart", "anlaut", "auslaut", "einfuegen"],
    }
    a = deutlichkeit.verfremden(text, einstellung, seed=19)
    b = deutlichkeit.verfremden(text, einstellung, seed=19)
    assert a == b
    assert a["text"] != text
    assert a["hits"]
    assert deutlichkeit._chsch("ich", __import__("random").Random(1)) == "isch"
    assert deutlichkeit._hart("Baba", __import__("random").Random(1)).startswith("P")
    assert len(deutlichkeit._anlaut("Termin", __import__("random").Random(1))) > len("Termin")
    assert deutlichkeit._auslaut("Behandlung", __import__("random").Random(1)).endswith("unk")


def test_statistik_zaehlt_zeitverlauf_und_mandant():
    import json
    import tempfile
    from pathlib import Path

    from tests.baukasten import statistik

    def schreiben(p: Path, data: dict) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")

    with tempfile.TemporaryDirectory() as d:
        basis = Path(d)
        lauf1 = basis / "20260901-100000"
        schreiben(lauf1 / "lauf.json", {
            "laufId": lauf1.name, "tenant": "meddent",
            "gestartet": "2026-09-01T10:00:00",
            "stories": [{"id": "ok-1", "ok": True}, {"id": "rot-1", "ok": False}],
        })
        for sid, ok, check in (("ok-1", True, "kein Fehler"), ("rot-1", False, "Telefon")):
            schreiben(lauf1 / sid / "bericht.json", {
                "id": sid, "start": "2026-09-01T10:00:00",
                "story": {"tenant": "meddent"},
                "zuege": [
                    {"wer": "anrufer", "text": "Hallo", "gehoert": "Hallo"},
                    {"wer": "bianca", "text": "Guten Tag", "latenzS": 2.0, "ersterTonS": 1.0},
                ],
                "ergebnis": {"ok": ok, "checks": [{"name": check, "ok": ok}]},
            })
        lauf2 = basis / "20260902-100000"
        schreiben(lauf2 / "lauf.json", {
            "laufId": lauf2.name, "tenant": "meddent",
            "gestartet": "2026-09-02T10:00:00",
            "stories": [{"id": "ok-2", "ok": True}],
        })
        schreiben(lauf2 / "ok-2" / "bericht.json", {
            "id": "ok-2", "start": "2026-09-02T10:00:00",
            "story": {"tenant": "meddent"},
            "zuege": [{"wer": "anrufer", "text": "Termin", "gehoert": "Termin"}],
            "ergebnis": {"ok": True, "checks": [{"name": "kein Fehler", "ok": True}]},
        })
        last = basis / "last-20260903-100000"
        schreiben(last / "lasttest.json", {
            "laufId": last.name,
            "laeufe": [
                {"nr": 1, "tenant": "meddent", "ok": True, "antwortS": 1.2,
                 "ersterTonS": 0.8, "zuege": [{"text": "ok"}, {"text": "ok"}]},
                {"nr": 2, "tenant": "thaler", "ok": False, "fehler": "timeout", "zuege": []},
            ],
        })
        s = statistik.aus_berichten(basis, "meddent")
        assert s["gesamt"]["gespraeche"] == 4
        assert s["gesamt"]["turns"] == 5
        assert s["gesamt"]["erfolgreich"] == 3
        assert s["gesamt"]["fehlgeschlagen"] == 1
        assert len(s["zeitreihe"]) == 3
        assert s["probleme"][0]["problem"] == "Telefon"
        assert s["analysen"][0]["storyId"] == "rot-1"
        assert statistik.aus_berichten(basis, "thaler")["gesamt"]["gespraeche"] == 1


if __name__ == "__main__":
    fehler = 0
    for name in sorted(n for n in dir() if n.startswith("test_")):
        try:
            globals()[name]()
            print(f"gruen: {name}")
        except AssertionError as e:
            fehler += 1
            print(f"ROT:   {name} — {e}")
    sys.exit(1 if fehler else 0)
