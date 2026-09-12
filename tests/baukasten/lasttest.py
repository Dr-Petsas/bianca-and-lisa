"""Belastungstest: parallele Kurzgespraeche, Monitoring ohne Browser-Audio.

Audio laeuft weiter durch die Pipeline (Start/Listen/TTS-Stream wird gezogen),
im Studio wird nichts vorgespielt. WRITE_LIVE bleibt unberuehrt — kein Buchen.
"""

from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from tests.baukasten import klang

MAX_PARALLEL = 18
LAST_SATZ = "Hallo, ich bin Markus Müller, ich hätte gerne einen Termin."
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
}


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
        sitze.append({
            "nr": i + 1,
            "tenant": k["id"],
            "kurz": k["kurz"],
            "farbe": k["farbe"],
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


def _audio_ziehen(basis: str, url: str) -> None:
    ziel = _abs_url(basis, url)
    if not ziel:
        return
    try:
        with httpx.Client(timeout=40.0) as client:
            with client.stream("GET", ziel) as r:
                r.raise_for_status()
                for _ in r.iter_bytes(65_536):
                    pass
    except Exception:
        pass


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
    final: dict[str, Any] = {}
    letzter_ton = 0.0
    luecken: list[float] = []
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
                if typ == "filler":
                    if not erster:
                        erster = round(jetzt, 2)
                    if letzter_ton and (jetzt - letzter_ton) > NORM["lueckeS"]:
                        luecken.append(round(jetzt - letzter_ton, 2))
                    letzter_ton = jetzt
                    if zieh and ev.get("audioUrl"):
                        threading.Thread(
                            target=_audio_ziehen,
                            args=(basis, ev.get("audioUrl")),
                            daemon=True,
                        ).start()
                if typ in ("reply", "warte", "empty"):
                    final = ev
                    break
    final["_latenzS"] = round(time.perf_counter() - t0, 2)
    final["_ersterTonS"] = erster or final["_latenzS"]
    final["_gehoert"] = gehoert or _text_von(final)
    final["_luecken"] = luecken
    if zieh and final.get("audioUrl"):
        threading.Thread(
            target=_audio_ziehen, args=(basis, final.get("audioUrl")),
            daemon=True,
        ).start()
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
        self._last_meld = 0.0

    def _snap(self, phase: str) -> dict[str, Any]:
        return {
            "phase": phase,
            "n": self.plan["n"],
            "fertig": self.fertig,
            "plan": self.plan,
            "norm": dict(NORM),
            "events": list(self.events[-240:]),
            "blasen": list(self.blasen),
            "transkript": list(self.transkript[-160:]),
            "latenz": list(self.latenz[-240:]),
            "kpis": kpis_von(self.latenz, self.blasen, self.fertig, self.plan["n"]),
        }

    def meld(self, phase: str = "lauf") -> None:
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
        self.meld("lauf")


def kpis_von(latenz: list[dict[str, Any]], blasen: list[dict[str, Any]],
             fertig: int, n: int) -> dict[str, Any]:
    toene = [float(p["wert"]) for p in latenz if p.get("metrik") == "ersterTon"]
    antw = [float(p["wert"]) for p in latenz if p.get("metrik") == "antwort"]
    starts = [float(p["wert"]) for p in latenz if p.get("metrik") == "start"]
    offs = [float(p.get("offsetPct") or 0) for p in latenz if p.get("metrik") in
            ("ersterTon", "antwort", "start")]
    return {
        "fertig": fertig,
        "n": n,
        "dropouts": len(blasen),
        "startP50": _perzentil(starts, 50),
        "ersterTonP50": _perzentil(toene, 50),
        "ersterTonP95": _perzentil(toene, 95),
        "antwortP50": _perzentil(antw, 50),
        "antwortP95": _perzentil(antw, 95),
        "offsetPct": round(sum(offs) / len(offs), 1) if offs else 0.0,
        "offsetP95": _perzentil(offs, 95),
    }


def _eine(sitz: dict[str, Any], *, basis: str, wav: Path, zuege: int,
          start_tor: threading.Barrier, welle_t0: float,
          sam: _Sammler) -> dict[str, Any]:
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
        "zuege": [],
    }
    try:
        start_tor.wait(timeout=45)
    except threading.BrokenBarrierError:
        out["fehler"] = "Starttor abgelaufen"
        return out
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=httpx.Timeout(90.0, connect=10.0)) as c:
            r = c.post(f"{basis}/api/start", json={
                "tenant": tenant, "test": True,
                "testName": f"Last {k['kurz']} {nr}",
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
            off = latenz_offset(start_s, NORM["startS"])
            sam.punkt(tS=t_abs, metrik="start", nr=nr, tenant=tenant, **off)
            sam.zeile(tS=t_abs, nr=nr, tenant=tenant, kurz=k["kurz"],
                      farbe=k["farbe"], wer="bianca", text=_text_von(d) or "Begrüßung")
            threading.Thread(
                target=_audio_ziehen,
                args=(basis, d.get("audioUrl") or ""),
                daemon=True,
            ).start()
            toene: list[float] = []
            antworten: list[float] = []
            for _ in range(zuege):
                t_zug = time.perf_counter() - welle_t0
                ev = _listen(c, basis, sid, wav, zieh=True)
                et = float(ev.get("_ersterTonS") or 0)
                ant = float(ev.get("_latenzS") or 0)
                leer = str(ev.get("type") or "") == "empty"
                toene.append(et)
                antworten.append(ant)
                o1 = latenz_offset(et, NORM["ersterTonS"])
                o2 = latenz_offset(ant, NORM["antwortS"])
                sam.punkt(tS=round(t_zug + et, 2), metrik="ersterTon",
                          nr=nr, tenant=tenant, **o1)
                sam.punkt(tS=round(t_zug + ant, 2), metrik="antwort",
                          nr=nr, tenant=tenant, **o2)
                gehoert = str(ev.get("_gehoert") or "")
                if gehoert:
                    sam.zeile(tS=round(t_zug, 2), nr=nr, tenant=tenant,
                              kurz=k["kurz"], farbe=k["farbe"],
                              wer="anrufer", text=gehoert)
                mund = _text_von(ev)
                if mund:
                    sam.zeile(tS=round(t_zug + ant, 2), nr=nr, tenant=tenant,
                              kurz=k["kurz"], farbe=k["farbe"],
                              wer="bianca", text=mund)
                drops = dropouts_von_zug(
                    tS=t_zug, ersterTonS=et, antwortS=ant, leer=leer,
                    nr=nr, tenant=tenant, kurz=k["kurz"], farbe=k["farbe"])
                for luecke in ev.get("_luecken") or []:
                    drops.append({
                        "tS": round(t_zug + et, 2), "dauerS": float(luecke),
                        "art": "luecke", "nr": nr, "tenant": tenant,
                        "kurz": k["kurz"], "farbe": k["farbe"],
                    })
                sam.blase(drops)
                out["zuege"].append({
                    "ersterTonS": et, "antwortS": ant, "leer": leer,
                    "text": mund, "gehoert": gehoert,
                })
                if leer:
                    raise RuntimeError(str(ev.get("error") or "leerer Zug"))
            out["ersterTonS"] = max(toene) if toene else 0.0
            out["antwortS"] = max(antworten) if antworten else 0.0
            try:
                c.post(f"{basis}/api/hangup", json={"sessionId": sid}, timeout=15)
            except httpx.HTTPError:
                pass
            out["ok"] = True
    except Exception as e:
        out["fehler"] = f"{type(e).__name__}: {e}"
        sam.zeile(tS=round(time.perf_counter() - welle_t0, 2), nr=nr,
                  tenant=tenant, kurz=k["kurz"], farbe=k["farbe"],
                  wer="system", text=out["fehler"])
        sam.blase(dropouts_von_zug(
            tS=round(time.perf_counter() - welle_t0, 2),
            ersterTonS=0, antwortS=0, leer=True, nr=nr, tenant=tenant,
            kurz=k["kurz"], farbe=k["farbe"]))
    sam.ende_sitzung()
    return out


def zusammenfassung(laeufe: list[dict[str, Any]], *, n: int, sekunden: float,
                    plan: dict[str, Any] | None = None,
                    blasen: list[dict[str, Any]] | None = None,
                    transkript: list[dict[str, Any]] | None = None,
                    latenz: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    ok = [x for x in laeufe if x.get("ok")]
    fehl = [x for x in laeufe if not x.get("ok")]
    toene = [float(x.get("ersterTonS") or 0) for x in ok]
    antw = [float(x.get("antwortS") or 0) for x in ok]
    starts = [float(x.get("startS") or 0) for x in ok]
    plan = plan or verteile(n)
    lat = list(latenz or [])
    bla = list(blasen or [])
    return {
        "n": n,
        "gehalten": len(ok),
        "fehler": len(fehl),
        "dauerS": round(sekunden, 2),
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
        "hinweise": [
            "Test-Bianca (nicht die Live-Leitung).",
            "Kein Buchen — nur Begrüßung und kurze Züge.",
            "Audio wird in der Pipeline abgespielt, nicht im Monitor.",
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
                           "farbe": k["farbe"]} for i in range(n)],
                "counts": {k["id"]: n},
                "kunden": [{**k, "n": n}],
            }
        else:
            plan = verteile(n)
    n = int(plan["n"])
    zuege = _kappe(zuege, 3)
    pfad = klang.audio_holen(klang.DEMO_STIMME, LAST_SATZ)
    if leitung:
        pfad = klang.telefon_datei(pfad, leitung=leitung)
    sam = _Sammler(plan, fortschritt)
    sam.meld("start")
    start_tor = threading.Barrier(n)
    laeufe: list[dict[str, Any] | None] = [None] * n
    welle_t0 = time.perf_counter()

    def arbeit(i: int) -> None:
        laeufe[i] = _eine(
            plan["sitze"][i], basis=basis, wav=pfad, zuege=zuege,
            start_tor=start_tor, welle_t0=welle_t0, sam=sam)

    threads = [threading.Thread(target=arbeit, args=(i,), daemon=True) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=220)
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
        latenz=sam.latenz)
