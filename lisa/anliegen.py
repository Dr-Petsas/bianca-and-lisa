"""Der Grund des Anrufs als sprechfertiger Satz — vorab, nicht im Gespraech.

Waehrend Lisa die Begruessung spricht und der Angerufene "ja" sagt, hat der
Rechner mehrere Sekunden Luft. Die nutzen wir: aus dem Auftrag (Freitext des
Chefs, oft mit Regieanweisungen wie "freundlich anbieten und nach vormittags
fragen") wird EIN sprechbarer Satz plus EINE Frage.

Ohne das las Lisa Auftragsfragmente vor ("Neuen Kontrolltermin vereinbaren").
Faellt das Modell aus, greift notfalltext() — deterministisch, ohne Netz.
"""

from __future__ import annotations

from lisa import llm
from lisa.greeting import erste_botschaft
from lisa.mission import ist_termin_auftrag


def _s(v: object) -> str:
    return " ".join(str(v or "").split()).strip()


def notfalltext(sit: dict) -> str:
    """Ohne Modell: Auftrag knapp nennen, Terminfrage anhaengen."""
    tenant = sit.get("tenant") or {}
    arzt = _s(tenant.get("behandler"))
    auftrag = _s(sit.get("auftrag"))
    kopf = f"Ich rufe im Auftrag von {arzt} an." if arzt else "Ich rufe aus der Praxis an."
    botschaft = erste_botschaft(auftrag)
    teile = [kopf]
    if botschaft:
        teile.append(botschaft if botschaft.endswith((".", "!", "?")) else botschaft + ".")
    if ist_termin_auftrag(auftrag):
        teile.append("Passt es Ihnen vormittags oder nachmittags besser?")
    return " ".join(teile)


def _auftrag_prompt(sit: dict) -> list[dict]:
    tenant = sit.get("tenant") or {}
    arzt = _s(tenant.get("behandler"))
    praxis = _s(tenant.get("praxisName"))
    auftrag = _s(sit.get("auftrag"))
    system = (
        "Du formulierst EINEN Gesprächseinstieg für eine Telefonassistentin einer "
        "Zahnarztpraxis. Der Angerufene hat gerade bestätigt, dass er die richtige "
        "Person ist. Begrüßung und Namen hat die Assistentin schon gesagt — die "
        "wiederholst du NICHT.\n"
        "REGELN\n"
        f"- Beginne mit „Ich rufe im Auftrag von {arzt} an" + (
            "“, danach der Grund." if arzt else "“ nur wenn ein Arzt genannt ist."
        ) + "\n"
        "- Nenne den konkreten Grund mit den Fakten aus dem Auftrag (Zahl, Zeitraum, "
        "Anlass). Keine Leerformeln, keine Regieanweisungen.\n"
        "- Höchstens zwei kurze Sätze, dann GENAU EINE Frage. Danach Schluss.\n"
        "- Uhrzeiten und Daten in Worten, nie als Ziffern.\n"
        "- Keine Terminvorschläge mit konkreten Uhrzeiten erfinden.\n"
        "- Antworte NUR mit dem gesprochenen Text, ohne Anführungszeichen.\n"
        f"PRAXIS: {praxis}\nBEHANDLER: {arzt or '—'}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"AUFTRAG DES CHEFS:\n{auftrag}"},
    ]


def bauen(sit: dict) -> str:
    """Einmal pro Sitzung, im Hintergrund. Bei Fehler: leer (Notfalltext greift)."""
    if not _s(sit.get("auftrag")):
        return ""
    out = llm.chat(_auftrag_prompt(sit), None, temperature=0.2, max_tokens=110)
    if not out.get("ok"):
        return ""
    text = _s(out.get("text")).strip('"“” ')
    if not text or len(text) > 420:
        return ""
    return text


def vorbereiten(sit: dict) -> None:
    try:
        text = bauen(sit)
        if text:
            sit["anliegen"] = text
    except Exception as e:  # nie den Anruf mitreissen
        print(f"lisa-anliegen fail {e}", flush=True)
