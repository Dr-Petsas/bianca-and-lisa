"""Chef-Einzeiler zum Lisa-Auftrag vertiefen — vor dem Anruf, im Textfeld.

Einzeiler („Recall vereinbaren“) geben Lisa nach zwei Zügen nichts mehr:
keinen Grund, keinen Einwand, keine nächste Schicht. Der Knopf schreibt
einen tieferen Auftrag zurück. Praxisgedächtnis nur, wenn die Zeile
zahnärztlich etwas sagt — Zoll/Demo/leere Events bleiben draußen.
"""

from __future__ import annotations

import re
from typing import Any

from kern import gedaechtnis, llm, tenants
from kern import patients as patmod

_RECALL_RE = re.compile(
    r"recall|kontrolle|nachsorge|prophylaxe|zahnreinigung|\bpzr\b", re.I)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _termine_text(past: list, upcoming: list) -> str:
    teile = []
    if upcoming:
        teile.append("Kommend: " + "; ".join(_s(x.get("label")) for x in upcoming[:4] if _s((x or {}).get("label"))))
    if past:
        teile.append("Zuletzt: " + "; ".join(_s(x.get("label")) for x in past[-3:] if _s((x or {}).get("label"))))
    return " | ".join(teile)


def _gedaechtnis_zu(name: str, phone: str) -> tuple[str, str]:
    """(text, stand) — stand: ok / nichts / aus / tot."""
    if not gedaechtnis.enabled():
        return "", "aus"
    if not gedaechtnis.erreichbar():
        return "", "tot"
    try:
        roh = gedaechtnis._kontext_holen(phone, name)
    except Exception as e:
        print(f"lisa-vertiefen gedaechtnis fail {e}", flush=True)
        return "", "tot"
    if not roh or not gedaechtnis.zeile_inhaltlich(roh):
        return "", "nichts"
    return roh, "ok"


def notfall_vertiefen(auftrag: str, *, hintergrund: str = "", termine: str = "") -> str:
    """Ohne Modell: Begründung und Gesprächsschichten an den Einzeiler."""
    kopf = _s(auftrag) or "Patienten anrufen."
    extra: list[str] = []
    if _RECALL_RE.search(kopf):
        extra.append(
            "Begründung, wenn jemand nach dem Warum fragt: regelmäßige Kontrolle, "
            "damit kleine Befunde früh auffallen; oft kombinierbar mit einer "
            "professionellen Zahnreinigung. War der Patient kürzlich da — nachfragen, "
            "nicht widersprechen. Keinen Befund und keine Krankengeschichte erfinden."
        )
    extra.append(
        "Gesprächsschichten über mehrere Züge (nicht in einem Atemzug): "
        "1) Grund des Anrufs, 2) kurz warum die Praxis jetzt anruft, "
        "3) auf Einwand eingehen, 4) Termin festmachen oder Rückruf anbieten. "
        "Nach zwei Sätzen nicht aufhören, nur weil der erste Punkt gesagt ist."
    )
    if termine:
        extra.append(f"Termine aus der Kartei (nutzen, nicht vorlesen): {termine}")
    if hintergrund:
        extra.append(
            "Nur dieser Praxisstand — inhaltlich, nicht zitieren wenn leer:\n"
            + hintergrund
        )
    extra.append(
        "[Regie, nicht vorlesen: Keine inhaltslosen Gedächtnissätze. "
        "Nichts erfinden, was oben nicht steht.]"
    )
    return kopf + "\n\n" + "\n".join(extra)


def _llm_vertiefen(auftrag: str, *, name: str, hintergrund: str, termine: str) -> str:
    system = (
        "Du vertiefst den Auftragstext für Lisa, die Telefonassistentin einer "
        "Zahnarztpraxis. Der Chef tippt oft nur einen Einzeiler. Lisa braucht "
        "Gesprächsschichten für 4–6 kurze Züge: Warum der Anruf, Begründung "
        "(z. B. Recall), typische Einwände, nächster Schritt.\n"
        "REGELN\n"
        "- Antworte NUR mit dem neuen Auftragstext auf Deutsch.\n"
        "- Den Sinn des Chefs behalten, nichts Gegenteiliges.\n"
        "- Briefing, nicht Skript: keine Begrüßung, keine Identitätsfrage, "
        "keine wörtlichen Dialogzeilen in Anführungszeichen, kein „Lisa, hier ist…“.\n"
        "- Spiegelstriche: Zweck, Begründung (Warum der Anruf), typische Einwände, "
        "nächster Schritt über mehrere Züge.\n"
        "- Patientengeschichte NUR aus dem gelieferten Praxisstand oder den Terminen. "
        "Steht nichts, erfinde nichts und schreibe nicht „im Gedächtnis steht…“.\n"
        "- Fachfremden Kram (Zoll, Paket, Demo) ignorieren.\n"
        "- Höchstens 160 Wörter."
    )
    user = f"AUFTRAG DES CHEFS:\n{auftrag}\n"
    if name:
        user += f"\nPATIENT: {name}\n"
    if termine:
        user += f"\nTERMINE AUS DER KARTEI:\n{termine}\n"
    if hintergrund:
        user += f"\nPRAXISSTAND (nur das, sonst nichts):\n{hintergrund}\n"
    else:
        user += "\nPRAXISSTAND: keiner — nichts aus einem Gedächtnis behaupten.\n"
    out = llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        None, temperature=0.25, max_tokens=360,
    )
    if not out.get("ok"):
        return ""
    text = _s(out.get("text")).strip('"“” ')
    if not text or len(text) < 40:
        return ""
    return text


def vertiefen(auftrag: str, *, tenant_id: str = "", patient: dict | None = None) -> dict[str, Any]:
    auftrag = _s(auftrag)
    if not auftrag:
        return {"ok": False, "error": "auftrag fehlt", "auftrag": ""}
    pat = patient if isinstance(patient, dict) else {}
    name = _s(pat.get("name")) or f"{_s(pat.get('firstName'))} {_s(pat.get('lastName'))}".strip()
    phone = "".join(c for c in _s(pat.get("phone")) if c.isdigit())
    past = list(pat.get("past") or [])
    upcoming = list(pat.get("upcoming") or [])
    if tenant_id and (pat.get("id") or name) and not (past or upcoming):
        try:
            t = tenants.laden(tenant_id)
            hist = patmod.termine_fuer(t, pat if pat.get("id") else {"name": name})
            past = hist.get("past") or []
            upcoming = hist.get("upcoming") or []
        except Exception as e:
            print(f"lisa-vertiefen termine fail {e}", flush=True)
    termine = _termine_text(past, upcoming)
    stand_text, stand = _gedaechtnis_zu(name, phone)
    text = _llm_vertiefen(auftrag, name=name, hintergrund=stand_text, termine=termine)
    if not text:
        text = notfall_vertiefen(auftrag, hintergrund=stand_text, termine=termine)
    return {
        "ok": True,
        "auftrag": text,
        "gedaechtnis": stand,
        "hatStand": bool(stand_text),
    }
