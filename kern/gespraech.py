"""Talk-Schicht: Nebenthemen mit Gravity und Gespraechs-Floor — fuer BEIDE Stimmen.

Abgeschrieben von Demo-Claras COS (F:\\Pickadoc-Demo\\demo-clara\\services\\
demo_cos.py, Stand 27.08.2026) — dieses Repo ist autark, deshalb kopiert statt
importiert, und auf den Telefon-Fall eingedampft (Chef 27.08.2026: "lisa und
bianca sollen abschweifen koennen ohne den faden zu verlieren").

Zwei Spuren, eine Stimme:

- JOB ist die deterministische Maschine (bianca/flow, bianca/verwalten,
  lisa/identitaet). Sie bleibt alleinige Autoritaet fuer Termine, Namen,
  Nummern und spricht wie bisher ZUERST — an ihr aendert diese Schicht NICHTS.
- TALK ist das Gespraech daneben. Jeder Anrufer-Satz wird abgehoert:
  Inhaltswoerter ausserhalb des Job-Vokabulars werden Themen mit GRAVITY.
  Wer erzaehlt oder nachfragt, bekommt den Floor — das LLM darf dann
  ausfuehrlich mitreden, und der Frage-Anker (bianca/agent._nachbessern)
  bleibt STUMM, solange der Faden traegt. Laesst der Anrufer los, gibt es
  EINE Bruecke zurueck zur offenen Job-Frage; danach gehoert der Mund wieder
  der Maschine.

Floors:
  job      kein Nebenthema — Maschine und Frage-Anker wie bisher
  blended  beilaeufige Erwaehnung: 1-2 warme Saetze, dann der offene Schritt
  talk     Thema hat den Floor: mitreden, KEIN Frage-Anker in diesem Zug
  zurueck  Thema gerade beendet: EIN Brueckensatz + offene Frage (einmal)

Der Sammler/Auftrag wird hier NIE veraendert — nur gelesen. Kein Netz, kein
LLM: reine Zustandspflege, JSON-tauglich (Listen statt Sets in der Sitzung).

Notaus: TALK_SCHICHT=0 (Umgebungsvariable) => Verhalten wie vor dem
27.08.2026 — jeder Zug ist job, der Anker feuert wie frueher.
"""

from __future__ import annotations

import os
import re
from typing import Any

JOB, BLENDED, TALK, ZURUECK = "job", "blended", "talk", "zurueck"

# Gravity-Konstanten — Werte wie in Demo-Claras COS (bewaehrt seit 22.08.2026).
G_START_USER = 0.30    # beilaeufig erwaehnt
G_START_PULL = 0.60    # erzaehlt/erfragt -> sofort volles Gespraech
G_WIEDER = 0.30        # jede weitere Erwaehnung zieht das Thema hoch
G_DECAY = 0.10         # pro gesprochenem Zug ohne Erwaehnung
G_CAP = 0.85           # Nebenthema schlaegt nie die dringende Hauptspur
G_SOCIAL = 0.60        # ab hier gehoert der Floor dem Thema
G_BLENDED = 0.30       # ab hier ein warmer Halbsatz im Job-Zug
G_WEG = 0.10           # darunter faellt das Thema aus dem Gedaechtnis
FADEN_MAX_ZUEGE = 8    # Notleine: Talk-Zuege ohne frische Nahrung


def enabled() -> bool:
    return os.environ.get("TALK_SCHICHT", "1").strip().lower() not in ("0", "false", "no")


# Job-Vokabular: Saetze mit diesem Stoff sind Task — aus ihnen entsteht NIE
# ein neues Nebenthema (ein Nachname im Buchungssatz ist kein Smalltalk).
_JOB_RE = re.compile(
    r"termin\w*|uhrzeit|\buhr\b|buch\w*|verschieb\w*|verleg\w*|absag\w*|"
    r"storn\w*|kalender|vormittag\w*|nachmittag\w*|morgens|abends|"
    r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|"
    r"übermorgen|uebermorgen|\bmorgen\b|n[aä]chste\s+woche|"
    r"nummer\w*|handy\w*|telefon\w*|doktor|praxis|behandler|"
    r"buchstabier\w*|eintrag\w*|\bakte\b|besuchsgrund",
    re.I,
)

# Schmerz/Notfall reisst den Fokus SOFORT zurueck zum Job (wie Demo-COS).
_DRINGEND_RE = re.compile(
    r"schmerz\w*|\bweh\b|\baua+\b|notfall|dringend|blutet|geschwollen|abgebrochen",
    re.I,
)

# Genervtheit (Chef 28.08.2026): einmal entschuldigen, dann nur noch liefern.
_GENERVT_RE = re.compile(
    r"jetzt\s+machen\s+sie\s+mal|das\s+dauert\s+mir|zu\s+lange|"
    r"ich\s+habe\s+nicht\s+ewig|ohne\s+umschweife|reicht\s+(jetzt|auch)|"
    r"kann\s+das\s+(nicht\s+)?schneller|sind\s+sie\s+noch\s+da|"
    r"das\s+nervt|geht\s+es\s+auch\s+k[uü]rzer|kommen\s+sie\s+zur\s+sache|"
    r"nicht\s+schon\s+wieder\s+(fragen|die\s+frage)",
    re.I,
)

# Loslassen: der Anrufer beendet das Nebenthema ausdruecklich ("na gut",
# "okay dann", "wo waren wir") — dann EINE Bruecke und zurueck zum Job.
_LOSLASS_RE = re.compile(
    r"^\s*(?:(?:ja|jaja|na|nun|also|gut|okay|ok|schon|dann)\b[\s,]*)*"
    r"(?:gut|okay|ok|passt(?:\s+schon)?|alles\s+klar|in\s+ordnung|egal|"
    r"weiter|zur(?:ück|ueck)|zur\s+sache|wo\s+waren\s+wir|jedenfalls|"
    r"wie\s+auch\s+immer|machen\s+wir\s+weiter|weiter\s+im\s+text|"
    r"genug\s+davon|anderes\s+thema)"
    r"\s*[.!?…]*\s*$",
    re.I,
)

# Fuell-/Hoeflichkeits-/Job-Woerter (>= 5 Zeichen — kuerzere filtert die
# Laengenregel), die NIE ein Gespraechsthema tragen.
_STOP = frozenset((
    "nicht", "haben", "hatte", "hatten", "haette", "hätte", "haetten", "hätten",
    "werden", "wurde", "wurden", "wuerde", "würde", "wuerden", "würden",
    "koennen", "können", "koennte", "könnte", "koennten", "könnten",
    "muessen", "müssen", "musste", "muesste", "müsste", "sollen", "sollte",
    "sollten", "wollen", "wollte", "wollten", "moechte", "möchte", "moechten",
    "möchten", "machen", "macht", "sagen", "sagte", "geben", "brauche",
    "brauchen", "bräuchte", "brauchte", "einen", "einem", "einer", "eines",
    "dieser", "diese", "dieses", "diesem", "jetzt", "heute", "schon", "immer",
    "wieder", "gerade", "vielleicht", "eigentlich", "wirklich", "natürlich",
    "natuerlich", "irgendwie", "jedenfalls", "übrigens", "uebrigens",
    "sowieso", "genau", "richtig", "stimmt", "danke", "gerne", "bitte",
    "hallo", "super", "prima", "klasse", "perfekt", "wunderbar", "passt",
    "alles", "nichts", "etwas", "okay", "wiederhören", "wiederhoeren",
    "tschüss", "tschuess", "entschuldigung", "verzeihung", "moment",
    "sekunde", "augenblick", "sonst", "trotzdem", "sicher", "bisschen",
    "meine", "meinen", "meiner", "meinem", "unser", "unsere", "ihren",
    "ihrer", "ihrem", "ihnen", "seine", "seinen", "seiner", "keine",
    "keinen", "wissen", "weisst", "weißt", "gesagt", "stimmen", "glaube",
    "glauben", "denke", "denken", "finde", "finden", "verstehe",
    "verstehen", "verstanden", "hoeren", "hören", "sehen", "gesehen",
    "irgendwas", "irgendwann", "irgendwo",
))


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _inhaltsworte(low: str) -> set[str]:
    """Inhaltswoerter (>= 5 Zeichen) ohne Fuell- und Job-Vokabular."""
    worte = re.findall(r"[a-zäöüß]{5,}", low)
    return {w for w in worte if w not in _STOP and not _JOB_RE.fullmatch(w)}


def ist_user_pull(text: str) -> bool:
    """Lange Leine nur, wenn das Gegenueber wirklich erzaehlt oder nachhakt."""
    t = _s(text)
    if len(t) < 36 or len(t.split()) < 6:
        return False
    return True


def stand(sit: dict) -> dict:
    st = sit.get("talk")
    if not isinstance(st, dict):
        st = {}
        sit["talk"] = st
    st.setdefault("gravity", {})
    st.setdefault("woerter", {})
    st.setdefault("stack", [])
    st.setdefault("floor", JOB)
    st.setdefault("bruecke", "")
    st.setdefault("frisch", [])
    st.setdefault("letzterSatz", "")
    st.setdefault("letzteRoute", {})
    st.setdefault("genervt", False)
    st.setdefault("entschuldigt", False)
    return st


def floor(sit: dict) -> str:
    return _s((sit.get("talk") or {}).get("floor")) or JOB


def traegt_thema(sit: dict, text: str) -> bool:
    """Traegt dieser Satz Gespraechsstoff (aktives oder neues Nebenthema)?

    Rein lesend — fuer die Fluesse: solche Saetze zaehlen NIE als Leerlauf
    Richtung Eskalation, sie gehen ans LLM (Talk-Schicht antwortet).
    """
    if not enabled():
        return False
    if (sit.get("talk") or {}).get("genervt"):
        return False
    low = _s(text).casefold()
    worte = _inhaltsworte(low)
    if not worte:
        return False
    st = sit.get("talk") or {}
    for thema, ws in (st.get("woerter") or {}).items():
        if thema in worte or (set(ws or []) & worte):
            return True
    if _DRINGEND_RE.search(low):
        return False
    # Neues Thema entsteht nur aus Saetzen OHNE Job-Stoff.
    return not _JOB_RE.search(low)


def _stack_push(st: dict, thema: str) -> None:
    for eintrag in st["stack"]:
        if eintrag.get("thema") == thema:
            return
    st["stack"].append({"thema": thema, "zuege": 0})
    # Maximale Tiefe 2 (wie Demo-COS): das aelteste verschachtelte faellt.
    if len(st["stack"]) > 2:
        st["stack"] = st["stack"][-2:]


def routen(sit: dict, text: str, *, ernte: list | tuple = (),
           job_gesprochen: bool = False, job_aktiv: bool = False) -> dict[str, Any]:
    """Ein Anrufer-Satz -> Floor-Entscheidung. Faellt fachlich NIE etwas.

    ernte           = frisch gefuellte Sammler-Felder (Bianca) — Task-Signal.
    job_gesprochen  = die Maschine hat diesen Satz schon beantwortet: nur
                      Wieder-Erkennung pflegen, Floor bleibt job.
    job_aktiv       = eine Buchung/Verwaltung laeuft (ernte zaehlt als Task).
    """
    st = stand(sit)
    if not enabled():
        st["floor"] = JOB
        return {"floor": JOB, "thema": "", "dringend": False}
    t = _s(text)
    low = t.casefold()

    # Idempotenz: derselbe Final direkt hintereinander (STT-Doppel) zieht
    # die Gravity nicht doppelt hoch.
    if t and t == st.get("letzterSatz") and st.get("letzteRoute"):
        return dict(st["letzteRoute"])

    def _fertig(route: dict) -> dict:
        st["letzterSatz"] = t
        st["letzteRoute"] = dict(route)
        st["floor"] = route["floor"]
        return route

    if _DRINGEND_RE.search(low):
        # Schmerz/Notfall: alle Nebenthemen fallen, der Job uebernimmt sofort.
        st["gravity"] = {}
        st["woerter"] = {}
        st["stack"] = []
        st["bruecke"] = ""
        st["frisch"] = []
        return _fertig({"floor": JOB, "thema": "", "dringend": True})

    if st.get("genervt") or _GENERVT_RE.search(low):
        # Ungeduld: Talk aus, Floor bleibt Job. EINMAL entschuldigen
        # (plan_block), danach nur noch den offenen Schritt liefern.
        st["genervt"] = True
        st["gravity"] = {}
        st["woerter"] = {}
        st["stack"] = []
        st["bruecke"] = ""
        st["frisch"] = []
        return _fertig({
            "floor": JOB, "thema": "", "dringend": False,
            "genervt": True, "entschuldigt": bool(st.get("entschuldigt")),
        })

    worte = _inhaltsworte(low)
    frisch: list[str] = []

    if job_gesprochen:
        # Maschine hat geantwortet — Themen nur wiedererkennen (damit ein
        # spaeterer Rueckgriff "wegen der Hochzeit ..." den Faden findet);
        # eine faellige Bruecke ist mit der Job-Antwort bedient.
        for thema in list(st["woerter"]):
            ws = set(st["woerter"].get(thema) or [])
            if thema in worte or (ws & worte):
                st["gravity"][thema] = min(
                    G_CAP, float(st["gravity"].get(thema, G_START_USER)) + G_WIEDER
                )
                st["woerter"][thema] = sorted(ws | worte)[:24]
                frisch.append(thema)
        st["bruecke"] = ""
        st["frisch"] = frisch
        return _fertig({"floor": JOB, "thema": "", "dringend": False})

    task_hit = bool(_JOB_RE.search(low)) or (job_aktiv and bool(ernte))

    thema = ""
    if worte:
        kandidaten = [
            k for k in st["woerter"]
            if k in worte or (set(st["woerter"].get(k) or []) & worte)
        ]
        if kandidaten:
            # Wieder-Erkennung schlaegt Neuanlage — das staerkste Thema zieht.
            thema = max(kandidaten, key=lambda k: float(st["gravity"].get(k, 0.0)))
            st["gravity"][thema] = min(
                G_CAP, float(st["gravity"].get(thema, G_START_USER)) + G_WIEDER
            )
            st["woerter"][thema] = sorted(set(st["woerter"].get(thema) or []) | worte)[:24]
        elif not task_hit:
            thema = max(sorted(worte), key=len)
            start = G_START_PULL if (ist_user_pull(t) or t.endswith("?")) else G_START_USER
            st["gravity"][thema] = start
            st["woerter"][thema] = sorted(worte)[:24]
        if thema:
            frisch.append(thema)

    # Loslassen ("na gut", "okay dann", "wo waren wir"): Faden zu, Bruecke.
    if not thema and st["stack"] and _LOSLASS_RE.match(t):
        top = st["stack"].pop()
        st["gravity"][_s(top.get("thema"))] = 0.2
        st["bruecke"] = ""
        st["frisch"] = []
        return _fertig({"floor": ZURUECK, "thema": _s(top.get("thema")), "dringend": False})

    # Kurze Fortsetzung ohne Inhaltswoerter ("Ja, wirklich!") haelt den
    # laufenden Faden — aber NUR, wenn er den Floor gerade schon hat.
    if not thema and not task_hit and not worte and st["stack"] and st.get("floor") == TALK:
        top = st["stack"][-1]
        if float(st["gravity"].get(_s(top.get("thema")), 0.0)) >= G_BLENDED:
            thema = _s(top.get("thema"))
            frisch.append(thema)

    g = float(st["gravity"].get(thema, 0.0)) if thema else 0.0
    if thema and g >= G_SOCIAL:
        f = BLENDED if task_hit else TALK
    elif thema and g >= G_BLENDED:
        f = BLENDED
    elif task_hit or not thema:
        f = JOB
    else:
        f = BLENDED

    if f == TALK:
        _stack_push(st, thema)
    if f == JOB and _s(st.get("bruecke")):
        # Ein Faden ist gerade verhungert: einmal sauber zurueckfuehren.
        thema = _s(st["bruecke"])
        st["bruecke"] = ""
        f = ZURUECK

    st["frisch"] = frisch
    return _fertig({"floor": f, "thema": thema, "dringend": False})


def nach_antwort(sit: dict) -> None:
    """Nach jedem gesprochenen Zug: Gravity verfaellt, kalte Faeden schliessen.

    Der Job-Zustand (Sammler, Phasen) wird hier NIE angefasst — nur der
    Gespraechs-Stack bewegt sich (wie Demo-COS nach_antwort).
    """
    st = sit.get("talk")
    if not isinstance(st, dict) or not enabled():
        return
    if st.get("genervt"):
        st["entschuldigt"] = True
    frisch = set(st.get("frisch") or [])
    gravity = st.setdefault("gravity", {})
    for k in list(gravity):
        if k not in frisch:
            gravity[k] = round(float(gravity[k]) - G_DECAY, 4)
        if float(gravity[k]) < G_WEG:
            del gravity[k]
            (st.get("woerter") or {}).pop(k, None)
            st["stack"] = [x for x in (st.get("stack") or []) if x.get("thema") != k]
    if st.get("stack"):
        top = st["stack"][-1]
        if st.get("floor") in (TALK, BLENDED):
            top["zuege"] = int(top.get("zuege") or 0) + 1
        g_top = float(gravity.get(_s(top.get("thema")), 0.0))
        kalt = (
            _s(top.get("thema")) not in frisch
            and g_top < G_SOCIAL
            and (st.get("floor") == JOB or int(top.get("zuege") or 0) >= FADEN_MAX_ZUEGE)
        )
        if kalt:
            st["stack"].pop()
            st["bruecke"] = _s(top.get("thema"))
            gravity[_s(top.get("thema"))] = 0.2
    if not st.get("stack") and st.get("floor") == TALK:
        st["floor"] = JOB
    st["frisch"] = []


# ---------------------------------------------------------------------------
# Response Planner: der eine Prompt-Block, in dem das LLM frei formulieren darf
# ---------------------------------------------------------------------------
_SCHUTZ = (
    "Dabei gilt: nichts erfinden — keine Termine, freien Zeiten, Zusagen oder "
    "Erledigungen aus dem Kopf, Preise NUR aus ZAHNMEDIZIN UND PREISE. Keine "
    "Diagnosen und keine individuellen Heilaussagen — allgemeines Wissen darfst "
    "du ruhig erklaeren. Keine Werkzeugnamen, keine Regieanweisungen."
)


def plan_block(route: dict, *, offene_frage: str = "", stimme: str = "bianca") -> str:
    """GESPRAECHSLAGE-Block fuer den Systemprompt — '' auf dem Job-Floor."""
    if route.get("genervt"):
        einmal = (
            "EINMAL kurz entschuldigen, dass es gedauert hat — danach NICHT nochmal."
            if not route.get("entschuldigt") else
            "Nicht noch einmal entschuldigen."
        )
        ziel = f"\u201e{offene_frage}\u201c" if _s(offene_frage) else "dem offenen nächsten Schritt"
        return (
            "GESPRÄCHSLAGE: Der Anrufer ist ungeduldig. "
            f"{einmal} Dann NUR noch {ziel} — keine Begleitsätze, "
            "keine Nebenthemen, kein Smalltalk. Ein kurzer Satz, dann die Frage. "
            + _SCHUTZ
        )
    f = _s(route.get("floor"))
    thema = _s(route.get("thema"))
    if _s(offene_frage):
        ziel_satz = f"der offenen Frage: \u201e{offene_frage}\u201c"
    elif stimme == "lisa":
        ziel_satz = "deinem Auftrag"
    else:
        ziel_satz = "der Frage, was du sonst noch fuer den Anrufer tun kannst"
    if f == TALK and thema:
        return (
            "GESPRÄCHSLAGE (dieser Block geht der Zwei-Satz-Regel vor): "
            f"Der Gespraechspartner hat \u201e{thema}\u201c auf den Tisch gelegt — geh JETZT "
            "ehrlich, konkret und mit eigenem Wissen darauf ein, wie eine warme, "
            "belesene Kollegin am Empfang. Auch auf Kurioses reagierst du echt "
            "(ueberrascht, amuesiert, interessiert), nie mit einer Floskel. "
            "Bleib bei DIESEM Thema, solange das Gegenueber es weiterzieht — "
            "kein Schwenk zum Termin, KEINE Terminfrage in diesem Zug. Zwei bis "
            "fuenf Saetze, gern eine echte Rueckfrage zum Thema. "
            + ("Der Auftrag bleibt bestehen: wiederhole ihn nicht, vergiss ihn nicht. "
               if stimme == "lisa" else "")
            + _SCHUTZ
        )
    if f == BLENDED and thema:
        return (
            "GESPRÄCHSLAGE: Der Gespraechspartner hat nebenbei "
            f"\u201e{thema}\u201c erwaehnt — wuerdige das ZUERST in ein bis zwei warmen, "
            "konkreten Saetzen (nicht nachplappern, nicht abbuegeln). Danach im "
            f"SELBEN Zug natuerlich weiter mit {ziel_satz} — neu formuliert, "
            "nie wortgleich wie zuvor. " + _SCHUTZ
        )
    if f == ZURUECK and thema:
        return (
            f"GESPRÄCHSLAGE: Das Thema \u201e{thema}\u201c ist besprochen. Verbinde es in "
            f"EINEM Halbsatz mit {ziel_satz} — ueber Nutzen oder Zeitbezug, nie "
            "\u201eSo, zurueck zu\u201c. Danach stellst du genau diese offene Frage, "
            "freundlich und in NEUEN Worten. " + _SCHUTZ
        )
    return ""


def budget(floor_name: str, *, genervt: bool = False) -> dict[str, Any]:
    """Token-/Temperatur-Budget je Floor — {} heisst: Job-Standard (90/0.3)."""
    if not enabled():
        return {}
    if genervt:
        return {"max_tokens": 70, "temperature": 0.2}
    if floor_name == TALK:
        return {"max_tokens": 240, "temperature": 0.6}
    if floor_name == BLENDED:
        return {"max_tokens": 150, "temperature": 0.5}
    if floor_name == ZURUECK:
        return {"max_tokens": 130, "temperature": 0.45}
    return {}
