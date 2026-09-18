"""Deterministischer Dialogkern (DIALOG_CONTROLLER).

Dieses Paket baut Biancas Gespraechssteuerung als typisierten, deterministischen
Controller PARALLEL zum Live-Pfad auf. Standardmodus ist ``legacy`` — dann ist
das Paket vollstaendig inert, der Live-Pfad (``bianca/agent.py`` -> ``flow.zug``)
laeuft byte-identisch.

Modi (Umgebungsvariable ``DIALOG_CONTROLLER``):
  - ``legacy``  : Controller wird nie aufgerufen (Default).
  - ``shadow``  : Controller berechnet je Zug NUR eine ``Decision`` aus dem
                  Eingangssnapshot, protokolliert Differenzen, fuehrt KEIN
                  Werkzeug aus und spricht NICHTS. Legacy bleibt Antwortquelle.
  - ``enforce`` : reserviert; taskweise und erst nach den harten Fertig-Kriterien
                  (siehe Plan). Ohne ausdrueckliche Freigabe bleibt der
                  Antwortpfad Legacy.

Bausteine:
  - ``typen``        geschlossene Typen (Task/SlotValue/SemanticEvent/
                     ToolCommand/ToolOutcome/SpeakSpec/Decision/State/Policy).
  - ``policy``       baut aus einem Mandanten die ``Policy`` (Verhalten = DATEN);
                     der Reducer bleibt dadurch mandantenagnostisch.
  - ``reducer``      reine Funktion State + Event + Policy -> State + Decision.
  - ``nlu``          deterministische Ereigniserkennung + schema-validierter
                     LLM-Rueckfall ohne Werkzeug-/Sprechautoritaet.
  - ``tool_gateway`` normalisiert Werkzeug-Rueckgaben in ``ToolOutcome`` und
                     verriegelt Schreib-Gates.
  - ``kern``         Orchestrator: Snapshot -> NLU -> Reducer -> Decision und
                     der Shadow-Beobachter.
"""

from __future__ import annotations

__all__ = ["typen", "policy", "reducer", "nlu", "tool_gateway", "kern"]
