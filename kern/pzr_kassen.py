"""PZR-Kassen-Wissen (Chef 08.09.2026): Praxispreis + Zuschuss-Tabelle.

Keine Vektor-Suche: 14 Kassen sind eine Nachschlag-Tabelle. Zahlen nur
von hier, nie geschätzt. Gesprochen immer „ungefähr“, nie „grob“.
Bei uns machen die Zahnärzte die Reinigung selbst — nicht Prophylaxehelferinnen.
Immer der Warnsatz: im Einzelfall kann das abweichen.
"""

from __future__ import annotations

import re
from typing import Any

PREIS_EURO = 120
PREIS_SATZ = (
    "Die professionelle Zahnreinigung kostet bei uns ungefähr "
    "einhundertzwanzig Euro."
)
PRAXIS_SATZ = (
    "Bei uns führen die Zahnärzte die Zahnreinigung selbst durch, "
    "nicht die Prophylaxehelferinnen."
)
KASSE_FRAGE = "Bei welcher Krankenkasse sind Sie versichert?"
DISCLAIMER = "Im Einzelfall kann das abweichen."

_PREIS_RE = re.compile(
    r"kostet|kosten|preis|teuer|zuschuss|übernimmt|uebernimmt|"
    r"zahlt\s+die|was\s+zahlt|was\s+uebernimm|was\s+übernimm|"
    r"krankenkasse|kasse\s+dazu",
    re.I,
)
_PZR_WORT_RE = re.compile(
    r"zahnreinigung|prophylaxe|\bpzr\b|zahnstein|reinigung",
    re.I,
)
_PRIVAT_RE = re.compile(r"\bprivat|beihilfe|privatversichert", re.I)
_WEISS_NICHT_RE = re.compile(
    r"weiß\s+(?:ich\s+)?nicht|weiss\s+(?:ich\s+)?nicht|keine\s+ahnung|"
    r"egal|weissnich|weißnich|keine\s+idee",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _norm(text: str) -> str:
    t = _s(text).lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


# id, Name, Aliase, sprechbarer Zuschuss (ohne Disclaimer, ohne Praxispreis).
KASSEN: tuple[dict[str, Any], ...] = (
    {
        "id": "ikk-innovation",
        "name": "IKK Innovationskasse",
        "alias": ("ikk innovationskasse", "innovationskasse"),
        "satz": (
            "Bei der IKK Innovationskasse gibt es in der Regel bis zu zweimal "
            "im Jahr einen Zuschuss, insgesamt bis ungefähr zweihundertfünfzig "
            "Euro im Jahr."
        ),
    },
    {
        "id": "big",
        "name": "BIG direkt gesund",
        "alias": ("big direkt gesund", "big direkt", "big"),
        "satz": (
            "Bei der BIG direkt gesund sind es in der Regel zweimal fünfundsiebzig "
            "Euro — ungefähr einhundertfünfzig Euro im Jahr."
        ),
    },
    {
        "id": "aok-hessen",
        "name": "AOK Hessen",
        "alias": ("aok hessen",),
        "satz": (
            "Bei der AOK Hessen sind es in der Regel zweimal sechzig Euro, "
            "plus Bonus möglich."
        ),
    },
    {
        "id": "kkh",
        "name": "KKH",
        "alias": ("kkh", "kaufmaennische", "kaufmännische"),
        "satz": (
            "Bei der KKH sind es in der Regel zweimal sechzig Euro — "
            "ungefähr einhundertzwanzig Euro im Jahr."
        ),
    },
    {
        "id": "bkk-exklusiv",
        "name": "BKK exklusiv",
        "alias": ("bkk exklusiv", "exklusiv"),
        "satz": (
            "Bei der BKK exklusiv sind es in der Regel zweimal sechzig Euro — "
            "ungefähr einhundertzwanzig Euro im Jahr."
        ),
    },
    {
        "id": "mobil",
        "name": "Mobil Krankenkasse",
        "alias": ("mobil krankenkasse", "mobil"),
        "satz": (
            "Bei der Mobil Krankenkasse sind es in der Regel zweimal sechzig Euro, "
            "oder einmal kostenlos im DentNet."
        ),
    },
    {
        "id": "aok-bayern",
        "name": "AOK Bayern",
        "alias": ("aok bayern",),
        "satz": (
            "Bei der AOK Bayern sind es ab fünfzehn Jahren in der Regel "
            "zweimal fünfzig Euro — ungefähr einhundert Euro im Jahr."
        ),
    },
    {
        "id": "bkk-firmus",
        "name": "BKK firmus",
        "alias": ("bkk firmus", "firmus"),
        "satz": (
            "Bei der BKK firmus gibt es in der Regel ein Budget bis ungefähr "
            "einhundert Euro, plus einmal kostenlos im DentNet."
        ),
    },
    {
        "id": "heimat",
        "name": "Heimat Krankenkasse",
        "alias": ("heimat krankenkasse", "heimat"),
        "satz": (
            "Bei der Heimat Krankenkasse sind es in der Regel einmal achtzig Euro, "
            "beim Vertragspartner oft die volle Übernahme."
        ),
    },
    {
        "id": "dak",
        "name": "DAK-Gesundheit",
        "alias": ("dak gesundheit", "dak"),
        "satz": (
            "Bei der DAK sind es in der Regel einmal sechzig Euro; "
            "in der Schwangerschaft oft die volle Übernahme über MamaPLUS."
        ),
    },
    {
        "id": "tk",
        "name": "Techniker Krankenkasse",
        "alias": ("techniker krankenkasse", "technikerkasse", "techniker", "tk"),
        "satz": (
            "Bei der Techniker Krankenkasse gibt es ab achtzehn in der Regel "
            "einmal ungefähr vierzig Euro."
        ),
    },
    {
        "id": "ikk-classic",
        "name": "IKK classic",
        "alias": ("ikk classic", "ikk klassik"),
        "satz": (
            "Bei der IKK classic sind es in der Regel einmal vierzig Euro, "
            "ab achtzehn zusätzlich einmal kostenlos im DentNet."
        ),
    },
    {
        "id": "aok-rheinland",
        "name": "AOK Rheinland/Hamburg",
        "alias": (
            "aok rheinland hamburg", "aok rheinland", "aok hamburg",
            "aok rheinland/hamburg",
        ),
        "satz": (
            "Bei der AOK Rheinland-Hamburg ist der Zuschuss eng begrenzt: "
            "ungefähr fünfunddreißig Euro, und volle Übernahme nur in der "
            "AOK-Zahnklinik Düsseldorf — nicht bei uns. Über den Bonus "
            "AOK-Vital plus oft extra bis sechzig Euro."
        ),
    },
    {
        "id": "barmer",
        "name": "BARMER",
        "alias": ("barmer ersatzkasse", "barmer"),
        "satz": (
            "Bei der Barmer gibt es den Zuschuss nur über gesammelte Bonuspunkte — "
            "bis ungefähr zweihundert Euro, aber nicht automatisch."
        ),
    },
)


def preis_und_kasse_frage() -> str:
    """Preis + Praxis-Hinweis + Kassenfrage. Nie „grob“."""
    return f"{PREIS_SATZ} {PRAXIS_SATZ} {KASSE_FRAGE}"


def disclaimer_satz() -> str:
    return DISCLAIMER


def ist_preisfrage(text: str) -> bool:
    """„Was kostet die?“, „Was übernimmt die Kasse?“ — PZR-Preis oder Zuschuss."""
    t = _s(text)
    if not t:
        return False
    if not _PREIS_RE.search(t):
        return False
    # Nacktes „was kostet die“ ohne Füllung/Krone: gilt, wenn der Kontext PZR ist
    # (prüft der Aufrufer). Hier reicht das Preiswort.
    return True


def hat_pzr_wort(text: str) -> bool:
    return bool(_PZR_WORT_RE.search(_s(text)))


def deute(text: str) -> dict[str, Any]:
    """Kasse aus dem Satz. Nie raten bei nacktem AOK/IKK/BKK.

    Rueckgabe: {id, name, satz} oder {id: privat|unbekannt|mehrdeutig, ...}.
    """
    t = _s(text)
    if not t:
        return {}
    if _WEISS_NICHT_RE.search(t) and not _PRIVAT_RE.search(t):
        return {
            "id": "unbekannt",
            "name": "",
            "satz": (
                "Kein Problem. Der Praxispreis liegt ungefähr bei einhundertzwanzig "
                "Euro; was Ihre Kasse dazugibt, klären wir beim Termin."
            ),
        }
    if _PRIVAT_RE.search(t):
        return {
            "id": "privat",
            "name": "privat",
            "satz": (
                "Als Privatversicherte hängt der Zuschuss von Ihrem Tarif ab. "
                "Der Praxispreis liegt ungefähr bei einhundertzwanzig Euro."
            ),
        }
    n = _norm(t)
    treffer: list[tuple[int, dict[str, Any]]] = []
    for k in KASSEN:
        for alias in k["alias"]:
            a = _norm(alias)
            if not a:
                continue
            if re.search(rf"(?<!\w){re.escape(a)}(?!\w)", n):
                treffer.append((len(a), k))
                break
    if treffer:
        treffer.sort(key=lambda x: x[0], reverse=True)
        k = treffer[0][1]
        return {"id": k["id"], "name": k["name"], "satz": k["satz"]}
    # Nackte Gruppe: Range, nicht raten.
    if re.search(r"(?<!\w)aok(?!\w)", n):
        return {
            "id": "mehrdeutig",
            "name": "AOK",
            "satz": (
                "Bei der AOK hängt der Zuschuss von Ihrer regionalen Kasse ab — "
                "ungefähr fünfunddreißig bis sechzig Euro, ein- oder zweimal im Jahr."
            ),
        }
    if re.search(r"(?<!\w)ikk(?!\w)", n):
        return {
            "id": "mehrdeutig",
            "name": "IKK",
            "satz": (
                "Bei der IKK kommt es auf die Kasse an: die classic gibt in der "
                "Regel einmal vierzig Euro, die Innovationskasse bis ungefähr "
                "zweihundertfünfzig Euro im Jahr."
            ),
        }
    if re.search(r"(?<!\w)bkk(?!\w)", n):
        return {
            "id": "mehrdeutig",
            "name": "BKK",
            "satz": (
                "Bei den Betriebskassen ist der Zuschuss unterschiedlich — "
                "oft einmal bis zweimal sechzig bis einhundert Euro im Jahr."
            ),
        }
    return {}


def auskunft(treffer: dict[str, Any] | None) -> str:
    """Sprechbare Kassen-Auskunft inkl. Disclaimer. Leer ohne Treffer."""
    if not treffer or not _s(treffer.get("satz")):
        return ""
    return f"{_s(treffer['satz'])} {DISCLAIMER}"


def unbekannt_satz() -> str:
    return (
        "Dazu habe ich gerade keine feste Zahl. Der Praxispreis liegt ungefähr "
        "bei einhundertzwanzig Euro; den Zuschuss klären wir beim Termin. "
        f"{DISCLAIMER}"
    )


def prompt_block() -> str:
    """Kompakte Wissensbasis für den LLM-Prompt — Zahlen nie erfinden."""
    zeilen = [
        "ZAHNREINIGUNG / PZR (Wissensbasis — NUR diese Zahlen, nie schätzen):",
        f"- Praxispreis ungefähr {PREIS_EURO} Euro. Immer „ungefähr“, nie eine glatte Zahl als fest behaupten.",
        f"- {PRAXIS_SATZ}",
        "- Gesetzliche Kassen übernehmen 1–2× im Jahr einen Zuschuss, je nach Kasse.",
        f"- Immer warnen: „{DISCLAIMER}“",
        "- Preis und Zuschuss NUR nennen, wenn der Anrufer danach fragt — "
        "nicht mit den Kosten ins Haus fallen.",
        "- Kassen-Zuschüsse (ungefähr):",
    ]
    kurz = {
        "ikk-innovation": "bis 2×, bis 250 Euro/Jahr",
        "big": "2× 75 Euro = 150 Euro",
        "aok-hessen": "2× 60 Euro, plus Bonus möglich",
        "kkh": "2× 60 Euro = 120 Euro",
        "bkk-exklusiv": "2× 60 Euro = 120 Euro",
        "mobil": "2× 60 Euro oder 1× kostenlos im DentNet",
        "aok-bayern": "2× 50 Euro ab 15 = 100 Euro",
        "bkk-firmus": "bis 100 Euro plus 1× kostenlos im DentNet",
        "heimat": "1× 80 Euro, Vertragspartner oft voll",
        "dak": "1× 60 Euro; Schwangere oft 100 % MamaPLUS",
        "tk": "1× 40 Euro ab 18",
        "ikk-classic": "1× 40 Euro, ab 18 plus 1× DentNet",
        "aok-rheinland": "1× 35 Euro, eng begrenzt; voll nur AOK-Zahnklinik Düsseldorf",
        "barmer": "bis 200 Euro nur mit Bonuspunkten, nicht automatisch",
    }
    for k in KASSEN:
        zeilen.append(f"  · {k['name']}: {kurz[k['id']]}")
    zeilen.append(
        "- Unbekannte Kasse oder nur „AOK“/„IKK“/„BKK“: ehrlich die Spanne "
        "oder „klären wir beim Termin“ — nie eine konkrete Zahl erfinden."
    )
    return "\n".join(zeilen)


def fuer_wissen(wissen: dict | None) -> str:
    """Nur anhängen, wenn die Praxis Zahnreinigung-Preise führt (nicht Derma)."""
    w = wissen if isinstance(wissen, dict) else {}
    if w.get("pzrKassen") is False:
        return ""
    if w.get("pzrKassen") is True:
        return prompt_block()
    preise = " ".join(_s(p) for p in (w.get("preise") or []))
    if "zahnreinigung" in preise.lower():
        return prompt_block()
    return ""
