"""Isoliertes Test-Dock fuer den Dialogkern — Browser ODER CLI, KEIN Telefon.

Startet einen winzigen stdlib-HTTP-Server (nur 127.0.0.1), der den reinen Kern
ueber den Orchestrator treibt. Man tippt im Browser gegen Bianca; Werkzeuge
werden simuliert (``gateway_sim``), es gibt KEIN MAS, KEINE Cloud Function,
KEIN Firestore und beruehrt KEINEN Live-Dienst (8095/8096/8097/8098).

Start (Browser):   python -m bianca.controller.dock            # -> 127.0.0.1:8199
Start (Terminal):  python -m bianca.controller.dock --cli

Szenario-Schalter im Browser steuern den Simulator (leere Slots, needs_phone,
slot_taken, mehrere/keine Termine, telefonisch nicht buchbar) — so laufen
Retry-, Ruecklese- und Ehrlich-nein-Pfade ohne echte Systeme.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bianca.controller import policy as pol
from bianca.controller.gateway_sim import Szenario
from bianca.controller.orchestrator import TestGespraech

_HOST = "127.0.0.1"
_PORT = 8199  # bewusst NICHT 8095/8096/8097/8098 (Live/Studio/Test)


# --------------------------------------------------------------------------- #
# Szenarien fuer den Dropdown.
# --------------------------------------------------------------------------- #
_SZENARIEN: dict[str, Szenario] = {
    "glueck": Szenario(
        anrufer_anrede="Frau",
        anrufer_nachname="Meier",
        anrufer_telefon="01701234567",
        anrufer_versicherung="gesetzlich",
        letzter_arzt="Doktor Blessing",
        letzter_grund="Hautscreening",
        letzter_wann="4 Monaten",
        termine=3,
    ),
    "keine_slots": Szenario(freie_slots=0),
    "nicht_buchbar": Szenario(slots_denied=True),
    "needs_phone": Szenario(buchung="needs_phone"),
    "slot_weg": Szenario(buchung="slot_taken"),
    "kein_termin": Szenario(termine=0),
    "mehrere_termine": Szenario(termine=3),
}


def _hirn_fn():
    """vLLM wenn erreichbar — sonst None (Dock bleibt tippbar).

    Nur dieses Dock: wenn die Live-.env-Basis tot ist, denselben Vertrag
    gegen den erreichbaren Peer versuchen. Live-Bianca/.env bleiben unangetastet.
    """
    try:
        from kern import llm as _llm
        if not _llm.health(timeout=2.0).get("ok"):
            alt = "http://100.77.30.98:8000/v1"
            if _llm.LLM_BASE.rstrip("/") != alt.rstrip("/"):
                _llm.LLM_BASE = alt
                _llm._CLIENT = None
            if not _llm.health(timeout=2.5).get("ok"):
                return None
        from bianca.controller import hirn
        return hirn.deuten
    except Exception:
        return None


_HIRN = _hirn_fn()


class _Sitzung:
    """Haelt EIN Gespraech (Dock ist Ein-Benutzer, lokal)."""

    def __init__(self) -> None:
        self.szenario_name = "glueck"
        self.gespraech = TestGespraech(pol.default(), _SZENARIEN["glueck"], llm=_HIRN)

    def reset(self, szenario_name: str | None = None) -> str:
        if szenario_name in _SZENARIEN:
            self.szenario_name = szenario_name
        sz = _SZENARIEN[self.szenario_name]
        self.gespraech = TestGespraech(pol.default(), sz, llm=_HIRN)
        return self.gespraech.start()


_SITZUNG = _Sitzung()


# --------------------------------------------------------------------------- #
# HTML (inline, keine Assets, kein externes CDN).
# --------------------------------------------------------------------------- #
_HTML = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dialogkern — Test-Dock (isoliert)</title>
<style>
 body{font-family:system-ui,Arial,sans-serif;margin:0;background:#eef1f5;color:#1b2430}
 header{background:#24374e;color:#fff;padding:12px 18px;display:flex;
   align-items:center;gap:14px;flex-wrap:wrap}
 header b{font-size:16px}
 header .tag{background:#d862c8;border-radius:10px;padding:2px 8px;font-size:12px}
 main{max-width:760px;margin:0 auto;padding:14px}
 #log{background:#fff;border-radius:12px;padding:14px;min-height:60vh;
   box-shadow:0 1px 4px rgba(0,0,0,.08)}
 .z{margin:8px 0;display:flex}
 .z.u{justify-content:flex-end}
 .b{max-width:78%;padding:9px 12px;border-radius:14px;white-space:pre-wrap;line-height:1.35}
 .u .b{background:#24374e;color:#fff;border-bottom-right-radius:4px}
 .a .b{background:#f0f2f6;border:1px solid #dce1e8;border-bottom-left-radius:4px}
 .meta{font-size:11px;color:#8a94a2;margin-top:3px}
 .llm{font-size:11px;color:#6b7380;margin:-2px 0 10px 2px;max-width:78%;white-space:pre-wrap;
      font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap;line-height:1.3}
 .sys{color:#8a94a2;font-size:12px;text-align:center;margin:10px 0}
 form{display:flex;gap:8px;margin-top:12px}
 input[type=text]{flex:1;padding:11px 12px;border:1px solid #c6cdd7;border-radius:10px;font-size:15px}
 button{background:#24374e;color:#fff;border:0;border-radius:10px;padding:0 16px;
   font-size:15px;cursor:pointer}
 button.sec{background:#7a8698}
 .bar{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}
 select{padding:8px;border-radius:8px;border:1px solid #c6cdd7}
 label.dbg{font-size:12px;color:#5b6470;display:flex;gap:5px;align-items:center}
 .over{color:#8a5}
</style></head><body>
<header>
  <b>Dialogkern</b><span class="tag">isoliert · 19.09v · Loop-Aufsicht (Rückblick→Übergabe) HIRN_STATUS</span>
  <span style="margin-left:auto;font-size:12px">Werkzeuge = SIM · keine MAS/CF/Firestore</span>
</header>
<main>
 <div id="log"></div>
 <form id="f" autocomplete="off">
   <input id="t" type="text" placeholder="Nachricht tippen … (z. B. 'Ich haette gern einen Termin')" autofocus>
   <button type="submit">Senden</button>
 </form>
 <div class="bar">
   <span>Szenario:</span>
   <select id="sz">
     <option value="glueck">Gluecklicher Pfad</option>
     <option value="keine_slots">Keine freien Slots</option>
     <option value="nicht_buchbar">Telefonisch nicht buchbar</option>
     <option value="needs_phone">Buchung: Handynummer noetig</option>
     <option value="slot_weg">Buchung: Slot vergeben</option>
     <option value="kein_termin">Verwaltung: kein Termin gefunden</option>
     <option value="mehrere_termine">Verwaltung: mehrere Termine</option>
   </select>
   <button class="sec" id="reset" type="button">Neu starten</button>
   <label class="dbg"><input type="checkbox" id="dbg"> Kern-Denken zeigen</label>
 </div>
 <div class="sys">Glücklicher Pfad: Frau Meier, vor 4 Monaten Hautscreening bei Doktor Blessing. Nach Ja keine erneute Datenabfrage. Power: <code>#intent=buchen</code> <code>#ja</code></div>
</main>
<script>
const log=document.getElementById('log'), inp=document.getElementById('t');
function add(cls,text,meta){
  const z=document.createElement('div'); z.className='z '+cls;
  const b=document.createElement('div'); b.className='b'; b.textContent=text; z.appendChild(b);
  if(meta){const m=document.createElement('div');m.className='meta';m.textContent=meta;b.appendChild(m);}
  log.appendChild(z); log.scrollTop=log.scrollHeight;
}
function sys(t){const d=document.createElement('div');d.className='sys';d.textContent=t;log.appendChild(d);log.scrollTop=log.scrollHeight;}
async function post(body){
  const r=await fetch('/api/eingabe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  return await r.json();
}
function zeigeAntwort(d){
  const dbgOn=document.getElementById('dbg').checked;
  let meta='';
  if(d.uebergeben) meta='UEBERGABE an Legacy · '+d.grund;
  else if(dbgOn) meta=[d.naechste,d.tool,d.grund].filter(Boolean).join(' · ')
                    +(d.debug?('  |  '+JSON.stringify(d.debug)):'');
  add('a', d.antwort||'(kein Satz)', meta||undefined);
  const l=document.createElement('div');
  l.className='llm';
  l.textContent=d.llm || '— keine LLM-Zeile —';
  log.appendChild(l);
  log.scrollTop=log.scrollHeight;
  if(d.hangup) sys('— Anruf beendet (auflegen) —');
}
document.getElementById('f').addEventListener('submit',async e=>{
  e.preventDefault(); const t=inp.value.trim(); if(!t)return;
  add('u',t); inp.value='';
  try{ zeigeAntwort(await post({text:t})); }catch(err){ sys('Fehler: '+err); }
});
async function reset(){
  log.innerHTML='';
  const sz=document.getElementById('sz').value;
  const d=await post({reset:true,szenario:sz});
  sys('Szenario: '+sz); add('a', d.antwort);
}
document.getElementById('reset').addEventListener('click',reset);
document.getElementById('sz').addEventListener('change',reset);
reset();
</script>
</body></html>"""
_HTML = _HTML.replace("HIRN_STATUS", "an" if _HIRN else "aus")


# --------------------------------------------------------------------------- #
# HTTP-Handler.
# --------------------------------------------------------------------------- #
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a) -> None:  # noqa: D401 - stumm halten
        pass

    def _json(self, obj: dict, code: int = 200) -> None:
        roh = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in ("/", "/index.html"):
            self._json({"error": "not_found"}, 404)
            return
        roh = _HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/eingabe":
            self._json({"error": "not_found"}, 404)
            return
        laenge = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(laenge) or b"{}")
        except (ValueError, TypeError):
            self._json({"error": "bad_json"}, 400)
            return
        if body.get("reset"):
            antwort = _SITZUNG.reset(body.get("szenario"))
            self._json({"antwort": antwort, "llm": "— Begrüßung, noch kein Zug —"})
            return
        text = str(body.get("text") or "")
        a = _SITZUNG.gespraech.eingabe(text)
        self._json(a.as_dict())


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def _cli() -> None:
    g = TestGespraech(pol.default(), _SZENARIEN["glueck"], llm=_HIRN)
    print("Dialogkern-Test (CLI). 'reset' startet neu, 'exit' beendet.\n")
    print("BIANCA:", g.start())
    while True:
        try:
            text = input("\nDU: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() in ("exit", "quit"):
            break
        if text.lower() == "reset":
            g = TestGespraech(pol.default(), _SZENARIEN["glueck"], llm=_HIRN)
            print("BIANCA:", g.start())
            continue
        a = g.eingabe(text)
        marke = " · ".join(x for x in (a.naechste, a.tool, a.grund) if x)
        print("BIANCA:", a.antwort or "(kein Satz)")
        print("   LLM:", a.llm or "— keine LLM-Zeile —")
        print("        [", marke, "]")
        if a.uebergeben:
            print("        [-> Legacy-Pfad wuerde hier uebernehmen]")
        if a.hangup:
            print("        [-> Anruf beendet]")


def main() -> None:
    ap = argparse.ArgumentParser(description="Isoliertes Test-Dock des Dialogkerns")
    ap.add_argument("--cli", action="store_true", help="im Terminal statt im Browser")
    ap.add_argument("--port", type=int, default=_PORT)
    args = ap.parse_args()
    if args.cli:
        _cli()
        return
    srv = ThreadingHTTPServer((_HOST, args.port), _Handler)
    print(f"Test-Dock laeuft:  http://{_HOST}:{args.port}")
    print("  Hirn:", "vLLM an" if _HIRN else "aus (vLLM nicht erreichbar)")
    print("  (isoliert, simuliert — kein Telefon, kein MAS/CF. Strg+C beendet.)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nDock beendet.")
        srv.shutdown()


if __name__ == "__main__":
    main()
