"""Story-Runner des Baukasten-Tests: fuehrt eine Story als ECHTEN Anruf.

Der Runner ist das Dock in Skriptform: er startet eine Sitzung am
Bianca-Dienst (8096), schickt je Zug das gerenderte Anrufer-WAV an
/api/listen (voller Pfad inkl. Parakeet-STT), liest den NDJSON-Strom
(filler/transcript/warte/reply) und mappt Biancas offene Frage ueber
geschichten.naechster_baustein auf den naechsten Katalog-Baustein.

Echtzeit-Taktung: zwischen den Zuegen wird die Spieldauer von Biancas
Antwort plus eine menschliche Denkpause gewartet — so laufen die
Hintergrund-Threads (Kartei-Suche, Gedaechtnis) wie im Live-Anruf.
Die Latenz je Zug misst NUR POST->reply; Mithoeren aendert daran nichts.

Bericht: tests/baukasten/berichte/<lauf>/<story>.json + alle Audios —
die Ergebnisseite (W-BK-5) rendert daraus den Bubble-Dialog.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.baukasten import aufraeumen, geschichten, klang, saetze  # noqa: E402

BASIS = "http://127.0.0.1:8096"
BERICHTE_DIR = Path(__file__).resolve().parent / "berichte"
MAX_ZUEGE = 40
DENKPAUSE_S = 0.8  # menschliche Reaktionszeit zwischen Hoeren und Sprechen

_WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def ziel_datum(tag: str, ab: date | None = None) -> str:
    """'naechste Woche {tag}' als ISO-Datum (der Tag der KOMMENDEN Woche)."""
    heute = ab or date.today()
    naechster_montag = heute + timedelta(days=7 - heute.weekday())
    try:
        offset = _WOCHENTAGE.index(tag)
    except ValueError:
        offset = 2  # unbekannter Tag: Mittwoch
    return (naechster_montag + timedelta(days=offset)).isoformat()


def _abs_url(basis: str, url: str) -> str:
    if not url:
        return ""
    return url if url.startswith("http") else basis.rstrip("/") + url


class Anruf:
    """Ein Testanruf: Sitzung, Zuege, Audio-Ablage, Bericht."""

    def __init__(self, story: dict[str, Any], *, basis: str = BASIS, lauf_dir: Path,
                 echtzeit: bool = True, mithoeren: bool = False, tenant: str = ""):
        self.story = story
        self.basis = basis.rstrip("/")
        self.echtzeit = echtzeit or mithoeren
        self.mithoeren = mithoeren
        self.tenant = tenant
        self.client = httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0))
        self.dir = lauf_dir / str(story.get("id") or f"s{story.get('nr', 0):02d}")
        self.audio_dir = self.dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.zuege: list[dict[str, Any]] = []
        self.session_id = ""
        self.lage = geschichten.lage_neu()
        self.fehler = ""
        self._audio_nr = 0

    # ---- Audio-Helfer -------------------------------------------------------

    def _bianca_audio(self, url: str) -> tuple[str, float]:
        """Biancas Antwort-Audio herunterladen und im Bericht ablegen."""
        voll = _abs_url(self.basis, url)
        if not voll:
            return "", 0.0
        try:
            r = self.client.get(voll)
            r.raise_for_status()
            blob = r.content
        except httpx.HTTPError as e:
            print(f"runner: bianca-audio fehlt ({e})", flush=True)
            return "", 0.0
        if blob[:4] == b"RIFF":
            blob = klang.wav_schliessen(blob)
        self._audio_nr += 1
        name = f"b{self._audio_nr:02d}.wav" if blob[:4] == b"RIFF" else f"b{self._audio_nr:02d}.mp3"
        (self.audio_dir / name).write_bytes(blob)
        dauer = max(0.0, (len(blob) - 44) / (klang.PCM_RATE * 2)) if blob[:4] == b"RIFF" else len(blob) / 4000.0
        return f"audio/{name}", dauer

    def _anrufer_audio(self, text: str) -> tuple[Path, str, float]:
        """Anrufer-WAV aus dem Klang-Cache holen und im Bericht ablegen."""
        text = " ".join((text or "").split())
        pfad = klang.audio_holen(self.story["stimme"], text)
        if self.story.get("telefonQualitaet"):
            pfad = klang.telefon_datei(pfad)
        self._audio_nr += 1
        name = f"a{self._audio_nr:02d}.wav"
        ziel = self.audio_dir / name
        if not ziel.is_file():
            shutil.copyfile(pfad, ziel)
        return pfad, f"audio/{name}", klang.dauer_s(pfad)

    def _abspielen(self, relativ: str) -> None:
        if not self.mithoeren or not relativ:
            return
        pfad = self.dir / relativ
        try:
            import winsound
            winsound.PlaySound(str(pfad), winsound.SND_FILENAME)
        except Exception:
            time.sleep(0.1)

    def _warten(self, s: float) -> None:
        if self.echtzeit and not self.mithoeren and s > 0:
            time.sleep(min(s, 30.0))

    # ---- HTTP ---------------------------------------------------------------

    def _start(self) -> dict[str, Any]:
        r = self.client.post(f"{self.basis}/api/start", json={"tenant": self.tenant})
        r.raise_for_status()
        antwort = r.json()
        self.session_id = str(antwort.get("sessionId") or "")
        if not self.session_id:
            raise RuntimeError("kein sessionId vom /api/start")
        return antwort

    def _listen(self, wav: Path) -> dict[str, Any]:
        """Ein Anrufer-Zug als Audio: NDJSON lesen bis reply/warte/empty."""
        t0 = time.perf_counter()
        erster_ton = 0.0
        ereignisse: list[dict[str, Any]] = []
        final: dict[str, Any] = {}
        with wav.open("rb") as f:
            with self.client.stream(
                "POST", f"{self.basis}/api/listen",
                data={"sessionId": self.session_id, "text": "", "bargeUrl": "", "bargeMs": 0},
                files={"audio": (wav.name, f, "audio/wav")},
            ) as r:
                r.raise_for_status()
                for zeile in r.iter_lines():
                    if not (zeile or "").strip():
                        continue
                    try:
                        ev = json.loads(zeile)
                    except json.JSONDecodeError:
                        continue
                    typ = str(ev.get("type") or "")
                    if typ == "filler" and not erster_ton:
                        erster_ton = round(time.perf_counter() - t0, 2)
                    ereignisse.append(ev)
                    if typ in ("reply", "warte", "empty"):
                        final = ev
                        break
        final["_latenzS"] = round(time.perf_counter() - t0, 2)
        final["_ersterTonS"] = erster_ton or final["_latenzS"]
        final["_ereignisse"] = ereignisse
        return final

    # ---- Zug-Protokoll ------------------------------------------------------

    def _merke_bianca(self, antwort: dict[str, Any], *, latenz: float | None = None,
                      erster_ton: float | None = None) -> float:
        rel, dauer = self._bianca_audio(str(antwort.get("audioUrl") or ""))
        self.zuege.append({
            "wer": "bianca",
            "text": str(antwort.get("text") or ""),
            "audio": rel,
            "dauerS": round(dauer, 2),
            "timings": antwort.get("timings") or {},
            "waechter": antwort.get("waechter") or [],
            "frage": str(antwort.get("frage") or ""),
            "modus": str(antwort.get("modus") or ""),
            "book": antwort.get("book"),
            "latenzS": latenz,
            "ersterTonS": erster_ton,
        })
        self._abspielen(rel)
        return dauer

    def _merke_anrufer(self, text: str, baustein: str, rel: str, dauer: float,
                       gehoert: str = "") -> None:
        self.zuege.append({
            "wer": "anrufer",
            "text": text,
            "gehoert": gehoert,
            "baustein": baustein,
            "audio": rel,
            "dauerS": round(dauer, 2),
        })

    # ---- Hauptlauf ----------------------------------------------------------

    def fuehren(self) -> dict[str, Any]:
        start_zeit = datetime.now().isoformat(timespec="seconds")
        t_lauf = time.perf_counter()
        try:
            begruessung = self._start()
            dauer = self._merke_bianca(begruessung)
            self._warten(dauer + DENKPAUSE_S)
            halbsatz_rest = ""
            stall_frage, stall_n = "", 0  # Anti-Stall: festgefahrene Maschinen-Frage

            for _ in range(MAX_ZUEGE):
                if halbsatz_rest:
                    zug = {"text": halbsatz_rest, "baustein": "halbsatz_rest"}
                    halbsatz_rest = ""
                else:
                    zug = geschichten.naechster_baustein(self.story, self.lage)
                if zug.get("auflegen") and not (zug.get("text") or "").strip():
                    break
                text = " ".join(str(zug.get("text") or "").split())
                if not text:
                    break
                wav, rel, dauer_a = self._anrufer_audio(text)
                self._abspielen(rel)
                final = self._listen(wav)
                typ = str(final.get("type") or "")
                gehoert = ""
                for ev in final.get("_ereignisse") or []:
                    if ev.get("type") == "transcript":
                        gehoert = str(ev.get("textIn") or "")
                self._merke_anrufer(text, str(zug.get("baustein") or ""), rel, dauer_a, gehoert)

                if typ == "warte":
                    # Halbsatz-Wache: kein Ton von Bianca, weiterhoeren.
                    self.zuege.append({"wer": "bianca", "text": "", "warte": True,
                                       "waechter": [{"w": "halbsatz-warte", "d": gehoert}],
                                       "latenzS": final.get("_latenzS")})
                    halbsatz_rest = str(zug.get("halbsatzRest") or "")
                    self._warten(0.9)
                    continue
                if typ == "empty":
                    self.fehler = str(final.get("error") or "leerer Zug")
                    break

                geschichten.lage_update(self.lage, final)
                dauer_b = self._merke_bianca(final, latenz=final.get("_latenzS"),
                                             erster_ton=final.get("_ersterTonS"))
                if final.get("hangup"):
                    break
                # Anti-Stall: kommt dieselbe Maschinen-Frage vier Mal in Folge,
                # ist der Dialog festgefahren — abbrechen und klar berichten
                # (live 29.08.2026: Buchstabier-Loop verbrannte 20+ Zuege).
                if self.lage["frage"] and self.lage["frage"] == stall_frage:
                    stall_n += 1
                    if stall_n >= 3:
                        self.fehler = f"festgefahren: frage={stall_frage} kam {stall_n + 1}x in Folge"
                        break
                else:
                    stall_frage, stall_n = self.lage["frage"], 0
                if zug.get("auflegen") or "abschied" in self.lage["gemacht"]:
                    # Abschied gesprochen, Bianca hat geantwortet — auflegen.
                    break
                rest = zug.get("halbsatzRest")
                if rest:
                    # Wache hat nicht gehalten: Teil 2 trotzdem nachreichen.
                    halbsatz_rest = str(rest)
                self._warten(dauer_b + DENKPAUSE_S)
        except (httpx.HTTPError, RuntimeError) as e:
            self.fehler = f"{type(e).__name__}: {e}"
        finally:
            letzter_anruf = self._auflegen()

        bericht = {
            "id": self.story.get("id") or "",
            "start": start_zeit,
            "dauerS": round(time.perf_counter() - t_lauf, 1),
            "story": {k: v for k, v in self.story.items()},
            "zielDatum": ziel_datum(str(self.story.get("tag") or "")),
            "fehler": self.fehler,
            "zuege": self.zuege,
            "ergebnis": bewerten(self.story, self.zuege, letzter_anruf,
                                 ziel_datum(str(self.story.get("tag") or "")), self.fehler),
            "lastCall": letzter_anruf,
        }
        (self.dir / "bericht.json").write_text(
            json.dumps(bericht, ensure_ascii=False, indent=1), encoding="utf-8")
        # Nicht sofort stornieren — 2 Stunden im Kalender, dann Autoloesch.
        try:
            aufraeumen.vormerken_aus_bericht(bericht)
        except Exception as e:
            print(f"runner: autoloesch-vormerken {type(e).__name__}: {e}", flush=True)
        return bericht

    def _auflegen(self) -> dict[str, Any]:
        letzter: dict[str, Any] = {}
        try:
            if self.session_id:
                self.client.post(f"{self.basis}/api/hangup", json={"sessionId": self.session_id})
                time.sleep(1.0)  # Nacharbeit (Notiz) laeuft im Hintergrund an
                r = self.client.get(f"{self.basis}/api/last-call")
                daten = r.json() if r.status_code == 200 else {}
                anruf = daten.get("call") or {}
                if anruf.get("sessionId") == self.session_id:
                    letzter = anruf
        except httpx.HTTPError:
            pass
        finally:
            self.client.close()
        return letzter


# ------------------------------------------------------------------ Bewertung

def bewerten(story: dict, zuege: list[dict], last_call: dict, ziel_iso: str,
             fehler: str = "") -> dict[str, Any]:
    """Checks je Anliegen-Art — die Ergebnisseite zeigt sie als gruen/rot."""
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, soll: str = "", ist: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "soll": soll, "ist": ist})

    art = story.get("anliegen") or geschichten.TERMIN
    book = last_call.get("lastBook") or {}
    sammler = last_call.get("sammler") or {}

    check("kein Fehler", not fehler, "", fehler)

    if art == geschichten.TERMIN:
        gebucht = bool(book.get("booked"))
        # Leerer Kalender ist Realitaet, kein Bianca-Fehler: sagt sie
        # "keinen freien Termin" und hinterlaesst die Rueckruf-Notiz,
        # zaehlt das als korrekt behandelt.
        kein_slot = any("keinen freien termin" in (z.get("text") or "").lower()
                        for z in zuege if z.get("wer") == "bianca")
        if not gebucht and kein_slot:
            check("gebucht", bool(last_call.get("praxisNotiz")),
                  "Rueckruf-Notiz statt Buchung (kein Slot frei)",
                  str(last_call.get("praxisNotiz") or ""))
        else:
            check("gebucht", gebucht)
        slot_iso = str(book.get("slotIso") or "")
        if gebucht and slot_iso:
            # Ausweichtermin ist KEIN Fehler, wenn Bianca ehrlich gesagt
            # hat, dass am Wunschtag nichts frei ist (Kalender-Realitaet).
            voll = any("nichts frei" in (z.get("text") or "").lower()
                       or "ausgebucht" in (z.get("text") or "").lower()
                       for z in zuege if z.get("wer") == "bianca")
            am_ziel = slot_iso[:10] == ziel_iso
            check("Zieltag", am_ziel or voll, ziel_iso,
                  slot_iso[:10] + ("" if am_ziel else " (Wunschtag ausgebucht)" if voll else ""))
        erwartet = saetze.GRUENDE.get(story.get("grund") or "", (None, ""))[1] or ""
        # Das ERWARTETE ist das gebuchte Tenant-Motiv (motivName) — der
        # Sammler-grund traegt nur den Konzeptnamen ("Invisalign-Beratung"),
        # der aufs Motiv ("KFO Besprechung") gemappt wird.
        motiv_ist = str(sammler.get("motivName") or "")
        grund_ist = str(sammler.get("grund") or "")
        if erwartet:
            check("Motiv", erwartet.lower() in motiv_ist.lower()
                  or erwartet.lower() in grund_ist.lower(),
                  erwartet, motiv_ist or grund_ist)
        telefon_ist = "".join(c for c in str(sammler.get("telefon") or "") if c.isdigit())
        check("Telefon", telefon_ist.endswith(saetze.TESTNUMMER[1:]) or telefon_ist == saetze.TESTNUMMER,
              saetze.TESTNUMMER, telefon_ist)
        check("Nachname", str(sammler.get("nachname") or "").lower() == story["nachname"].lower(),
              story["nachname"], str(sammler.get("nachname") or ""))
    elif art == geschichten.ABSAGEN:
        check("abgesagt", bool((last_call.get("lastCancel") or {}).get("ok")))
    elif art == geschichten.VERSCHIEBEN:
        moved = bool((last_call.get("lastMove") or {}).get("ok")) or bool(book.get("booked"))
        check("verschoben", moved)
    elif art == geschichten.AUSKUNFT:
        vorgelesen = any("termin" in (z.get("text") or "").lower()
                         for z in zuege if z.get("wer") == "bianca" and (z.get("modus") or "") == "auskunft")
        check("Termin vorgelesen", vorgelesen or bool(sammler.get("phase")))
    else:  # Doku-Anliegen: es zaehlt die Notiz fuer die Praxis
        notiert = bool(last_call.get("lastNote")) or bool(last_call.get("praxisNotiz"))
        check("Notiz fuer die Praxis", notiert)

    # Latenz-Statistik ueber die Bianca-Zuege.
    latenzen = [z.get("latenzS") for z in zuege if z.get("wer") == "bianca" and z.get("latenzS")]
    erste_toene = [z.get("ersterTonS") for z in zuege if z.get("wer") == "bianca" and z.get("ersterTonS")]
    waechter_alle = [w.get("w") for z in zuege for w in (z.get("waechter") or [])]
    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "latenzMaxS": max(latenzen) if latenzen else 0.0,
        "latenzMittelS": round(sum(latenzen) / len(latenzen), 2) if latenzen else 0.0,
        "ersterTonMaxS": max(erste_toene) if erste_toene else 0.0,
        "waechter": sorted(set(waechter_alle)),
        "zuege": len(zuege),
    }


# ----------------------------------------------------------------------- Lauf

def lauf(stories: list[dict[str, Any]], *, basis: str = BASIS, echtzeit: bool = True,
         mithoeren: bool = False, tenant: str = "", lauf_id: str = "") -> dict[str, Any]:
    """Mehrere Stories nacheinander; schreibt berichte/<laufId>/lauf.json."""
    lauf_id = lauf_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    lauf_dir = BERICHTE_DIR / lauf_id
    lauf_dir.mkdir(parents=True, exist_ok=True)
    berichte: list[dict[str, Any]] = []
    for story in stories:
        print(f"runner: Story {story.get('id')} startet", flush=True)
        anruf = Anruf(story, basis=basis, lauf_dir=lauf_dir,
                      echtzeit=echtzeit, mithoeren=mithoeren, tenant=tenant)
        b = anruf.fuehren()
        erg = b.get("ergebnis") or {}
        print(f"runner: Story {story.get('id')} {'GRUEN' if erg.get('ok') else 'ROT'} "
              f"(Zuege {erg.get('zuege')}, Latenz max {erg.get('latenzMaxS')}s)", flush=True)
        berichte.append({
            "id": b.get("id"), "ok": bool(erg.get("ok")),
            "checks": erg.get("checks"), "latenzMaxS": erg.get("latenzMaxS"),
            "fehler": b.get("fehler") or "", "pfad": f"{b.get('id')}/bericht.json",
        })
        zwischen = {"laufId": lauf_id, "gestartet": datetime.now().isoformat(timespec="seconds"),
                    "stories": berichte}
        (lauf_dir / "lauf.json").write_text(json.dumps(zwischen, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        time.sleep(2.0)  # Sitzungs-Nacharbeit atmen lassen
    gruen = sum(1 for b in berichte if b["ok"])
    print(f"runner: Lauf {lauf_id} fertig — {gruen}/{len(berichte)} gruen", flush=True)
    return {"laufId": lauf_id, "gruen": gruen, "gesamt": len(berichte), "stories": berichte}


def main() -> None:
    p = argparse.ArgumentParser(description="Baukasten-Story gegen den Bianca-Dienst fahren")
    p.add_argument("--anzahl", type=int, default=1, help="so viele Automatik-Stories")
    p.add_argument("--ab", type=int, default=1, help="Story-Nummer, ab der gezaehlt wird")
    p.add_argument("--tag", default="Mittwoch", help="Wunschtag (naechste Woche)")
    p.add_argument("--basis", default=BASIS)
    p.add_argument("--tenant", default="")
    p.add_argument("--schnell", action="store_true", help="ohne Echtzeit-Taktung")
    p.add_argument("--mithoeren", action="store_true", help="Audio lokal abspielen")
    p.add_argument("--telefon", action="store_true",
                   help="Anrufer-Audio auf 8 kHz / 8 bit (Telefonqualitaet)")
    a = p.parse_args()
    stories = [geschichten.automatik(nr, tag=a.tag) for nr in range(a.ab, a.ab + a.anzahl)]
    if a.telefon:
        for s in stories:
            s["telefonQualitaet"] = True
    ergebnis = lauf(stories, basis=a.basis, echtzeit=not a.schnell,
                    mithoeren=a.mithoeren, tenant=a.tenant)
    sys.exit(0 if ergebnis["gruen"] == ergebnis["gesamt"] else 1)


if __name__ == "__main__":
    main()
