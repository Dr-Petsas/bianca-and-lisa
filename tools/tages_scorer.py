"""Read-only Tagesauswertung der Telefon-KI-Anrufe.

Die Rubrik ist absichtlich streng und evidenzbasiert:

* ``super``: belegter Abschluss, keine erkennbare Reibung.
* ``gut``: belegter Abschluss mit hoechstens einer kleinen Reibung oder
  ehrlicher Rueckruf-/Praxisnotiz-Abschluss.
* ``durchwachsen``: echtes Gespraech, aber mehrere Reibungen oder kein klarer
  Abschluss nach einem laengeren Verlauf.
* ``unvollstaendig``: Anliegen genannt, Gespraech frueh ohne Abschluss beendet.
* ``fehlerhaft``: harter Fehler (Write fehlgeschlagen, Erfolg ohne Beweis,
  Phantom-Transfer, Fakten-/Unklar-/Presence-Schleife).

Aufleger sind NUR Anrufe ohne substanziellen Anrufersatz. Ein genanntes
Anliegen bleibt auch dann in der Wertung, wenn der Anrufer danach auflegt.

Beispiele:

    python tools/tages_scorer.py
    python tools/tages_scorer.py --datum 2026-09-15 --json /tmp/score.json
    python tools/tages_scorer.py --seit 2026-09-15T16:00:00+00:00 --tenant blessing

Das Werkzeug schreibt nie in Sitzungen, Kalender oder Manifeste. ``--json``
schreibt ausschliesslich den angeforderten Bericht.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


KLASSEN = ("super", "gut", "durchwachsen", "unvollstaendig", "fehlerhaft")
ZIEL_SUPER = 40.0
ZIEL_MINDESTENS_GUT = 80.0

_LEERWORTE = {
    "aeh", "aehem", "aha", "also", "bitte", "danke", "dankeschoen", "gut",
    "hallo", "hi", "hm", "ja", "jaja", "mhm", "nein", "okay", "ok", "oh",
    "servus", "test", "tschuess", "uff",
}
_ANLIEGEN_RE = re.compile(
    r"\b(?:termin|buchen|vereinbaren|verschieben|verlegen|absagen|stornieren|"
    r"rezept|ueberweisung|krankmeldung|rechnung|rueckruf|verbinden|sprechen|"
    r"oeffnungszeit|sprechzeit|schmerz|notfall|kontrolle|screening|beratung|"
    r"ausschlag|allerg|akne|rosacea|ekzem|nagel|wunde|haut|vorsorge)\w*\b",
    re.I,
)
_UNKLAR_RE = re.compile(
    r"was meinen sie damit|meinen sie vielleicht etwas anderes|"
    r"das habe ich nicht verstanden|akustisch nicht verstanden",
    re.I,
)
_PRESENCE_RE = re.compile(
    r"sind sie noch dran|ich bin noch da|meine frage war",
    re.I,
)
_NEUE_RE = re.compile(r"\bich bin die neue\b|wir kennen uns noch nicht", re.I)
_SERMON_RE = re.compile(
    r"entlaste die anmeldung|medizinische versorgung der patienten|"
    r"ich verbessere mich mit jedem anruf",
    re.I,
)
_SONST_RE = re.compile(r"kann ich (?:ihnen )?sonst noch|sonst etwas fuer sie", re.I)
_IDENTITAET_RE = re.compile(r"richtig erkannt|termin ist fuer sie selbst", re.I)
_KALENDER_DOWN_RE = re.compile(r"terminkalender antwortet gerade nicht", re.I)
_ERFOLG = {
    "book": re.compile(
        r"\btermin\b.{0,90}\b(?:fest )?(?:eingetragen|gebucht|vereinbart)\b|"
        r"\balles\b.{0,30}\beingetragen\b",
        re.I | re.S,
    ),
    "cancel": re.compile(
        r"\btermin\b.{0,90}\b(?:abgesagt|storniert|geloescht|gestrichen)\b",
        re.I | re.S,
    ),
    "move": re.compile(
        r"\btermin\b.{0,90}\b(?:verschoben|verlegt|umgebucht)\b",
        re.I | re.S,
    ),
    "note": re.compile(
        r"\b(?:notiz|rueckruf(?:bitte|wunsch)?)\b.{0,90}"
        r"\b(?:notiert|angelegt|geschrieben|eingerichtet)\b|"
        r"\bdie praxis meldet sich\b",
        re.I | re.S,
    ),
    "transfer": re.compile(
        r"\b(?:stelle|verbinde|leite)\b.{0,80}\b(?:durch|weiter|verbindung)\b|"
        r"\bverbindung\b.{0,60}\b(?:eingeleitet|hergestellt)\b",
        re.I | re.S,
    ),
}
_RULE_ANSWER_RE = re.compile(
    r"persoenlich in die praxis|am telefon nicht ausstellen|"
    r"die genauen oeffnungszeiten habe ich hier leider nicht|"
    r"kommen sie bitte jetzt|rufen sie bitte 112|116\s*117|"
    r"gehoert nicht zu unserer praxis",
    re.I,
)
_WRITE_PARTS = {
    "book": ("bookappointment", "book_slot", "masbook"),
    "cancel": ("cancelappointment", "cancel_appointment", "mascancel"),
    "move": ("moveappointment", "move_appointment", "masmove"),
    "note": ("appointmentnote", "note_appointment", "praxis_notiz"),
    "phone": ("updatepatientphone", "update_phone"),
    "patient": ("createpatient", "create_patient"),
    "transfer": ("transfer",),
}


def _s(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _fold(value: Any) -> str:
    return (
        _s(value).lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def _dt(value: Any) -> datetime | None:
    text = _s(value).replace("Z", "+00:00")
    if not text:
        return None
    try:
        out = datetime.fromisoformat(text)
    except ValueError:
        return None
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return out


def _zuege(manifest: dict) -> list[dict]:
    return [z for z in (manifest.get("zuege") or []) if isinstance(z, dict)]


def _inputs(manifest: dict) -> list[str]:
    return [_s(z.get("textIn")) for z in _zuege(manifest) if _s(z.get("textIn"))]


def _outputs(manifest: dict) -> list[str]:
    return [_s(z.get("text")) for z in _zuege(manifest) if _s(z.get("text"))]


def _substantiell(text: str) -> bool:
    """Ein Anliegen nicht als Aufleger wegrechnen.

    Reine Begruessungen/Fuelllaute zaehlen nicht. Ein Taskwort zaehlt auch
    allein; ansonsten braucht es mindestens zwei echte Inhaltswoerter.
    """
    folded = _fold(text)
    if not folded:
        return False
    if _ANLIEGEN_RE.search(folded):
        return True
    woerter = re.findall(r"[a-z0-9]+", folded)
    inhalt = [w for w in woerter if w not in _LEERWORTE and len(w) > 1]
    return len(inhalt) >= 2


def substantielle_inputs(manifest: dict) -> list[str]:
    return [text for text in _inputs(manifest) if _substantiell(text)]


def _marker_ok(manifest: dict, key: str) -> bool:
    value = manifest.get(key)
    if not value:
        return False
    if not isinstance(value, dict):
        return bool(value)
    if value.get("ok") is False or value.get("success") is False:
        return False
    if value.get("error") and not (
        value.get("ok") or value.get("success") or value.get("appointmentId")
        or value.get("id")
    ):
        return False
    return True


def _tools(manifest: dict) -> list[dict]:
    out = [x for x in (manifest.get("tools") or []) if isinstance(x, dict)]
    for zug in _zuege(manifest):
        out.extend(x for x in (zug.get("tools") or []) if isinstance(x, dict))
    return out


def _tool_name(tool: dict) -> str:
    return _fold(tool.get("name") or tool.get("tool"))


def _tool_ok(tool: dict) -> bool:
    if tool.get("ok") is False or tool.get("success") is False:
        return False
    if tool.get("error"):
        return False
    if tool.get("ok") is True or tool.get("success") is True:
        return True
    dispatch = tool.get("dispatch") if isinstance(tool.get("dispatch"), dict) else {}
    response = dispatch.get("response") if isinstance(dispatch.get("response"), dict) else {}
    if response.get("success") is False or response.get("ok") is False:
        return False
    return bool(response.get("success") or response.get("ok"))


def _tool_explizit_fehlgeschlagen(tool: dict) -> bool:
    if tool.get("ok") is False or tool.get("success") is False or tool.get("error"):
        return True
    dispatch = tool.get("dispatch") if isinstance(tool.get("dispatch"), dict) else {}
    response = dispatch.get("response") if isinstance(dispatch.get("response"), dict) else {}
    return response.get("success") is False or response.get("ok") is False


def _tool_art(tool: dict) -> str:
    name = _tool_name(tool)
    for art, teile in _WRITE_PARTS.items():
        if any(teil in name for teil in teile):
            return art
    return ""


def _evidenz(manifest: dict) -> dict[str, bool]:
    tools = _tools(manifest)
    return {
        "book": _marker_ok(manifest, "lastBook")
        or any(_tool_art(t) == "book" and _tool_ok(t) for t in tools),
        "cancel": _marker_ok(manifest, "lastCancel")
        or any(_tool_art(t) == "cancel" and _tool_ok(t) for t in tools),
        "move": _marker_ok(manifest, "lastMove")
        or any(_tool_art(t) == "move" and _tool_ok(t) for t in tools),
        "note": _marker_ok(manifest, "lastNote")
        or bool(_s(manifest.get("praxisNotiz")))
        or any(_tool_art(t) == "note" and _tool_ok(t) for t in tools),
        "transfer": _marker_ok(manifest, "lastTransfer")
        or bool(manifest.get("weiterleitungZiel"))
        or any(_tool_art(t) == "transfer" and _tool_ok(t) for t in tools)
        or any(bool(z.get("transfer")) for z in _zuege(manifest)),
        "patient": _marker_ok(manifest, "lastCreate")
        or any(_tool_art(t) == "patient" and _tool_ok(t) for t in tools),
        "phone": any(_tool_art(t) == "phone" and _tool_ok(t) for t in tools),
    }


def _offene_frage(manifest: dict) -> str:
    sammler = manifest.get("sammler") if isinstance(manifest.get("sammler"), dict) else {}
    return _s(sammler.get("frage"))


def _wiederholungen(outputs: Iterable[str]) -> tuple[int, str]:
    fragen: Counter[str] = Counter()
    for text in outputs:
        for satz in re.split(r"(?<=[?])\s+", text):
            if "?" not in satz:
                continue
            norm = re.sub(r"[^a-z0-9]+", " ", _fold(satz)).strip()
            if len(norm) >= 8:
                fragen[norm] += 1
    if not fragen:
        return 0, ""
    text, n = fragen.most_common(1)[0]
    return n, text[:100]


def _erfolg_claims(outputs: Iterable[str]) -> set[str]:
    blob = _fold("\n".join(outputs))
    return {art for art, muster in _ERFOLG.items() if muster.search(blob)}


def _failed_writes(manifest: dict, evidenz: dict[str, bool]) -> list[str]:
    failed: set[str] = set()
    for tool in _tools(manifest):
        art = _tool_art(tool)
        if art and _tool_explizit_fehlgeschlagen(tool) and not evidenz.get(art, False):
            failed.add(art)
    last_book = manifest.get("lastBook")
    if (
        isinstance(last_book, dict)
        and not _marker_ok(manifest, "lastBook")
        and not evidenz.get("book", False)
    ):
        failed.add("book")
    return sorted(failed)


def _praxis(manifest: dict) -> str:
    tenant = manifest.get("tenant") if isinstance(manifest.get("tenant"), dict) else {}
    for value in (
        manifest.get("tenantId"), tenant.get("id"), tenant.get("tenantId"),
        tenant.get("_id"),
    ):
        folded = _fold(value)
        if folded:
            return folded
    praxis = _fold(
        tenant.get("praxisName") or tenant.get("praxisNameMelde")
        or manifest.get("praxisName")
    )
    if praxis:
        for name in ("blessing", "thaler", "ruether", "meddent"):
            if name in praxis:
                return name
    gruss = _fold((_outputs(manifest) or [""])[0])
    for name in ("blessing", "thaler", "ruether", "meddent"):
        if name in gruss:
            return name
    if "medical center" in gruss or "zahnaerzte im" in gruss:
        return "meddent"
    return "unbekannt"


def _deterministische_stichprobe(session_id: str, anteil: float = 0.10) -> bool:
    anteil = max(0.0, min(1.0, float(anteil)))
    wert = int(hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:8], 16)
    return wert / 0xFFFFFFFF < anteil


@dataclass
class Bewertung:
    sessionId: str
    startedAt: str
    praxis: str
    klasse: str
    gewertet: bool
    gruende: list[str]
    reibungen: list[str]
    evidenz: list[str]
    anruferZuege: int
    substantielleZuege: int
    dauerMs: int
    manuellPruefen: bool


def bewerten(manifest: dict, *, session_id: str = "") -> Bewertung:
    sid = _s(session_id or manifest.get("id")) or "unbekannt"
    start = _s(manifest.get("startedAt"))
    praxis = _praxis(manifest)
    inputs = _inputs(manifest)
    substanziell = substantielle_inputs(manifest)
    outputs = _outputs(manifest)
    blob_out = "\n".join(outputs)
    dauer_ms = int(manifest.get("dauerMs") or 0)
    evidenz_map = _evidenz(manifest)
    evidenz = sorted(k for k, v in evidenz_map.items() if v)
    claims = _erfolg_claims(outputs)
    write_fails = _failed_writes(manifest, evidenz_map)
    repeat_n, repeat_text = _wiederholungen(outputs)
    unklar_n = sum(1 for text in outputs if _UNKLAR_RE.search(text))
    presence_n = sum(1 for text in outputs if _PRESENCE_RE.search(text))
    sonst_n = sum(1 for text in outputs if _SONST_RE.search(text))
    hard: list[str] = []
    reibung: list[str] = []

    if not substanziell:
        return Bewertung(
            sessionId=sid, startedAt=start, praxis=praxis, klasse="aufleger",
            gewertet=False, gruende=["kein_substanzieller_anrufersatz"],
            reibungen=[], evidenz=evidenz, anruferZuege=len(inputs),
            substantielleZuege=0, dauerMs=dauer_ms, manuellPruefen=False,
        )

    for art in write_fails:
        hard.append(f"write_fehlgeschlagen:{art}")
    for claim in sorted(claims):
        if not evidenz_map.get(claim, False):
            hard.append(f"erfolg_ohne_beweis:{claim}")
    if unklar_n >= 3:
        hard.append(f"unklar_schleife:{unklar_n}")
    elif unklar_n:
        reibung.append(f"unklar:{unklar_n}")
    if presence_n >= 3:
        hard.append(f"presence_schleife:{presence_n}")
    elif presence_n:
        reibung.append(f"presence:{presence_n}")
    if sonst_n >= 3:
        hard.append(f"sonst_noch_schleife:{sonst_n}")
    elif sonst_n:
        reibung.append(f"sonst_noch:{sonst_n}")
    if repeat_n >= 3:
        hard.append(f"frage_wiederholt:{repeat_n}:{repeat_text}")
    elif repeat_n == 2:
        reibung.append(f"frage_wiederholt:2:{repeat_text}")
    if any(_NEUE_RE.search(text) for text in outputs):
        reibung.append("eisbrecher_neue")
    if any(_SERMON_RE.search(text) for text in outputs):
        reibung.append("anmeldung_sermon")
    identitaet_n = sum(1 for text in outputs if _IDENTITAET_RE.search(text))
    if identitaet_n >= 2:
        reibung.append("identitaets_dopplung")
    kalender_down = sum(1 for text in outputs if _KALENDER_DOWN_RE.search(text))
    if kalender_down >= 2:
        reibung.append(f"kalender_down:{kalender_down}")
    for art in ("book", "cancel", "move", "note", "phone", "patient", "transfer"):
        if evidenz_map.get(art) and any(
            _tool_art(tool) == art and _tool_explizit_fehlgeschlagen(tool)
            for tool in _tools(manifest)
        ):
            reibung.append(f"write_retry:{art}")

    # Echte Schreib-/Transferergebnisse sind die staerkste Evidenz. Eine
    # Praxisnotiz ist ein ehrlicher Abschluss, aber bewusst hoechstens "gut".
    hartes_ergebnis = any(evidenz_map[k] for k in ("book", "cancel", "move", "transfer"))
    notiz_ergebnis = evidenz_map["note"]
    regel_antwort = any(_RULE_ANSWER_RE.search(_fold(text)) for text in outputs)
    offen = _offene_frage(manifest)
    # Ein erfolgreiches Lesen eines bestehenden Termins / Praxiswissens ist
    # fuer automatische "super"-Bewertung nicht stark genug: mindestens gut
    # plus manuelle Stichprobe, ausser ein Write/Transfer beweist das Ergebnis.
    lese_ok = any(
        _tool_ok(tool)
        and any(x in _tool_name(tool) for x in (
            "findpatientappointments", "patientlastdoctor", "getfreetimeslots",
        ))
        for tool in _tools(manifest)
    )

    if hard:
        klasse = "fehlerhaft"
        gruende = hard
    elif hartes_ergebnis:
        if not reibung:
            klasse, gruende = "super", ["belegter_abschluss"]
        elif len(reibung) == 1:
            klasse, gruende = "gut", ["belegter_abschluss_mit_reibung"]
        else:
            klasse, gruende = "durchwachsen", ["belegter_abschluss_aber_zaeh"]
    elif notiz_ergebnis:
        if len(reibung) <= 1:
            klasse, gruende = "gut", ["ehrlicher_notiz_abschluss"]
        else:
            klasse, gruende = "durchwachsen", ["notiz_abschluss_aber_zaeh"]
    elif regel_antwort or (lese_ok and not offen):
        if len(reibung) <= 1:
            klasse, gruende = "gut", ["plausibel_geloeste_auskunft"]
        else:
            klasse, gruende = "durchwachsen", ["auskunft_aber_zaeh"]
    elif len(substanziell) <= 2 and (dauer_ms <= 90_000 or len(inputs) <= 3):
        klasse, gruende = "unvollstaendig", ["anliegen_frueh_abgebrochen"]
    else:
        klasse, gruende = "durchwachsen", ["kein_belegter_abschluss"]

    # Nie unbesehen automatisch hochjubeln: alle plausiblen, aber nicht
    # tool-belegten Auskuenfte sowie deterministische 10 % der Super-Faelle
    # gehen in die Gegenhoer-Stichprobe.
    manuell = bool(
        (klasse == "super" and _deterministische_stichprobe(sid))
        or (klasse == "gut" and (regel_antwort or lese_ok) and not hartes_ergebnis)
    )
    return Bewertung(
        sessionId=sid, startedAt=start, praxis=praxis, klasse=klasse,
        gewertet=True, gruende=gruende, reibungen=reibung, evidenz=evidenz,
        anruferZuege=len(inputs), substantielleZuege=len(substanziell),
        dauerMs=dauer_ms, manuellPruefen=manuell,
    )


def _prozent(n: int, gesamt: int) -> float:
    return round(100.0 * n / gesamt, 1) if gesamt else 0.0


def _gruppe(rows: list[Bewertung]) -> dict[str, Any]:
    gewertet = [row for row in rows if row.gewertet]
    counts = Counter(row.klasse for row in gewertet)
    super_n = counts["super"]
    gut_n = counts["gut"]
    return {
        "gesamt": len(rows),
        "aufleger": len(rows) - len(gewertet),
        "gewertet": len(gewertet),
        "klassen": {
            klasse: {"n": counts[klasse], "pct": _prozent(counts[klasse], len(gewertet))}
            for klasse in KLASSEN
        },
        "superPct": _prozent(super_n, len(gewertet)),
        "superPlusGutPct": _prozent(super_n + gut_n, len(gewertet)),
        "ziel": {
            "mindestens50": len(gewertet) >= 50,
            "super40": _prozent(super_n, len(gewertet)) >= ZIEL_SUPER,
            "superPlusGut80": _prozent(super_n + gut_n, len(gewertet))
            >= ZIEL_MINDESTENS_GUT,
        },
    }


def bericht(rows: list[Bewertung], *, zeitzone: str = "Europe/Berlin") -> dict[str, Any]:
    tz = ZoneInfo(zeitzone)
    pro_praxis: dict[str, list[Bewertung]] = defaultdict(list)
    pro_stunde: dict[str, list[Bewertung]] = defaultdict(list)
    for row in rows:
        pro_praxis[row.praxis].append(row)
        start = _dt(row.startedAt)
        if start:
            pro_stunde[start.astimezone(tz).strftime("%Y-%m-%d %H:00")].append(row)
    return {
        "rubrikVersion": 1,
        "zeitzone": zeitzone,
        "gesamt": _gruppe(rows),
        "praxen": {name: _gruppe(pro_praxis[name]) for name in sorted(pro_praxis)},
        "stunden": {name: _gruppe(pro_stunde[name]) for name in sorted(pro_stunde)},
        "manuelleStichprobe": [
            row.sessionId for row in rows if row.gewertet and row.manuellPruefen
        ],
        "sessions": [asdict(row) for row in rows],
    }


def _grenzen(
    datum: str | None,
    seit: str | None,
    bis: str | None,
    zeitzone: str,
) -> tuple[datetime, datetime]:
    tz = ZoneInfo(zeitzone)
    if datum:
        tag = date.fromisoformat(datum)
    else:
        tag = datetime.now(tz).date()
    start = datetime.combine(tag, time.min, tzinfo=tz).astimezone(timezone.utc)
    ende = datetime.combine(tag, time.max, tzinfo=tz).astimezone(timezone.utc)
    if seit:
        start = _dt(seit) or start
    if bis:
        ende = _dt(bis) or ende
    return start, ende


def manifests(
    root: Path,
    *,
    start: datetime,
    ende: datetime,
    tenant: str = "",
    tests: bool = False,
) -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    if not root.is_dir():
        return rows
    for ordner in root.iterdir():
        pfad = ordner / "anruf.json"
        if not pfad.is_file():
            continue
        try:
            manifest = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        wann = _dt(manifest.get("startedAt"))
        if not wann or wann < start or wann > ende:
            continue
        if manifest.get("testAnruf") and not tests:
            continue
        if tenant and _praxis(manifest) != _fold(tenant):
            continue
        rows.append((ordner.name, manifest))
    rows.sort(key=lambda item: _dt(item[1].get("startedAt")) or start)
    return rows


def _text_ausgeben(report: dict[str, Any]) -> None:
    gesamt = report["gesamt"]
    print(
        f"gesamt={gesamt['gesamt']} aufleger={gesamt['aufleger']} "
        f"gewertet={gesamt['gewertet']} super={gesamt['superPct']:.1f}% "
        f"super+gut={gesamt['superPlusGutPct']:.1f}%"
    )
    for name, gruppe in report["praxen"].items():
        print(
            f"{name}: n={gruppe['gewertet']} super={gruppe['superPct']:.1f}% "
            f"super+gut={gruppe['superPlusGutPct']:.1f}% "
            f"fehler={gruppe['klassen']['fehlerhaft']['pct']:.1f}%"
        )
    print("klassen:")
    for klasse in KLASSEN:
        eintrag = gesamt["klassen"][klasse]
        print(f"  {klasse:16} {eintrag['n']:4}  {eintrag['pct']:5.1f}%")
    if report["manuelleStichprobe"]:
        print("manuell_pruefen:", ", ".join(report["manuelleStichprobe"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evidenzbasierter Tages-Scorer (read-only)")
    parser.add_argument(
        "--root", type=Path,
        default=Path("/app/.data/anrufe/bianca")
        if Path("/app").is_dir()
        else Path(".data/anrufe/bianca"),
    )
    parser.add_argument("--datum", help="Lokaler Kalendertag, YYYY-MM-DD")
    parser.add_argument("--seit", help="ISO-Zeitpunkt; ueberschreibt Tagesbeginn")
    parser.add_argument("--bis", help="ISO-Zeitpunkt; ueberschreibt Tagesende")
    parser.add_argument("--zeitzone", default="Europe/Berlin")
    parser.add_argument("--tenant", default="", help="Optional: blessing/thaler/meddent/ruether")
    parser.add_argument("--tests", action="store_true", help="Testanrufe mitwerten")
    parser.add_argument("--json", type=Path, help="Bericht zusaetzlich als JSON schreiben")
    parser.add_argument("--nur-json", action="store_true")
    args = parser.parse_args(argv)

    start, ende = _grenzen(args.datum, args.seit, args.bis, args.zeitzone)
    geladen = manifests(
        args.root, start=start, ende=ende, tenant=args.tenant, tests=args.tests
    )
    rows = [bewerten(manifest, session_id=sid) for sid, manifest in geladen]
    report = bericht(rows, zeitzone=args.zeitzone)
    report["zeitraum"] = {"von": start.isoformat(), "bis": ende.isoformat()}
    report["root"] = str(args.root)
    if args.json:
        args.json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.nur_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _text_ausgeben(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
