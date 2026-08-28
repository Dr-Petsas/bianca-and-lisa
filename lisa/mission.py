"""Auftrag rahmen — portiert aus MAS lisa/outbound.js rahmeAuftrag, ohne MAS."""

from __future__ import annotations

import re

TERMIN_WORT_RE = re.compile(
    r"\b(termin\w*|verschieb\w*|vorverleg\w*|verleg\w*|absag\w*|abgesagt|storn\w*|"
    r"recall\w*|kontrolle|prophylaxe|nachsorge|buch\w*|umbuch\w*|erinner\w*|"
    r"slot\w*|sprechstunde\w*|zahnreinigung)\b",
    re.I,
)


def praxis_an(praxis: str) -> str:
    """„von der Demo-Praxis“ / „von Zahnärzte im Medical Center“."""
    haus = " ".join(str(praxis or "").split()).strip()
    if not haus:
        return ""
    low = haus.casefold()
    if "zahnärzte" in low or "zahnaerzte" in low:
        return f"von {haus}"
    return f"von der {haus}"


def rahme_auftrag(prompt: str) -> str:
    text = " ".join(str(prompt or "").split()).strip()
    if not text:
        return ""
    if TERMIN_WORT_RE.search(text):
        return text
    return (
        f"{text}\n\n"
        "[Regieanweisung, NICHT vorlesen und NICHT erwaehnen: Dieser Anruf hat nichts "
        "mit Terminen zu tun. Sage in eigenen Worten genau die Nachricht, die oben "
        "steht. Frage NICHT nach Terminwuenschen, biete KEINEN Termin an, nenne "
        "keinen Terminanlass. Eine kurze Nachricht darf in ein bis zwei Saetzen "
        "erledigt sein. Fragt der Angerufene nach dem WARUM und die Nachricht "
        "oben nennt keinen Grund: sage ehrlich, dass dir dazu keine Einzelheiten "
        "vorliegen, und biete an, dass die Praxis zurueckruft — niemals mauern "
        "oder einen Grund erfinden.]"
    )


def identitaets_rahmen(praxis: str, behandler: str = "") -> str:
    praxis = " ".join(str(praxis or "").split()).strip() or "der Praxis"
    arzt = " ".join(str(behandler or "").split()).strip()
    arzt_teil = (
        f'Du rufst im Auftrag von "{arzt}" an. Fragt jemand, wer dich schickt, '
        f'oder wer du bist, nenne "{arzt}" und die Praxis. Erfinde keinen anderen Arzt.'
        if arzt else
        "Nenne keinen Arzt, wenn der Auftrag keinen nennt."
    )
    return (
        f'\n\n[Identitaet fuer dieses Gespraech, Regieanweisung — NICHT vorlesen: '
        f'Du rufst fuer die Praxis "{praxis}" an. Stelle dich mit GENAU dieser '
        f'Praxis vor ("hier ist Lisa {praxis_an(praxis)}"). {arzt_teil} '
        f"Nenne NIE eine andere Praxis und keinen anderen Arzt, auch wenn im "
        f"Prompt ein Beispiel mit einem anderen Namen steht — dieser Auftrag gilt.]"
    )


def ist_termin_auftrag(prompt: str) -> bool:
    return bool(TERMIN_WORT_RE.search(str(prompt or "")))
