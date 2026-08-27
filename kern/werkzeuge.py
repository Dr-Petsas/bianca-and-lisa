"""Werkzeug-Schemas der Kalender-Tools — EINE Quelle für Lisa und Bianca."""

from __future__ import annotations

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_appointments",
            "description": "Kommende Termine des Patienten aus der Akte vorlesen.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "offer_slots",
            "description": (
                "Freie Termine holen, wenn neu gebucht werden soll oder der angebotene "
                "nicht passt. Wunsch z. B. 'Donnerstag nachmittags'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "wish": {"type": "string", "description": "Patientenwunsch, frei formuliert."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_patient",
            "description": (
                "Neue Patientenakte in der Kartei anlegen, wenn die Person nicht gefunden wird. "
                "Vorher nicht selbst raten — das Werkzeug sucht zuerst. Handy ist Pflicht."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "first": {"type": "string", "description": "Vorname"},
                    "last": {"type": "string", "description": "Nachname"},
                    "phone": {"type": "string", "description": "Handynummer, so gesagt."},
                    "birth": {"type": "string", "description": "Geburtsdatum YYYY-MM-DD, falls genannt."},
                    "gender": {"type": "string", "description": "frau / herr / diverse, falls klar."},
                },
                "required": ["first", "last", "phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_slot",
            "description": "Bucht einen neuen Termin. Nach Angebot: iso unverändert als slot_iso.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slot_iso": {"type": "string", "description": "ISO aus offer_slots, unverändert."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": "Sagt den bestehenden Termin ab. Datum nur wenn der Patient ein anderes nennt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD, leer = Termin aus der Akte."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_appointment",
            "description": (
                "Verschiebt den bestehenden Termin. Ohne slot_iso: Ausweichplätze suchen. "
                "Mit slot_iso: auf genau diesen Platz legen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slot_iso": {"type": "string", "description": "ISO des neuen Platzes."},
                    "wish": {"type": "string", "description": "z. B. nachmittags, nächste Woche."},
                    "date": {"type": "string", "description": "Datum des alten Termins, YYYY-MM-DD."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note_appointment",
            "description": (
                "Schreibt ins Notizfeld des Termins, was der Patient Besonderes gesagt hat "
                "(Angst, Spritze, Begleitung, Schmerzen …) oder eine Kurzfassung des Gesprächs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "Kurzer Sachtext für die Praxis."},
                },
                "required": ["note"],
            },
        },
    },
]
