"""Belastungstest: vollstaendige Audio-Gespraeche ueber alle Mandanten.

Vor der parallelen Welle laeuft je Mandant ein einzelnes Referenzgespraech.
Danach fuehren zufaellige Personas echte mehrzuegige Dialoge ueber
``/api/listen`` (TTS -> Telefonqualitaet -> STT -> Bianca -> TTS-Stream).
Kalenderbuchungen werden an der letzten Bestaetigung bewusst abgebrochen.
"""

from __future__ import annotations

import json
import queue
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from kern import tenants, zimmer_map
from tests.baukasten import geschichten, klang, saetze

MAX_PARALLEL = 18
MAX_DIALOG_ZUEGE = 28
AUDIO_GAP_S = 0.55
Fortschritt = Callable[[dict[str, Any]], None]

KUNDEN: tuple[dict[str, str], ...] = (
    {"id": "meddent", "kurz": "Medical Center", "farbe": "#4da3ff"},
    {"id": "thaler", "kurz": "Thaler", "farbe": "#37c978"},
    {"id": "blessing", "kurz": "Blessing", "farbe": "#d862c8"},
)

# Einzelgespraech ohne Last — Zielwerte der Produktionsstrecke.
NORM = {
    "startS": 1.20,
    "ersterTonS": 0.80,
    "antwortS": 2.00,
    "lueckeS": 1.50,
    "sttS": 0.45,
    "llmS": 1.20,
    "ttsS": 1.20,
    "audioS": 1.20,
}

METRIKEN = ("start", "stt", "llm", "tts", "ersterTon", "antwort", "audio")
METRIK_LABEL = {
    "start": "Gesprächsstart",
    "stt": "STT",
    "llm": "Dialog/LLM",
    "tts": "TTS",
    "ersterTon": "Erster Ton",
    "antwort": "Gesamtantwort",
    "audio": "Audio-Auslieferung",
}


def _tenant_katalog(tenant_id: str) -> tuple[list[str], list[str]]:
    tenant = tenants.laden(tenant_id)
    behandler = [
        str(c.get("name") or "").strip()
        for c in tenants.behandler_kalender(tenant)
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    ]
    motive = list(tenant.get("visitMotives") or [])
    if zimmer_map.aktiv(tenant):
        motive = zimmer_map.buchbarer_katalog(tenant, motive)
    gruende = [
        str(m.get("name") or "").strip()
        for m in motive
        if isinstance(m, dict) and str(m.get("name") or "").strip()
    ]
    return behandler or list(geschichten.BEHANDLER), gruende or list(saetze.GRUENDE)


def story_fuer_sitz(sitz: dict[str, Any], *, baseline: bool = False) -> dict[str, Any]:
    """Reproduzierbar zufaellige, mandantenscharfe Vollgeschichte."""
    tenant = str(sitz.get("tenant") or "")
    nr = int(sitz.get("nr") or 1)
    seed = int(sitz.get("seed") or (nr * 7919 + sum(map(ord, tenant)) * 101))
    if baseline:
        seed = 900_001 + sum(map(ord, tenant)) * 17
    rnd = random.Random(seed)
    behandler, gruende = _tenant_katalog(tenant)
    story = geschichten.automatik(
        nr, tag=rnd.choice(("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag")),
        seed=seed, tenant=tenant, behandler=behandler, gruende=gruende,
    )
    # Mehrheit: kompletter Termin-Dialog bis direkt vor dem Write. Dazu
    # Dokument-/Praxisanliegen fuer unterschiedliche Flow-Laengen.
    art = str(sitz.get("anliegen") or "")
    if not art:
        art = rnd.choices(
            [geschichten.TERMIN, *geschichten.DOKU_ARTEN],
            weights=[70, *([30 / max(1, len(geschichten.DOKU_ARTEN))]
                           * len(geschichten.DOKU_ARTEN))],
            k=1,
        )[0]
    if art in geschichten.DOKU_ARTEN:
        story["anliegen"] = art
        story["id"] = f"last-{nr:02d}-{tenant}-{art}"
        story["abschweifer"] = story["abschweifer"][:1]
        story["zwischenfragePreis"] = False
        story["halbsatz"] = False
    else:
        story["id"] = f"last-{nr:02d}-{tenant}-{story['grund']}"
    if baseline:
        # Die Referenz misst Infrastruktur, nicht zufällige Härtefälle. Ein
        # stabil verständlicher Sprecher/Name hält den Einzelvergleich nutzbar.
        story.update({
            "stimme": "markus",
            "vorname": "Markus",
            "nachname": "Müller",
            "halbsatz": False,
            "abschweifer": [],
            "zwischenfragePreis": False,
            "readbackFehler": False,
            "slotAnnahme": 1,
            "pzr": False,
        })
    story["lasttestKeinSchreiben"] = True
    story["lasttestBaseline"] = baseline
    return story


def _kappe(n: int, oben: int) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = 1
    return max(1, min(oben, v))


def kunde_von(tenant_id: str) -> dict[str, str]:
    tid = str(tenant_id or "")
    for k in KUNDEN:
        if k["id"] == tid:
            return dict(k)
    return {"id": tid or "?", "kurz": tid or "?", "farbe": "#8b96a5"}


def verteile(n: int, kunden: list[dict[str, str]] | tuple[dict[str, str], ...] | None = None) -> dict[str, Any]:
    n = _kappe(n, MAX_PARALLEL)
    pool = [dict(k) for k in (kunden or KUNDEN) if str(k.get("id") or "").strip()]
    if not pool:
        pool = [dict(k) for k in KUNDEN]
    counts = {k["id"]: 0 for k in pool}
    zufall = random.SystemRandom()
    zuordnung: list[dict[str, str]] = []
    # Bei genug Plaetzen kommt jede Praxis mindestens einmal vor. Die
    # restlichen Gespraeche werden wirklich zufaellig verteilt.
    if n >= len(pool):
        zuordnung.extend(pool)
    while len(zuordnung) < n:
        zuordnung.append(zufall.choice(pool))
    zufall.shuffle(zuordnung)
    sitze: list[dict[str, Any]] = []
    for i in range(n):
        k = zuordnung[i]
        counts[k["id"]] += 1
        seed = zufall.randrange(1, 2_000_000_000)
        art = zufall.choices(
            [geschichten.TERMIN, *geschichten.DOKU_ARTEN],
            weights=[70, *([30 / max(1, len(geschichten.DOKU_ARTEN))]
                           * len(geschichten.DOKU_ARTEN))],
            k=1,
        )[0]
        sitze.append({
            "nr": i + 1,
            "tenant": k["id"],
            "kurz": k["kurz"],
            "farbe": k["farbe"],
            "seed": seed,
            "anliegen": art,
        })
    return {
        "n": n,
        "sitze": sitze,
        "counts": counts,
        "kunden": [{**dict(k), "n": counts[k["id"]]} for k in pool],
    }


def latenz_offset(wert: float, norm: float) -> dict[str, float]:
    w = float(wert or 0)
    nrm = float(norm or 0)
    off = round(w - nrm, 2) if nrm else 0.0
    pct = round(((w / nrm) - 1.0) * 100.0, 1) if nrm else 0.0
    return {"wert": round(w, 2), "norm": nrm, "offsetS": off, "offsetPct": pct}


def dropouts_von_zug(*, tS: float, ersterTonS: float, antwortS: float,
                     leer: bool, nr: int, tenant: str,
                     kurz: str = "", farbe: str = "") -> list[dict[str, Any]]:
    k = kunde_von(tenant)
    if kurz:
        k["kurz"] = kurz
    if farbe:
        k["farbe"] = farbe
    out: list[dict[str, Any]] = []
    if leer or antwortS <= 0:
        out.append({
            "tS": round(tS, 2),
            "dauerS": round(max(antwortS, ersterTonS, 1.0), 2),
            "art": "ausfall",
            "nr": nr,
            "tenant": k["id"],
            "kurz": k["kurz"],
            "farbe": k["farbe"],
        })
        return out
    if ersterTonS > NORM["ersterTonS"] * 1.6:
        out.append({
            "tS": round(tS, 2),
            "dauerS": round(max(0.05, ersterTonS - NORM["ersterTonS"]), 2),
            "art": "ersterTon",
            "nr": nr,
            "tenant": k["id"],
            "kurz": k["kurz"],
            "farbe": k["farbe"],
        })
    luecke = antwortS - ersterTonS
    if luecke > NORM["lueckeS"] * 1.5:
        out.append({
            "tS": round(tS + ersterTonS, 2),
            "dauerS": round(luecke, 2),
            "art": "luecke",
            "nr": nr,
            "tenant": k["id"],
            "kurz": k["kurz"],
            "farbe": k["farbe"],
        })
    return out


def _perzentil(werte: list[float], p: float) -> float:
    if not werte:
        return 0.0
    s = sorted(werte)
    i = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return s[i]


def _abs_url(basis: str, url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return basis.rstrip("/") + "/" + u.lstrip("/")


def _audio_messen(basis: str, url: str) -> dict[str, Any]:
    """Progressiven Antwortstrom komplett ziehen und echte Lieferluecken messen."""
    ziel = _abs_url(basis, url)
    if not ziel:
        return {"ok": False, "bytes": 0, "dauerS": 0.0, "firstByteS": 0.0,
                "maxGapS": 0.0, "gaps": [], "error": "audioUrl fehlt"}
    t0 = time.perf_counter()
    first = 0.0
    vorher = 0.0
    groesse = 0
    gaps: list[float] = []
    try:
        with httpx.Client(timeout=40.0) as client:
            with client.stream("GET", ziel) as r:
                r.raise_for_status()
                for teil in r.iter_bytes(4096):
                    if not teil:
                        continue
                    jetzt = time.perf_counter()
                    if not first:
                        first = jetzt
                    elif vorher:
                        gap = jetzt - vorher
                        if gap >= AUDIO_GAP_S:
                            gaps.append(round(gap, 3))
                    vorher = jetzt
                    groesse += len(teil)
        ende = time.perf_counter()
        return {
            "ok": groesse > 44,
            "bytes": groesse,
            "dauerS": round(ende - t0, 3),
            "firstByteS": round((first - t0) if first else 0.0, 3),
            "maxGapS": max(gaps) if gaps else 0.0,
            "gaps": gaps,
            "error": "" if groesse > 44 else "leeres Audio",
        }
    except Exception as exc:
        return {
            "ok": False, "bytes": groesse,
            "dauerS": round(time.perf_counter() - t0, 3),
            "firstByteS": round((first - t0) if first else 0.0, 3),
            "maxGapS": max(gaps) if gaps else 0.0,
            "gaps": gaps,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _text_von(ev: dict[str, Any]) -> str:
    for k in ("text", "textIn"):
        t = " ".join(str(ev.get(k) or "").split())
        if t:
            return t
    return ""


def _listen(client: httpx.Client, basis: str, sid: str, wav: Path,
            *, zieh: bool) -> dict[str, Any]:
    t0 = time.perf_counter()
    erster = 0.0
    gehoert = ""
    stt_info: dict[str, Any] = {}
    final: dict[str, Any] = {}
    letzter_ton = 0.0
    luecken: list[float] = []
    audio_messungen: list[dict[str, Any]] = []
    audio_queue: queue.Queue[tuple[str, str] | None] = queue.Queue()

    def audio_start(url: str, art: str) -> None:
        if not zieh or not url:
            return
        audio_queue.put((url, art))

    def audio_arbeit() -> None:
        while True:
            posten = audio_queue.get()
            if posten is None:
                return
            url, art = posten
            arbeits_start = time.perf_counter() - t0
            messung = _audio_messen(basis, url)
            messung["art"] = art
            messung["tonBeiS"] = round(
                arbeits_start + float(messung.get("firstByteS") or 0), 3)
            audio_messungen.append(messung)

    audio_thread = threading.Thread(target=audio_arbeit, daemon=True)
    if zieh:
        audio_thread.start()

    with wav.open("rb") as f:
        with client.stream(
            "POST", f"{basis}/api/listen",
            data={"sessionId": sid, "text": "", "bargeUrl": "", "bargeMs": 0},
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
                jetzt = time.perf_counter() - t0
                if typ == "transcript":
                    gehoert = _text_von(ev) or gehoert
                    stt_info = dict(ev.get("stt") or {})
                elif typ == "warte":
                    # Halbsatz-/Diktat-Wartezüge tragen den echten Decode im
                    # finalen textIn; Bianca spricht dabei bewusst nicht.
                    gehoert = _text_von(ev) or gehoert
                    stt_info = dict(ev.get("stt") or stt_info)
                if typ == "filler":
                    if not erster:
                        erster = round(jetzt, 2)
                    if letzter_ton and (jetzt - letzter_ton) > NORM["lueckeS"]:
                        luecken.append(round(jetzt - letzter_ton, 2))
                    letzter_ton = jetzt
                    audio_start(str(ev.get("audioUrl") or ""), "fueller")
                if typ in ("reply", "warte", "empty"):
                    final = ev
                    break
    final["_latenzS"] = round(time.perf_counter() - t0, 2)
    final["_ersterTonS"] = erster or final["_latenzS"]
    # Niemals Biancas Antwort als vermeintliches STT-Ergebnis einsetzen:
    # der Lasttest muss einen leeren Audio-Decode sichtbar rot markieren.
    final["_gehoert"] = gehoert
    final["_stt"] = stt_info
    final["_luecken"] = luecken
    audio_start(str(final.get("audioUrl") or ""), "antwort")
    if zieh:
        audio_queue.put(None)
        audio_thread.join(timeout=130)
        if audio_thread.is_alive():
            audio_messungen.append({
                "ok": False, "bytes": 0, "dauerS": 130.0,
                "firstByteS": 0.0, "maxGapS": 130.0, "gaps": [],
                "error": "Audio-Warteschlange nach 130 s nicht beendet",
                "art": "warteschlange",
            })
    echte_toene = [
        float(m.get("tonBeiS") or 0) for m in audio_messungen
        if m.get("ok") and float(m.get("tonBeiS") or 0) > 0
    ]
    if echte_toene:
        final["_ersterTonS"] = round(min(echte_toene), 2)
    final["_audio"] = list(audio_messungen)
    return final


class _Sammler:
    def __init__(self, plan: dict[str, Any], fortschritt: Fortschritt | None):
        self.plan = plan
        self.fortschritt = fortschritt
        self.lock = threading.Lock()
        self.events: list[dict[str, Any]] = []
        self.blasen: list[dict[str, Any]] = []
        self.transkript: list[dict[str, Any]] = []
        self.latenz: list[dict[str, Any]] = []
        self.fertig = 0
        self.baseline_fertig = 0
        self.baseline: dict[str, Any] = {}
        self.phase = "start"
        self._last_meld = 0.0

    def _snap(self, phase: str) -> dict[str, Any]:
        return {
            "phase": phase,
            "n": self.plan["n"],
            "fertig": self.fertig,
            "baselineFertig": self.baseline_fertig,
            "baselineGesamt": sum(
                1 for k in (self.plan.get("kunden") or []) if int(k.get("n") or 0) > 0
            ),
            "baseline": dict(self.baseline),
            "plan": self.plan,
            "norm": dict(NORM),
            "events": list(self.events[-240:]),
            "blasen": list(self.blasen),
            "transkript": list(self.transkript[-160:]),
            "latenz": list(self.latenz[-240:]),
            "kpis": kpis_von(self.latenz, self.blasen, self.fertig, self.plan["n"]),
            "statistik": statistik_von(self.latenz, self.blasen, self.events),
            "vergleich": vergleich_von(self.latenz),
        }

    def meld(self, phase: str = "lauf") -> None:
        if phase != "lauf":
            self.phase = phase
        phase = self.phase
        self._last_meld = time.monotonic()
        if self.fortschritt:
            self.fortschritt(self._snap(phase))

    def _tipp(self) -> None:
        if time.monotonic() - self._last_meld >= 0.25:
            self.meld("lauf")

    def zeile(self, **kw: Any) -> None:
        with self.lock:
            self.transkript.append(kw)
            self.events.append({"art": "text", **kw})
        self._tipp()

    def punkt(self, **kw: Any) -> None:
        with self.lock:
            self.latenz.append(kw)
        self._tipp()

    def blase(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        with self.lock:
            self.blasen.extend(items)
        self._tipp()

    def ende_sitzung(self) -> None:
        with self.lock:
            self.fertig += 1
        self.meld("last")

    def ende_baseline(self, tenant: str, ergebnis: dict[str, Any]) -> None:
        with self.lock:
            self.baseline_fertig += 1
            self.baseline[tenant] = ergebnis
        self.meld("baseline")


def kpis_von(latenz: list[dict[str, Any]], blasen: list[dict[str, Any]],
             fertig: int, n: int) -> dict[str, Any]:
    last = [p for p in latenz if p.get("phase", "last") == "last"]
    toene = [float(p["wert"]) for p in last if p.get("metrik") == "ersterTon"]
    antw = [float(p["wert"]) for p in last if p.get("metrik") == "antwort"]
    starts = [float(p["wert"]) for p in last if p.get("metrik") == "start"]
    offs = [float(p.get("offsetPct") or 0) for p in latenz if p.get("metrik") in
            ("ersterTon", "antwort", "start") and p.get("phase", "last") == "last"]
    echte_dropouts = [
        b for b in blasen
        if b.get("phase", "last") == "last"
        and b.get("art") in {"ausfall", "stt_leer", "audio_ausfall", "audio_luecke", "audio_fehlt"}
    ]
    return {
        "fertig": fertig,
        "n": n,
        "dropouts": len(echte_dropouts),
        "startP50": _perzentil(starts, 50),
        "ersterTonP50": _perzentil(toene, 50),
        "ersterTonP95": _perzentil(toene, 95),
        "antwortP50": _perzentil(antw, 50),
        "antwortP95": _perzentil(antw, 95),
        "offsetPct": round(sum(offs) / len(offs), 1) if offs else 0.0,
        "offsetP95": _perzentil(offs, 95),
    }


def _messwert_stat(werte: list[float]) -> dict[str, float | int]:
    return {
        "n": len(werte),
        "mittel": round(sum(werte) / len(werte), 3) if werte else 0.0,
        "p50": round(_perzentil(werte, 50), 3),
        "p95": round(_perzentil(werte, 95), 3),
        "max": round(max(werte), 3) if werte else 0.0,
    }


def _stat_block(latenz: list[dict[str, Any]], blasen: list[dict[str, Any]],
                *, phase: str, tenant: str = "") -> dict[str, Any]:
    punkte = [
        p for p in latenz
        if p.get("phase", "last") == phase
        and (not tenant or p.get("tenant") == tenant)
    ]
    stoer = [
        b for b in blasen
        if b.get("phase", "last") == phase
        and (not tenant or b.get("tenant") == tenant)
    ]
    gespraeche = {(p.get("tenant"), p.get("nr")) for p in punkte
                  if p.get("metrik") == "start"}
    turns = sum(1 for p in punkte if p.get("metrik") == "antwort")
    echte_dropouts = [
        b for b in stoer
        if b.get("art") in {"ausfall", "stt_leer", "audio_ausfall", "audio_luecke", "audio_fehlt"}
    ]
    stufen: list[dict[str, Any]] = []
    for name in sorted({str(p.get("stufe") or "") for p in punkte if p.get("stufe")}):
        teil = [p for p in punkte if str(p.get("stufe") or "") == name]
        stufen.append({
            "stufe": name,
            "turns": sum(1 for p in teil if p.get("metrik") == "antwort"),
            "stt": _messwert_stat([
                float(p.get("wert") or 0) for p in teil if p.get("metrik") == "stt"
            ]),
            "antwort": _messwert_stat([
                float(p.get("wert") or 0) for p in teil if p.get("metrik") == "antwort"
            ]),
            "ersterTon": _messwert_stat([
                float(p.get("wert") or 0) for p in teil if p.get("metrik") == "ersterTon"
            ]),
        })
    stufen.sort(key=lambda x: float((x["antwort"] or {}).get("p95") or 0), reverse=True)
    stt_engines = {}
    for engine in sorted({
        str(p.get("sttWinner") or "") for p in punkte
        if p.get("metrik") == "stt" and p.get("sttWinner")
    }):
        stt_engines[engine] = _messwert_stat([
            float(p.get("wert") or 0) for p in punkte
            if p.get("metrik") == "stt" and str(p.get("sttWinner") or "") == engine
        ])
    return {
        "gespraeche": len(gespraeche),
        "turns": turns,
        "dropouts": len(echte_dropouts),
        "warnungen": len(stoer) - len(echte_dropouts),
        "metriken": {
            m: _messwert_stat([
                float(p.get("wert") or 0) for p in punkte if p.get("metrik") == m
            ])
            for m in METRIKEN
        },
        "stufen": stufen,
        "sttEngines": stt_engines,
    }


def statistik_von(latenz: list[dict[str, Any]], blasen: list[dict[str, Any]],
                  events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    tenant_ids = sorted({
        str(p.get("tenant") or "") for p in latenz if p.get("tenant")
    })
    out: dict[str, Any] = {}
    for phase in ("baseline", "last"):
        out[phase] = {
            "gesamt": _stat_block(latenz, blasen, phase=phase),
            "mandanten": {
                tid: _stat_block(latenz, blasen, phase=phase, tenant=tid)
                for tid in tenant_ids
            },
        }
    return out


def _vergleich_rows(basis: dict[str, Any], last: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for m in METRIKEN:
        b = (basis.get("metriken") or {}).get(m) or {}
        last_m = (last.get("metriken") or {}).get(m) or {}
        bp50, lp50 = float(b.get("p50") or 0), float(last_m.get("p50") or 0)
        bp95, lp95 = float(b.get("p95") or 0), float(last_m.get("p95") or 0)
        rows.append({
            "metrik": m,
            "label": METRIK_LABEL.get(m, m),
            "einzelP50": bp50,
            "einzelP95": bp95,
            "lastP50": lp50,
            "lastP95": lp95,
            "deltaP50": round(lp50 - bp50, 3),
            "deltaP95": round(lp95 - bp95, 3),
            "deltaPct": round(((lp95 / bp95) - 1) * 100, 1) if bp95 else 0.0,
        })
    return rows


def vergleich_von(latenz: list[dict[str, Any]]) -> dict[str, Any]:
    stat = statistik_von(latenz, [])
    basis, last = stat["baseline"], stat["last"]
    tids = sorted(set((basis.get("mandanten") or {}))
                  | set((last.get("mandanten") or {})))
    return {
        "gesamt": _vergleich_rows(basis["gesamt"], last["gesamt"]),
        "mandanten": {
            tid: _vergleich_rows(
                (basis.get("mandanten") or {}).get(tid) or {},
                (last.get("mandanten") or {}).get(tid) or {},
            )
            for tid in tids
        },
    }


def _norm_metrik(metrik: str) -> float:
    return float({
        "start": NORM["startS"],
        "stt": NORM["sttS"],
        "llm": NORM["llmS"],
        "tts": NORM["ttsS"],
        "ersterTon": NORM["ersterTonS"],
        "antwort": NORM["antwortS"],
        "audio": NORM["audioS"],
    }.get(metrik, 1.0))


def _wav_fuer_zug(story: dict[str, Any], text: str, leitung: dict | None) -> Path:
    pfad = klang.audio_holen(str(story.get("stimme") or klang.DEMO_STIMME), text)
    return klang.telefon_datei(pfad, leitung=leitung or klang.LEITUNG_DEFAULT)


def _warte_fortsetzung(zug: dict[str, Any]) -> str:
    rest = " ".join(str(zug.get("halbsatzRest") or "").split())
    if rest:
        return rest
    baustein = str(zug.get("baustein") or "")
    if baustein in {"buchstabieren", "telefon", "name", "vorname", "nachname"}:
        return "Fertig."
    return ""


def _eine(sitz: dict[str, Any], *, basis: str, story: dict[str, Any],
          start_tor: threading.Barrier | None, welle_t0: float,
          sam: _Sammler, phase: str = "last",
          leitung: dict | None = None,
          normen: dict[str, float] | None = None) -> dict[str, Any]:
    nr = int(sitz["nr"])
    tenant = str(sitz["tenant"])
    k = {
        "id": tenant,
        "kurz": str(sitz.get("kurz") or tenant),
        "farbe": str(sitz.get("farbe") or "#8b96a5"),
    }
    out: dict[str, Any] = {
        "nr": nr, "ok": False, "startS": 0.0, "ersterTonS": 0.0,
        "antwortS": 0.0, "fehler": "", "sessionId": "",
        "tenant": tenant, "kurz": k["kurz"], "farbe": k["farbe"],
        "phase": phase, "story": story.get("id") or "",
        "anliegen": story.get("anliegen") or "", "zuege": [],
    }
    if start_tor is not None:
        try:
            start_tor.wait(timeout=90)
        except threading.BrokenBarrierError:
            out["fehler"] = "Starttor abgelaufen"
            if phase == "last":
                sam.ende_sitzung()
            return out
    t0 = time.perf_counter()
    sid = ""
    lage = geschichten.lage_neu()
    halbsatz_rest = ""
    toene: list[float] = []
    antworten: list[float] = []
    turn_nr = 0
    stufe = "start"
    stt_winner = ""
    natuerlich_beendet = False

    def punkt(metrik: str, wert: float, t_abs: float, **extra: Any) -> None:
        norm = float((normen or {}).get(metrik) or _norm_metrik(metrik))
        sam.punkt(
            tS=round(t_abs, 2), phase=phase, metrik=metrik, nr=nr,
            tenant=tenant, kurz=k["kurz"], farbe=k["farbe"],
            turn=turn_nr, stufe=stufe, sttWinner=stt_winner,
            **latenz_offset(wert, norm), **extra,
        )

    def audio_stoerungen(messungen: list[dict[str, Any]], t_abs: float) -> list[dict[str, Any]]:
        drops: list[dict[str, Any]] = []
        for m in messungen:
            if not m.get("ok"):
                drops.append({
                    "tS": round(t_abs, 2), "dauerS": float(m.get("dauerS") or 1),
                    "art": "audio_ausfall", "detail": m.get("error") or "",
                    "nr": nr, "tenant": tenant, "kurz": k["kurz"],
                    "farbe": k["farbe"], "phase": phase, "turn": turn_nr,
                })
            for gap in m.get("gaps") or []:
                drops.append({
                    "tS": round(t_abs, 2), "dauerS": float(gap),
                    "art": "audio_luecke", "detail": m.get("art") or "",
                    "nr": nr, "tenant": tenant, "kurz": k["kurz"],
                    "farbe": k["farbe"], "phase": phase, "turn": turn_nr,
                })
        return drops

    try:
        with httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0)) as c:
            r = c.post(f"{basis}/api/start", json={
                "tenant": tenant, "test": True,
                "testNoWrite": True,
                "testName": f"Last {k['kurz']} {nr} {story.get('anliegen')}",
            })
            r.raise_for_status()
            d = r.json()
            sid = str(d.get("sessionId") or "")
            if not sid:
                raise RuntimeError("kein sessionId")
            out["sessionId"] = sid
            start_s = round(time.perf_counter() - t0, 2)
            out["startS"] = start_s
            t_abs = round(time.perf_counter() - welle_t0, 2)
            punkt("start", start_s, t_abs)
            sam.zeile(tS=t_abs, phase=phase, nr=nr, tenant=tenant, kurz=k["kurz"],
                      farbe=k["farbe"], wer="bianca", text=_text_von(d) or "Begrüßung")
            start_audio = _audio_messen(basis, str(d.get("audioUrl") or ""))
            punkt("audio", float(start_audio.get("dauerS") or 0), t_abs,
                  audioArt="begruessung")
            sam.blase(audio_stoerungen([start_audio], t_abs))

            for _ in range(MAX_DIALOG_ZUEGE):
                if halbsatz_rest:
                    zug = {"text": halbsatz_rest, "baustein": "halbsatz_rest"}
                    halbsatz_rest = ""
                else:
                    zug = geschichten.naechster_baustein(story, lage)
                if zug.get("auflegen") and not str(zug.get("text") or "").strip():
                    natuerlich_beendet = True
                    break
                text = " ".join(str(zug.get("text") or "").split())
                if not text:
                    break
                turn_nr += 1
                stufe = str(zug.get("baustein") or lage.get("frage") or "dialog")
                wav = _wav_fuer_zug(story, text, leitung)
                t_zug = time.perf_counter() - welle_t0
                ev = _listen(c, basis, sid, wav, zieh=True)
                et = float(ev.get("_ersterTonS") or 0)
                ant = float(ev.get("_latenzS") or 0)
                leer = str(ev.get("type") or "") == "empty"
                wartet = str(ev.get("type") or "") == "warte"
                stt_daten = ev.get("_stt") if isinstance(ev.get("_stt"), dict) else {}
                stt_winner = str(stt_daten.get("winner") or stt_daten.get("gewinner") or "")
                if not wartet:
                    toene.append(et)
                antworten.append(ant)
                if not wartet:
                    punkt("ersterTon", et, t_zug + et)
                punkt("antwort", ant, t_zug + ant)
                timings = ev.get("timings") if isinstance(ev.get("timings"), dict) else {}
                for metrik, key in (("stt", "stt"), ("llm", "llm"), ("tts", "tts")):
                    if key in timings:
                        punkt(metrik, float(timings.get(key) or 0), t_zug + ant)
                audio_m = list(ev.get("_audio") or [])
                if audio_m:
                    punkt("audio", sum(float(x.get("dauerS") or 0) for x in audio_m),
                          t_zug + ant, audioArt="zug")
                gehoert = str(ev.get("_gehoert") or "")
                if gehoert:
                    sam.zeile(tS=round(t_zug, 2), phase=phase, nr=nr, tenant=tenant,
                              kurz=k["kurz"], farbe=k["farbe"],
                              wer="anrufer", text=gehoert, soll=text,
                              baustein=zug.get("baustein") or "",
                              stt=ev.get("_stt") or {})
                mund = "" if wartet else _text_von(ev)
                if mund:
                    sam.zeile(tS=round(t_zug + ant, 2), phase=phase, nr=nr, tenant=tenant,
                              kurz=k["kurz"], farbe=k["farbe"],
                              wer="bianca", text=mund)
                drops = [] if wartet else dropouts_von_zug(
                    tS=t_zug, ersterTonS=et, antwortS=ant, leer=leer,
                    nr=nr, tenant=tenant, kurz=k["kurz"], farbe=k["farbe"])
                for drop in drops:
                    drop["phase"] = phase
                    drop["turn"] = turn_nr
                if not gehoert:
                    drops.append({
                        "tS": round(t_zug + ant, 2), "dauerS": ant or 1.0,
                        "art": "stt_leer", "detail": "Audio ergab kein Transkript",
                        "nr": nr, "tenant": tenant, "kurz": k["kurz"],
                        "farbe": k["farbe"], "phase": phase, "turn": turn_nr,
                    })
                for luecke in ev.get("_luecken") or []:
                    drops.append({
                        "tS": round(t_zug + et, 2), "dauerS": float(luecke),
                        "art": "luecke", "nr": nr, "tenant": tenant,
                        "kurz": k["kurz"], "farbe": k["farbe"],
                        "phase": phase, "turn": turn_nr,
                    })
                drops.extend(audio_stoerungen(audio_m, t_zug + ant))
                if mund and not audio_m:
                    drops.append({
                        "tS": round(t_zug + ant, 2), "dauerS": 1.0,
                        "art": "audio_fehlt", "nr": nr, "tenant": tenant,
                        "kurz": k["kurz"], "farbe": k["farbe"],
                        "phase": phase, "turn": turn_nr,
                    })
                sam.blase(drops)
                out["zuege"].append({
                    "ersterTonS": et, "antwortS": ant, "leer": leer,
                    "text": mund, "gehoert": gehoert, "warte": wartet,
                    "soll": text, "baustein": zug.get("baustein") or "",
                    "timings": timings, "audio": audio_m,
                    "stt": ev.get("_stt") or {},
                })
                if leer:
                    raise RuntimeError(str(ev.get("error") or "leerer Zug"))
                if not gehoert:
                    raise RuntimeError("Audio ergab kein STT-Transkript")
                if wartet:
                    halbsatz_rest = _warte_fortsetzung(zug)
                    if not halbsatz_rest:
                        raise RuntimeError(
                            f"Bianca wartet ohne passende Fortsetzung ({stufe})")
                    continue
                geschichten.lage_update(lage, ev)
                if ev.get("hangup") or zug.get("auflegen"):
                    natuerlich_beendet = True
                    break
                rest = zug.get("halbsatzRest")
                if rest:
                    halbsatz_rest = str(rest)
            if not natuerlich_beendet:
                raise RuntimeError(
                    f"Dialog fand nach {MAX_DIALOG_ZUEGE} Zügen keinen Abschluss")
            out["ersterTonS"] = max(toene) if toene else 0.0
            out["antwortS"] = max(antworten) if antworten else 0.0
            out["turns"] = len(out["zuege"])
            out["ok"] = True
    except Exception as e:
        out["fehler"] = f"{type(e).__name__}: {e}"
        sam.zeile(tS=round(time.perf_counter() - welle_t0, 2), nr=nr,
                  tenant=tenant, kurz=k["kurz"], farbe=k["farbe"],
                  phase=phase, wer="system", text=out["fehler"])
        fehler_drop = dropouts_von_zug(
            tS=round(time.perf_counter() - welle_t0, 2),
            ersterTonS=0, antwortS=0, leer=True, nr=nr, tenant=tenant,
            kurz=k["kurz"], farbe=k["farbe"])
        for drop in fehler_drop:
            drop["phase"] = phase
            drop["turn"] = turn_nr
        sam.blase(fehler_drop)
    finally:
        if sid:
            try:
                httpx.post(f"{basis}/api/hangup", json={"sessionId": sid}, timeout=15)
            except httpx.HTTPError:
                pass
    if phase == "last":
        sam.ende_sitzung()
    return out


def zusammenfassung(laeufe: list[dict[str, Any]], *, n: int, sekunden: float,
                    plan: dict[str, Any] | None = None,
                    blasen: list[dict[str, Any]] | None = None,
                    transkript: list[dict[str, Any]] | None = None,
                    latenz: list[dict[str, Any]] | None = None,
                    baseline: dict[str, Any] | None = None,
                    gesamt_sekunden: float | None = None) -> dict[str, Any]:
    ok = [x for x in laeufe if x.get("ok")]
    fehl = [x for x in laeufe if not x.get("ok")]
    toene = [float(x.get("ersterTonS") or 0) for x in ok]
    antw = [float(x.get("antwortS") or 0) for x in ok]
    starts = [float(x.get("startS") or 0) for x in ok]
    plan = plan or verteile(n)
    lat = list(latenz or [])
    bla = list(blasen or [])
    stat = statistik_von(lat, bla, list(transkript or []))
    vergleich = vergleich_von(lat)
    return {
        "n": n,
        "gehalten": len(ok),
        "fehler": len(fehl),
        "dauerS": round(sekunden, 2),
        "gesamtDauerS": round(gesamt_sekunden if gesamt_sekunden is not None else sekunden, 2),
        "turns": sum(len(x.get("zuege") or []) for x in laeufe),
        "startP50": _perzentil(starts, 50),
        "startP95": _perzentil(starts, 95),
        "ersterTonP50": _perzentil(toene, 50),
        "ersterTonP95": _perzentil(toene, 95),
        "antwortP50": _perzentil(antw, 50),
        "antwortP95": _perzentil(antw, 95),
        "laeufe": laeufe,
        "plan": plan,
        "norm": dict(NORM),
        "blasen": bla,
        "transkript": list(transkript or []),
        "latenz": lat,
        "kpis": kpis_von(lat, bla, len(laeufe), n),
        "baseline": dict(baseline or {}),
        "statistik": stat,
        "vergleich": vergleich,
        "hinweise": [
            "Test-Bianca (nicht die Live-Leitung).",
            "Vollständige zufällige Dialoge; Kalenderbuchungen werden vor dem Write abgebrochen.",
            "Jeder Satz läuft als WAV durch dieselbe STT- und TTS-Audiopipeline.",
            "Vor der Lastwelle läuft je Mandant ein Einzelgespräch als Vergleich.",
            "SIP/Asterisk begrenzt echte Telefonleitungen zusätzlich.",
        ],
    }


def welle(*, n: int = 6, zuege: int = 2, basis: str, tenant: str = "",
          plan: dict[str, Any] | None = None,
          leitung: dict | None = None,
          fortschritt: Fortschritt | None = None) -> dict[str, Any]:
    if plan is None:
        if tenant:
            n = _kappe(n, MAX_PARALLEL)
            k = kunde_von(tenant)
            plan = {
                "n": n,
                "sitze": [{"nr": i + 1, "tenant": k["id"], "kurz": k["kurz"],
                           "farbe": k["farbe"],
                           "seed": random.SystemRandom().randrange(1, 2_000_000_000)}
                          for i in range(n)],
                "counts": {k["id"]: n},
                "kunden": [{**k, "n": n}],
            }
        else:
            plan = verteile(n)
    n = int(plan["n"])
    for sitz in plan["sitze"]:
        sitz.setdefault("seed", random.SystemRandom().randrange(1, 2_000_000_000))
    stories = [story_fuer_sitz(s) for s in plan["sitze"]]
    aktive_tenants: dict[str, dict[str, Any]] = {}
    for sitz in plan["sitze"]:
        aktive_tenants.setdefault(str(sitz["tenant"]), sitz)
    baseline_sitze: list[dict[str, Any]] = []
    baseline_stories: list[dict[str, Any]] = []
    for i, sitz in enumerate(aktive_tenants.values(), 1):
        bs = {**sitz, "nr": -i, "seed": 900_000 + i, "anliegen": geschichten.TERMIN}
        baseline_sitze.append(bs)
        baseline_stories.append(story_fuer_sitz(bs, baseline=True))

    sam = _Sammler(plan, fortschritt)
    gesamt_t0 = time.perf_counter()
    sam.meld("vorwaermen")

    # Die Anrufer-TTS darf die gemessene Bianca-TTS nicht verfälschen.
    # Deshalb alle voraussichtlichen Sätze vor der Einzelmessung rendern.
    gesehen: set[tuple[str, str]] = set()
    for story in [*baseline_stories, *stories]:
        for text in geschichten.saetze_fuer_audio(story):
            key = (str(story.get("stimme") or ""), text)
            if key in gesehen:
                continue
            gesehen.add(key)
            _wav_fuer_zug(story, text, leitung)
        sam.meld("vorwaermen")

    # Einzelgespräch je aktivem Mandanten: echte, mandantenscharfe Baseline.
    sam.meld("baseline")
    for sitz, story in zip(baseline_sitze, baseline_stories):
        ergebnis = _eine(
            sitz, basis=basis, story=story, start_tor=None,
            welle_t0=gesamt_t0, sam=sam, phase="baseline", leitung=leitung,
        )
        sam.ende_baseline(str(sitz["tenant"]), ergebnis)

    normen_je_tenant: dict[str, dict[str, float]] = {}
    basis_stat = statistik_von(sam.latenz, sam.blasen)["baseline"]["mandanten"]
    for tid, block in basis_stat.items():
        normen_je_tenant[tid] = {
            m: float(((block.get("metriken") or {}).get(m) or {}).get("p50") or 0)
            for m in METRIKEN
        }

    sam.meld("last")
    start_tor = threading.Barrier(n)
    laeufe: list[dict[str, Any] | None] = [None] * n
    welle_t0 = time.perf_counter()

    def arbeit(i: int) -> None:
        laeufe[i] = _eine(
            plan["sitze"][i], basis=basis, story=stories[i],
            start_tor=start_tor, welle_t0=welle_t0, sam=sam, phase="last",
            leitung=leitung,
            normen=normen_je_tenant.get(str(plan["sitze"][i]["tenant"])) or {},
        )

    threads = [threading.Thread(target=arbeit, args=(i,), daemon=True) for i in range(n)]
    for t in threads:
        t.start()
    deadline = time.perf_counter() + 1_200
    for t in threads:
        t.join(timeout=max(0.0, deadline - time.perf_counter()))
    for i, x in enumerate(laeufe):
        if x is None:
            sitz = plan["sitze"][i]
            laeufe[i] = {
                "nr": sitz["nr"], "ok": False, "fehler": "Thread nicht fertig",
                "startS": 0, "ersterTonS": 0, "antwortS": 0, "sessionId": "",
                "tenant": sitz["tenant"], "kurz": sitz["kurz"], "farbe": sitz["farbe"],
                "zuege": [],
            }
    return zusammenfassung(
        [x for x in laeufe if x], n=n,
        sekunden=time.perf_counter() - welle_t0,
        plan=plan, blasen=sam.blasen, transkript=sam.transkript,
        latenz=sam.latenz, baseline=sam.baseline,
        gesamt_sekunden=time.perf_counter() - gesamt_t0)
