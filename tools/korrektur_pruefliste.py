"""Read-only Pruefliste: Wo hat der Anrufer Bianca korrigiert — und kam es an?

Vorbild ist Claras Nachtlauf (F:\\Clara-Voice, tools/nachtlauf.py, nur
gelesen): die teuersten Fehler sind die, bei denen der Mensch etwas richtig
stellt und die Assistentin darueber hinweggeht. Der Tages-Scorer zaehlt nur
Schleifen; diese Liste zeigt die einzelne Stelle samt Vorlauf, damit daraus
ein Live-Satz-Test mit dem echten Wortlaut werden kann.

Je Zug wird der Anrufer-Satz geprueft:

* ``korrektur``  — ausdrueckliche Richtigstellung („ich meinte“, „nicht X,
  sondern Y“, „das stimmt nicht“, „Sie haben mich falsch verstanden“).
* ``widerspruch`` — „Nein, …“ mit eigenem Inhalt danach. Ein blankes
  „Nein.“ auf eine Ja/Nein-Frage ist eine Antwort, keine Korrektur.

Danach wird Biancas Reaktion gelesen (gleicher Zug, Folgezug):

* ``frage_wiederholt``   — sie stellt dieselbe Frage wie vor der Korrektur.
* ``nicht_verstanden``   — Unklar-Satz statt Aufnahme.
* ``korrektur_erneut``   — der Anrufer muss in den naechsten zwei Zuegen
  erneut korrigieren.
* ``quittiert``          — erkennbarer Bezug („Entschuldigung“, „korrigiere“).

Stufe ``rot`` = mindestens ein Ueberhoer-Befund, ``gelb`` = weder quittiert
noch ueberhoert (von Hand anhoeren), ``gruen`` = quittiert ohne Befund.

Beispiele (im Container, Protokolle unter /app/.data/anrufe/bianca):
    python tools/korrektur_pruefliste.py
    python tools/korrektur_pruefliste.py --datum 2026-10-06 --nur-rot
    python tools/korrektur_pruefliste.py --tage 7 --json /tmp/pruefliste.json

Das Werkzeug schreibt nie in Sitzungen, Kalender oder Manifeste. Namen und
Rufnummern werden maskiert; ``--klartext`` zeigt sie (nur am Server lesen,
nie ins Repo oder in Mails kopieren).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import tages_scorer as ts  # noqa: E402

STUFEN = ("rot", "gelb", "gruen")

_KORREKTUR_RE = re.compile(
    r"\bich\s+meinte\b|\bich\s+(?:habe|hab|hatte)\b[^.?!]{0,40}\bgesagt\b|"
    r"\bhabe?\s+ich\s+(?:doch\s+)?(?:nicht|gar\s+nicht|nie)\b[^.?!]{0,30}\bgesagt\b|"
    r"\bich\s+sagte\b|\bnicht\s+[^,.?!]{2,40}?,?\s+sondern\b|"
    r"\bdas\s+(?:ist|war|stimmt)\s+(?:so\s+)?(?:nicht|falsch)\b|"
    r"\bstimmt\s+(?:so\s+)?nicht\b|\b(?:ist|war)\s+falsch\b|"
    r"\b(?:sie\s+haben|du\s+hast)\s+(?:mich|das)\s+(?:falsch|nicht\s+richtig)\s+verstanden\b|"
    r"\bfalsch\s+(?:verstanden|geschrieben|notiert|eingetragen)\b|"
    r"\bkorrigier\w*\b",
    re.I,
)
# „Nein, nein, …“ zaehlt als EIN Nein — sonst fiele „Nein, nein, nicht
# Thomas, Thannes ist mein Nachname“ als inhaltsleer durch.
_NEIN_ANFANG_RE = re.compile(r"^\s*(?:(?:nein|nee|ne|nö|noe)\b[\s,.!-]*)+", re.I)
# Inhaltsleere Reste nach „Nein“: das ist eine Antwort, kein Widerspruch.
_NEIN_LEER_RE = re.compile(
    r"^(?:danke|dankesch\w*|nichts|nix|das\s+war\w*|alles|passt|gut|"
    r"bitte|noch\s+nicht|eigentlich\s+nicht|leider\s+nicht)\b",
    re.I,
)
_FRAGE_RE = re.compile(r"[^.?!]*\?")
_QUITTUNG_RE = re.compile(
    r"\bentschuldigung\b|\bverzeihung\b|\bkorrigiere\b|\bkorrigiert\b|"
    r"\bich\s+hatte\b[^.?!]{0,40}\bgeh(?:ö|oe)rt\b|\bdann\s+(?:also|eben)\b|"
    r"\bah\s+(?:so|okay)\b|\bverstehe\b|\bnat(?:ü|ue)rlich\b",
    re.I,
)
_WORT_RE = re.compile(r"[a-zäöüß0-9]+", re.I)


def _woerter(text: str) -> list[str]:
    return _WORT_RE.findall(text or "")


def art(text: str) -> str:
    """'korrektur' | 'widerspruch' | '' fuer einen Anrufer-Satz."""
    t = ts._s(text)
    if not t:
        return ""
    if _KORREKTUR_RE.search(t):
        return "korrektur"
    m = _NEIN_ANFANG_RE.match(t)
    if m:
        rest = t[m.end():].strip()
        if rest and not _NEIN_LEER_RE.match(rest) and len(_woerter(rest)) >= 3:
            return "widerspruch"
    return ""


def _fragen(text: str) -> set[str]:
    out = set()
    for satz in _FRAGE_RE.findall(text or ""):
        norm = re.sub(r"[^a-z0-9]+", " ", ts._fold(satz)).strip()
        if len(norm) >= 8:
            out.add(norm)
    return out


def befunde(zuege: list[dict], i: int) -> list[str]:
    """Ueberhoer-Signale fuer die Korrektur in Zug i."""
    antwort = ts._s(zuege[i].get("text"))
    vorher = ts._s(zuege[i - 1].get("text")) if i > 0 else ""
    out: list[str] = []
    if _fragen(antwort) & _fragen(vorher):
        out.append("frage_wiederholt")
    if ts._UNKLAR_RE.search(ts._fold(antwort)):
        out.append("nicht_verstanden")
    for j in range(i + 1, min(i + 3, len(zuege))):
        if art(zuege[j].get("textIn")) == "korrektur":
            out.append("korrektur_erneut")
            break
    if _QUITTUNG_RE.search(antwort):
        out.append("quittiert")
    return out


def stufe(signale: list[str]) -> str:
    quittiert = "quittiert" in signale
    if "nicht_verstanden" in signale or "korrektur_erneut" in signale:
        return "rot"
    # Nach einer Quittung darf die naechste Pflichtfrage wieder dieselbe sein
    # („… korrigiere ich auf Thannes. Wie ist Ihr Vorname?“).
    if "frage_wiederholt" in signale and not quittiert:
        return "rot"
    return "gruen" if quittiert else "gelb"


# Verhoerte Sammler-Namen tragen manchmal Allerweltswoerter („SMS“); die
# zu maskieren macht die Liste unlesbar, ohne jemanden zu schuetzen.
_KEIN_NAME = {
    "sms", "frau", "herr", "herrn", "doktor", "termin", "nein", "ja", "und",
    "der", "die", "das", "ich", "sie", "mit", "von", "fertig", "bitte", "danke",
}


def _schutzwoerter(manifest: dict) -> list[str]:
    """Namen aus dem Manifest, die maskiert werden muessen."""
    namen: set[str] = set()
    sammler = manifest.get("sammler") if isinstance(manifest.get("sammler"), dict) else {}
    anrufer = manifest.get("anrufer") if isinstance(manifest.get("anrufer"), dict) else {}
    quellen = [ts._s(q.get(k)) for q in (sammler, anrufer)
               for k in ("name", "vorname", "nachname", "kontaktName")]
    quellen.append(ts._s(manifest.get("patientName")))
    for text in quellen:
        namen.update(w for w in _woerter(text)
                     if len(w) >= 3 and w.lower() not in _KEIN_NAME)
    return sorted(namen, key=len, reverse=True)


_ZIFFERN_RE = re.compile(r"(?:\d[\s/-]?){4,}")
_ANREDE_RE = re.compile(r"\b(Frau|Herrn?)\s+(?!Doktor\b)[A-ZÄÖÜ][\w-]*")


def maskieren(text: str, namen: list[str]) -> str:
    out = _ZIFFERN_RE.sub("[NUMMER] ", text or "").strip()
    out = _ANREDE_RE.sub(r"\1 [NAME]", out)
    for name in namen:
        out = re.sub(rf"\b{re.escape(name)}\b", "[NAME]", out, flags=re.I)
    return out


def _waechter(zug: dict) -> list[str]:
    return [ts._s(w.get("w")) for w in (zug.get("waechter") or [])
            if isinstance(w, dict) and ts._s(w.get("w"))]


def pruefen(session_id: str, manifest: dict, *, klartext: bool = False) -> list[dict]:
    zuege = ts._wertbare_zuege(manifest)
    namen = [] if klartext else _schutzwoerter(manifest)
    m = (lambda t: ts._s(t)) if klartext else (lambda t: maskieren(ts._s(t), namen))
    out: list[dict] = []
    for i, zug in enumerate(zuege):
        a = art(zug.get("textIn"))
        if not a:
            continue
        signale = befunde(zuege, i)
        vorlauf = [
            {"bianca": m(zuege[j].get("text")), "anrufer": m(zuege[j].get("textIn"))}
            for j in range(max(0, i - 2), i)
        ]
        out.append({
            "id": f"{session_id[:8]}-z{i}",
            "session": session_id,
            "praxis": ts._praxis(manifest),
            "zug": i,
            "art": a,
            "stufe": stufe(signale),
            "signale": signale,
            "frage": ts._s(zug.get("frage") or ""),
            "waechter": _waechter(zug),
            "vorlauf": vorlauf,
            "eingabe": m(zug.get("textIn")),
            "ist": m(zug.get("text")),
            "soll": "Korrektur uebernehmen und kurz bestaetigen; die Frage von "
                    "davor nicht wortgleich wiederholen.",
        })
    return out


def bericht(eintraege: list[dict], anrufe: int) -> dict[str, Any]:
    zaehler = {s: sum(1 for e in eintraege if e["stufe"] == s) for s in STUFEN}
    praxen: dict[str, dict[str, int]] = {}
    for e in eintraege:
        p = praxen.setdefault(e["praxis"], {s: 0 for s in STUFEN})
        p[e["stufe"]] += 1
    reihenfolge = {s: n for n, s in enumerate(STUFEN)}
    eintraege = sorted(eintraege, key=lambda e: (reihenfolge[e["stufe"]], e["id"]))
    return {"anrufe": anrufe, "stellen": len(eintraege), "stufen": zaehler,
            "praxen": praxen, "eintraege": eintraege}


def _text_ausgeben(rep: dict[str, Any], *, nur_rot: bool) -> None:
    s = rep["stufen"]
    print(f"anrufe={rep['anrufe']} korrekturstellen={rep['stellen']} "
          f"rot={s['rot']} gelb={s['gelb']} gruen={s['gruen']}")
    for name, p in sorted(rep["praxen"].items()):
        print(f"  {name}: rot={p['rot']} gelb={p['gelb']} gruen={p['gruen']}")
    for e in rep["eintraege"]:
        if nur_rot and e["stufe"] != "rot":
            continue
        if e["stufe"] == "gruen":
            continue
        print()
        print(f"[{e['stufe']}] {e['id']} {e['praxis']} {e['art']} "
              f"signale={','.join(e['signale']) or '-'} frage={e['frage'] or '-'}")
        for v in e["vorlauf"]:
            if v["bianca"]:
                print(f"    Bianca : {v['bianca'][:160]}")
            if v["anrufer"]:
                print(f"    Anrufer: {v['anrufer'][:160]}")
        print(f"  > Anrufer: {e['eingabe'][:200]}")
        print(f"  > Bianca : {e['ist'][:200]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Korrektur-Pruefliste (read-only)")
    parser.add_argument(
        "--root", type=Path,
        default=Path("/app/.data/anrufe/bianca")
        if Path("/app").is_dir() else Path(".data/anrufe/bianca"),
    )
    parser.add_argument("--datum", help="Lokaler Kalendertag, YYYY-MM-DD (Default heute)")
    parser.add_argument("--tage", type=int, default=1,
                        help="So viele Tage bis einschliesslich --datum")
    parser.add_argument("--zeitzone", default="Europe/Berlin")
    parser.add_argument("--tenant", default="")
    parser.add_argument("--tests", action="store_true", help="Testanrufe mitpruefen")
    parser.add_argument("--nur-rot", action="store_true")
    parser.add_argument("--klartext", action="store_true",
                        help="Namen/Nummern nicht maskieren (nur am Server lesen)")
    parser.add_argument("--json", type=Path, help="Pruefliste zusaetzlich als JSON schreiben")
    args = parser.parse_args(argv)

    start, ende = ts._grenzen(args.datum, None, None, args.zeitzone)
    start = start - timedelta(days=max(0, args.tage - 1))
    geladen = ts.manifests(args.root, start=start, ende=ende,
                           tenant=args.tenant, tests=args.tests)
    eintraege: list[dict] = []
    for sid, manifest in geladen:
        eintraege.extend(pruefen(sid, manifest, klartext=args.klartext))
    rep = bericht(eintraege, len(geladen))
    rep["zeitraum"] = {"von": start.isoformat(), "bis": ende.isoformat()}
    if args.json:
        args.json.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    _text_ausgeben(rep, nur_rot=args.nur_rot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
