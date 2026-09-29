# Befund-Sammlung (laufend): Anrufe und systemische Fehler

Chef 29.09.2026: "wir sammeln weiter telefonate und fehler" — noch NICHTS
reparieren. Jeder neue Anruf kommt unten in den Abschnitt "Anrufe", jeder neue
Fehler in den Musterkatalog (neue Nummer, nie umnummerieren). Zählen:
`python tools/anruf_muster.py <von> <bis>` bzw. `--ids <präfix> …`
(nur lesend über die Live-API 8096, Testanrufe bleiben draußen).

## Musterkatalog

Zähler aus `tools/anruf_muster.py`, 489 echte Anrufe 22.–29.09.2026
(Blessing 291, Thaler 128, MedDent 68, Rüther 2), Stand 29.09. 10:50.

| Nr. | Muster | 22.–29.09. |
| --- | --- | ---: |
| M1 | Antwort auf eine LLM-Frage gegen veraltete Maschinen-Frage bewertet | 3 |
| M2 | Nach erledigter Aufgabe holt Auto-Resume eine Schein-Aufgabe zurück | 3 |
| M3 | Nachfrage-Vorsätze gestapelt | 7 |
| M4 | Sprachwache verwirft Zug, Bianca fragt nach (davon mitten in eigener Ansage) | 21 (4) |
| M5 | Verbindungswunsch endet ohne Buchung/Absage/Verschiebung/Notiz | 30 von 41 |
| M6 | „Ich bin die Neue!“ plus Bezugswort („Verstehe.“) | 25 |
| M7 | Ganzsatz-Belehrung auf eine korrekte Kurzantwort | 7 |
| M8 | Qwen lernt Phrase → Kleinwort (Verdacht Fehl-Lernen) | 23 |
| M9 | Antwort im selben Anruf wortgleich wiederholt | 115 |

**M1 · Zwei Zustände laufen auseinander.** Die offene Frage
(`sammler["frage"]`) setzt nur der Regel-Ablauf. Fragt das LLM selbst (Name,
Wunschzeit …), bleibt die alte Frage stehen; `_fluss_sync`
(`bianca/agent.py`) gleicht nur nach Tool-Läufen ab. Alles, was
`sammler["frage"]` liest, arbeitet dann auf der falschen Frage:
`ohr.sprachkontext` (ja_nein), `_offene_frage` (ja-nein-unklar),
`gespraech.unklar_antwort` („Wobei darf ich Ihnen helfen?“) und der
Qwen-Namensschutz (`qwen_korrektor.live_sperre` / `_namens_kontext`) — daher
wurden Namen als Verhörer gelernt („klaus->Glauser“). Der Zähler erfasst nur
den Namensfall; der Mechanismus gilt für jede LLM-Frage.

**M2 · Schein-Aufgabe.** Parakeet verhört das Anliegen-Wort („Terminabsauging“,
„absorgen“), Qwen hat es richtig, ist aber seit 18.09. nur Korrektor
(`QWEN_LIVE_OHR=0`). Der Ablauf legt eine Buchung an; nach der echten Absage
holt `_auto_resume_anhaengen` diese Buchung zurück („Was ist denn der Grund
für Ihren Besuch?“).

**M3 · Vorsatz-Stapel.** `stille.letzte_frage` und `sit["flussFrage"]`
(`agent._maschinen_antwort`, `split(". ")`) übernehmen die letzte Frage samt
Vorsatz; `stille.frage_praefix` setzt einen zweiten davor („Ich frage noch
einmal: Noch einmal die Frage: …“).

**M4 · Nachfrage auf verworfene Züge.** `dienst.py` (Sprachwache,
`englisch-oder-stille`) antwortet immer mit `hoerfehler_nachfrage`, auch
während Biancas eigener Ansage. Seit Chef 28.09. werden auch „Yeah/No“
verworfen — ein als „Yeah“ verhörtes „Ja“ geht in der Ja/Nein-Frage verloren.
Nicht belegbar: verworfene Züge speichern bewusst weder Audio noch Text.

**M5 · Verbindungswunsch.** Erst die feste Absage (`weiterleiten.ENTLASTUNG`,
wortgleich wiederholt), Rückruf erst spät; `RUECKRUF_ANGEBOT` existiert.
„Na, danke.“ wurde als Zustimmung gewertet. Zähler ist eine Stichwortsuche
(verbinden/durchstellen/Mitarbeiter) — Anrufe mit korrekt gegebener Auskunft
zählen fälschlich mit.

**M6** `kern/eingehen.anwenden` hängt den Bezug hinter die Erstkontakt-Zeile;
`flow.py` sperrt das nur für den Grund-Pfad (Thaler 08.09.).

**M7** `agent.py` `ganzsatz-waechter` nach drei „unklaren“ Zügen — meist
Folge von M1 (Name ist kein Satz).

**M8** `qwen_korrektor._lernen` lernt auch, wenn Parakeet recht hatte
(„kannst du mir->konsumiere“). Wörterbuch gilt nur je Anruf.

**M9** Grob: jede wortgleiche Wiederholung, auch berechtigte
(„Wie ist Ihre Handynummer?“). Häufigste Fälle: „Die Rückrufbitte ist bereits
für die Praxis notiert.“, „Das habe ich akustisch nicht sicher mitbekommen.
Wobei darf ich Ihnen helfen?“

## Anrufe

### 29.09.2026 · Thaler · `a8fa761f305a458fba65c4242fa3869a`

09:20 Uhr, 3:30 min. Frau Kaur (per Nummer erkannt) will einen Termin für
ihren Mann und bittet dreimal um einen Menschen. **Ergebnis: nichts** — kein
Termin, kein Rückruf, Anruferin legt auf.

- z2, z18: wortgleich „eine menschliche Verbindung ist nicht eingerichtet.
  Worum geht es?“ — z18, obwohl das Anliegen bekannt ist (M5, M9).
- z3: „Ich bin die Neue! Verstehe. Habe ich Sie richtig erkannt?“ (M6).
- z4: „das kam nicht sicher an“ 4,5 s VOR Ende der eigenen Ansage (M4).
- z5: Zahnreinigung angeboten, bevor der Grund bekannt ist, und der
  Anruferin statt dem Mann; der Besuchsgrund wird im ganzen Anruf nie erfragt.
- z7: Frage „ist die Leistung Kiefer dabei“ mit dem PZR-Preis beantwortet
  (offene Frage war `pzr_kasse`).
- z8: Parakeet „Holen Sie mal gut.“, Qwen „Hansi Merkur.“ → Kassenfrage erneut.
- z10, z11: zwei Nachfragen auf verworfene Züge in der Ja/Nein-Frage (M4);
  z11 „Ich frage noch einmal: Noch einmal die Frage: …“ (M3).
- z12 LLM fragt den Namen des Mannes, `frage` bleibt `schonmal` → z13/z14
  „Singh Harbrid“ gilt als unklares Ja/Nein, zweimal „Kurz zurück zur Frage:
  War Ihr Mann schon einmal bei uns?“ (M1, M3) → „Ja, habe ich ja gesagt.“
- z19: Rückruf erst beim dritten Verbindungswunsch; Qwen lernt
  „kannst du mir->konsumiere“ (M8).
- z20: „Na, danke.“ als Ja gewertet, Anruferin legt auf; kein Rückruf angelegt.

### 29.09.2026 · Thaler · `881ade7045be4eccbe49597ee69987a1`

09:21 Uhr, 1:42 min. Herr Glaser sagt einen Termin ab. **Ergebnis: Absage
erledigt** (gefunden, bestätigt, `agentCancelAppointmentById` 200, verifiziert)
— aber mit fünf unnötigen Zügen und einem verwirrenden Schluss.

- z2: Parakeet „Terminabsauging.“ (Qwen „Terminabsage.“); „Ich bin die Neue!
  Verstehe.“ (M6); begrüßt ihn mit Namen und fragt trotzdem „Unter wem ist der
  Termin eingetragen?“.
- z3–z5: Namensantworten „Klaus Anton“, „Glass“, „Laura Anton“ (Qwen jedes Mal
  „Glauser Anton“) als unklar gewertet → zweimal wortgleich „Wobei darf ich
  Ihnen helfen?“, dann Ganzsatz-Belehrung (M1, M7, M9). Qwen lernt
  „klaus/glass/laura->Glauser“.
- z6/z7: „absorgen“ (Qwen „absagen“) → Buchungs-Ablauf, Grund-Menü „Neupatient,
  Kontrolle, Schmerzen …“ (M2).
- z8/z9: Absage korrekt.
- z11: Auto-Resume der Schein-Buchung „Was ist denn der Grund für Ihren
  Besuch?“ (M2), Anrufer legt auf.
- Nebenbefund: Absage mit `source: "telefonki-lisa"` verbucht, obwohl Bianca.
