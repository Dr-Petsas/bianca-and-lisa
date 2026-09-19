# Befund: Alle Bianca-Anrufe 14.–17.09.2026 — löst die KI, oder schreibt sie nur Notizen?

Stand 17.09.2026, 10:30 Uhr. Grundlage sind die 432 Mitschnitte
(`.data/anrufe/bianca/*/anruf.json`, read-only vom Server gezogen) vom
14.09. 04:09 UTC bis 17.09. 07:43 UTC: Blessing 280, Thaler 110, MedDent 31,
Rüther 11. Beweis für „gelöst" ist ausschließlich das Werkzeug-Ledger
(`tools[].ok` für Buchung/Absage/Verschiebung), nie der gesprochene Text.
Die 235 Anrufe OHNE Schreib-Beweis, aber mit Dialog wurden vollständig
gelesen (vier Auditoren, Kategorien P1–P14, `befund_slice_0-3.jsonl`).

## 1. Trichter

| | Anrufe | Anteil an Anrufen mit Anliegen |
| --- | ---: | ---: |
| Anrufe gesamt | 432 | |
| Aufleger / kein Anliegen / Warteschleife / Test | 152 | |
| **Anrufe mit echtem Anliegen** | **280** | 100 % |
| gelöst mit Schreib-Beweis (Buchung, Absage, Verschiebung) | 57 | 20 % |
| gelöst ohne Schreibvorgang (Auskunft korrekt gegeben) | 5 | 2 % |
| teilweise gelöst | 6 | 2 % |
| **nur Notiz an die Praxis** | **77** | **28 %** |
| **nichts erreicht** (gescheitert 127 + nicht lösbar 8) | **135** | **48 %** |
| Weiterleitungen | 0 | |

Fast die Hälfte der Anrufer mit Anliegen legt ohne Ergebnis auf, ein
weiteres Viertel bekommt nur „die Praxis meldet sich". Die Auditoren
bewerten 39 von 59 gescheiterten Anrufen der ersten Tranche als „hätte
Bianca lösen können" — das Problem liegt überwiegend in unserem Code,
nicht am Anrufer.

## 2. Hauptursachen (Auditor-Zuordnung, 223 Anrufe mit Anliegen ohne Schreib-Beweis)

| Kat. | Haupt | beteiligt | Ergebnis (Haupt) |
| --- | ---: | ---: | --- |
| P13 LLM erfindet / ignoriert | 47 | 167 | 34 gescheitert, 13 Notiz |
| P10 Rückruf-/Rezept-Weg | 27 | 37 | 9 gescheitert, 5 Notiz, 8 nicht lösbar |
| P9 „Mensch sprechen" / Verbinden | 20 | 46 | 17 gescheitert |
| P3a Terminauskunft → nur Notiz | 17 | 39 | 13 Notiz |
| P3b Absage/Verschieben → nur Notiz | 17 | 25 | 13 Notiz |
| P1 „Leistung wird nicht angeboten" | 15 | 28 | 11 gescheitert |
| P14 Sonstiges (Namensdiktat, Abschied) | 15 | 22 | 7 gescheitert |
| P8 Wiederholungs-/Frage-Schleife | 13 | 79 | 11 gescheitert |
| P11 Einwand überhört | 12 | 35 | 11 gescheitert |
| P5 Buchung scheitert an Handynummer | 10 | 16 | 5 gescheitert, 3 Notiz |
| P4 Slot „gerade weg" | 7 | 8 | 4 gescheitert |
| P2 Kalender-500 („antwortet nicht") | 7 | 10 | 5 Notiz |
| P7 Latenz / taubes Ohr | 6 | 14 | 6 gescheitert |
| P6 Motiv falsch gemappt | 2 | 58 | |

## 3. Gewichtete Nacharbeit — mit Ursache im Code

Gewichtung: Häufigkeit × Schaden (Anrufer geht leer aus) × Reparierbarkeit.
„Sofort" = Bianca-Repo, klein, ohne fremden Deploy.

### A. Sofort (Bianca-Repo)

**A1 · Toter Kalender aus der Patientenkartei → „Der Terminkalender antwortet gerade nicht"**
- Beleg: 61 von 64 `getFreeTimeSlots`-500ern („Could not load doctor") in 15
  Blessing-Sitzungen tragen `calendarId=TphQRh53x8SToBSa8DdB`; der Mandant
  kennt nur `8krcWh7AuXEfgWc1blzQ` (beide heißen „Doktor Charlotte Blessing").
  Die Kartei (`anruferKartei`, aus `masPatientLastDoctor`) liefert den
  Kalender des LETZTEN Termins — bei importierten Altterminen ein gelöschter
  Kalender. Folge: 10 Anrufe „Terminkalender antwortet gerade nicht",
  darunter 1cdee70f, 386155ea, 537fa2ec, 720b67a8, ede4141f.
- Ursache: `bianca/arzt.py:249` — `_s(termin.get("calendarId")) or cal.id`
  nimmt die rohe Termin-ID VOR dem Namensabgleich mit den Tenant-Kalendern.
- Fix: Kalender-ID nur übernehmen, wenn sie in `tenant.calendars` steht;
  sonst per Namen (`kalender_von`) auflösen; ohne Treffer leer lassen
  (Default-Kalender). Zusätzlich: jeder 500er aus `getFreeTimeSlots` mit
  fremder Kalender-ID → einmal mit Default-Kalender wiederholen.

**A2 · Rückruf versprochen, aber keine Notiz geschrieben**
- Beleg: 7 Anrufe (1cdee70f, 386155ea, 537fa2ec, 64503f4e, 720b67a8,
  ede4141f, fbe07bc5) hören „Die Praxis ruft Sie kurzfristig zurück — Ihre
  Nummer habe ich ja." — im Ledger steht KEIN `praxis_notiz`. Die Praxis
  erfährt nichts, der Anrufer wartet.
- Ursache: `bianca/flow.py:955-960` (CF-Fehler in `_angebot`) spricht das
  Versprechen ohne Notiz und ohne Nummernprüfung.
- Fix: dort echte `praxis_notiz` (Grund, Wunsch, Nummer) + W-RUECKRUF-NUMMER,
  wenn keine Nummer vorliegt; Fakten-Wache um den Claim „Praxis ruft zurück /
  meldet sich" ergänzen (Evidenz = Notiz-Werkzeug).

**A3 · Verbinde-Rückfrage in Praxen ohne Verbinde-Ziel**
- Beleg: 19 Anrufe (Blessing 14, Thaler 5), zuletzt HEUTE 06:37 (0de63876):
  „Verbinden Sie mich bitte mit einer Arzthelferin." → „zu welchem unserer
  Ärzte darf ich Sie verbinden?" (zweimal), erst im 4. Zug die Wahrheit
  („nicht eingerichtet — Rückrufwunsch?"). Blessing hat EINEN Arzt und
  keine Weiterleitung; die Frage ist eine Sackgasse.
- Ursache: `bianca/weiterleiten.py:824-830` (Fall 3) und `:741-753`
  (Rückfrage-Zweig) prüfen nie, ob der Mandant überhaupt durchstellen kann
  (`verbindenErlaubt` leer, keine `weiterleitungen`); `_MENSCH_NUR_RE`
  kennt „Arzthelferin/MFA/Helferin/Praxisteam" nicht (Fall 2 greift nicht).
- Fix: ohne Verbinde-Ziel NIE nach dem Arzt fragen → sofort ein Satz
  („Durchstellen ist hier nicht eingerichtet — ich kann das Anliegen direkt
  übernehmen oder einen Rückruf notieren. Worum geht es?"); Mitarbeiter-Wörter
  ergänzen.

**A4 · Änderungs-Schleife nach „Nein" auf das Readback**
- Beleg: 23 Readbacks („Soll ich das so eintragen?") ohne Buchung; in
  05a5dd55 („Ich mache den Termin online aus. Danke."), 31b8842d („Nein." /
  „Oh ne."), 4dfc81be („Nein, danke.") fragt Bianca bis zu dreimal „Was darf
  ich ändern — Zeitpunkt, Name, Nummer oder Besuchsgrund?" und lässt nicht los.
  66913eb8: „Ich möchte das Telefon beenden, Termin nicht buchen." →
  „Ganz kurz bitte. Im Angebot sind: …".
- Ursache: `flow._aenderung_zug` kennt nur die vier Felder; Ablehnung,
  Abschied, „online", „nicht buchen" sind kein Ausgang. `kern/abschied.py`
  und `ist_abbruch` erkennen „Telefon beenden / Termin nicht buchen" nicht.
- Fix: Ablehnung/Abschied/„online"/„nicht buchen" → höflich schließen (kein
  Termin, keine Notiz ohne Wunsch), Auflegen bei klarem Abschied.

**A5 · Wiederholungs-Wächter streicht die Slot-Liste**
- Beleg: 66913eb8 Zug 19 — `wiederholung-gestrichen: „Frei ist am Montag,
  den siebten Dezember um zwölf Uhr; …"` → gesprochen wurde nur „Alles klar.
  Welcher davon passt Ihnen?" (ohne Optionen).
- Ursache: `kern/wiederholung.py` — Ziffern-Ausnahme greift nicht bei
  ausgeschriebenen Datums-/Uhrzeitwörtern; das Angebot war wortgleich mit
  dem vorigen (gleiche Slots nach Motivwechsel).
- Fix: Angebots-/Readback-Sätze (Wochentag/Monat/„Uhr") nie streichen.

**A6 · Slot-Ablehnung wird nur bei Blessing gemerkt**
- Beleg: Thaler 27dee67b — „Keiner passt morgen, morgen geht's nicht." →
  „es bleibt bei morgen um dreizehn Uhr dreißig; oder morgen um sechzehn Uhr."
- Ursache: `slotPraeferenzenFesthalten` (W-BLESSING-SLOTPRÄFERENZ) ist ein
  Blessing-Schalter; Thaler/MedDent/Rüther vergessen Ausschlüsse.
- Fix: Schalter zum Standard machen (wie W-RUHE am 15.09.).

**A7 · Phantom-Slots am 30. Tag des Suchfensters („Termin ist gerade weg")**
- Beleg: 8 `book_slot` → „The slot is not available." in 6 Anrufen; 6 der 8
  liegen exakt auf Tag 30 nach Anrufbeginn und wurden OHNE `startDate`
  gesucht; mit `startDate` liefert die CF diese Slots nicht.
- Vermutete Ursache (Plattform): `appointmentsService.getFreeTimeSlots`
  rechnet `searchEndDate = searchStartDate + 30 Tage` MIT Uhrzeit; der
  Kalkulator erzeugt für den letzten Tag ganze Tages-Slots, `isSlotAvailable`
  verwirft sie später. Zu verifizieren in `freeTimeSlotsCalculator.ts:186-352`.
- Fix Bianca (sofort): Slots am letzten Tag des Fensters verwerfen bzw.
  `startDate` immer senden; Fix Plattform: Fensterende auf Tagesende.

### B. Dringend — braucht Chef-Entscheidung / Plattform-Deploy

**B1 · Ohne Handynummer keine Buchung (P5)**
- Beleg: 7 `needs_phone`-Abbrüche in 4 Anrufen; Thaler 53736d6f: „Ich habe
  kein Handy." → „Dann rufen wir Sie zurück … Festnetznummer?" — Termin weg,
  Notiz statt Buchung. Ältere Patienten sind systematisch ausgeschlossen.
- Ursache: `docgendaweb/functions/src/controllers/masAgent.ts:396-402`
  verlangt `mobilePhoneNumber`; Biancas Selbstheilung (W-AKTE-HANDY) schreibt
  bewusst nur bestätigte MOBILnummern.
- Vorschlag: für `source=pickadoc-bianca` Buchung OHNE SMS zulassen, wenn
  eine Festnetznummer vorliegt (in `phoneNumber` schreiben, Termin-Notiz
  „keine SMS möglich — Festnetz …"). Entscheidung: Chef.

**B2 · „Diese Leistung wird in dieser Praxis nicht angeboten" (P1)**
- Beleg: 30 Blessing-Anrufe hören den Satz, 15-mal Hauptursache, 11
  gescheitert. Treffer sind Hautwünsche und Rückfragen: „Dornwarzen" →
  Botox/Filler (66913eb8), „Beratung" → nicht angeboten, „Was soll ich
  aussprechen?" → Nachname „Was Aussprechen" (a467367e).
- Ursache: `bianca/gehirn.py:1916-1931` — bei `frage=grund` wird JEDE kurze
  unbekannte Äußerung zum Katalog-Nein (`nicht_im_katalog`).
  W-BLESSING-MOTIVKLARHEIT (15.09.) deckt Beratung/Weiterbehandlung, nicht
  den Rest.
- Fix: Katalog-Nein nur bei klar fachfremdem Wunsch (Fach-Wache-Vokabular);
  sonst EINE Rückfrage („Was soll die Ärztin sich ansehen?") + Fuzzy gegen
  Katalog-Namen UND Erklärtexte; Rückfragen des Anrufers („Was meinen Sie?")
  nie als Grund/Namen ernten.

### C. Wichtig — LLM-Verhalten und Wächter

**C1 · LLM erfindet Termine und Erledigt-Zusagen (P13, 167 Anrufe beteiligt)**
- Beleg: 53986f42 — „Ich habe für morgen, Mittwoch, den sechzehnten
  September, einen Termin um neun Uhr dreißig. Passt Ihnen das? … Wir sehen
  uns morgen — bis dann!" — KEIN `getFreeTimeSlots`, KEIN `book_slot`. Der
  Anrufer glaubt, er habe einen Termin.
- Ursache: `kern/fakten_wache.py` deckt „ist eingetragen/gebucht", nicht
  „ich habe für morgen … einen Termin (für Sie)" und „Wir sehen uns …".
- Fix: Slot-Claim = Datum + Uhrzeit ohne `getFreeTimeSlots`-Evidenz → streichen;
  Abschied nach Termin-Aussage ohne `book_slot` → blockieren und Maschine
  weiterführen.

**C2 · Anmeldungs-Sermon (P9/P10)**
- Beleg: 31 Anrufe (Blessing 17, Thaler 13, MedDent 1) hören ~40 s „Ich bin
  die KI-Telefonassistentin der Praxis und entlaste die Anmeldung …".
  Blessing hat seit 15.09. `anmeldungKurz`; Thaler nicht.
- Fix: Kurzform für alle Mandanten (ein Satz + Anliegen-Frage).

**C3 · Namensdiktat / Korrektur nicht übernommen (P14/P11)**
- Beleg: 61438281 (49 Züge): „Kromer, fertig." → stummer Zug, dann „Meine
  Frage war: Wie lautet der Nachname?"; a467367e speichert die Rückfrage als
  Nachnamen.
- Fix: W-DIKTAT-FERTIG auf den Korrektur-Pfad („nicht X, sondern Y, fertig")
  ausdehnen; Rückfragen („Was meinen Sie / soll ich …?") sind nie Namen.

**C4 · Latenz und taubes Ohr (P7)**
- Beleg: 223 von 3.906 Hör-Zügen brauchten > 4 s Serverzeit (LLM-/Maschinen-
  Anteil dominant, Spitze 26 s); Cluster 15.09. 14:50–15:00 UTC; Brücke
  meldet 15.09. 12:58–13:0x `bruecke-start http 500` und „gehoert" ohne
  „antwort" (29e7ed8e). Die Container-Logs sind weg.
- Fix: Fehlerlog in ein Volume schreiben (nie wieder blind), Zug-Timeout mit
  hörbarem Fallback; Buchungs-/Suchpfade vermessen (`timings.llm` enthält
  die ganze Maschine inkl. CF-Aufrufe).

### D. Heute bereits umgesetzt (noch nicht committet, nicht deployt)

- **W-RUECKRUFGRUND-ENDE** (Anruf a8536585): fehlender Rückrufgrund wird
  einmal ehrlich beantwortet, kein Termin-Menü, keine Endschleife, keine
  Akten-Anrede (`bianca/flow.py`, `bianca/agent.py`, `tests/test_rueckruf.py`).

### Offen aus früherem Auftrag

- **Thaler PZR nur in Zimmer 3** (Ausweichzimmer bei vollem Zimmer 3 noch zu
  klären), keine Doppelbuchungen — noch nicht umgesetzt.

## 4. Werkzeuge dieser Analyse (temporär, `%TEMP%\bianca-anrufe\`)

`funnel.py` (Trichter mit Ledger-Beweis), `agg2.py` (Kategorien + Belege),
`cross.py` (Auditor-Urteil × Schreib-Beweis), `latenz*.py`, `tools_stat.py`,
`cal500*.py` (Kalender-500er), `tag30.py` (Phantom-Slots), `zaehl2-5.py`
(Symptomzähler je Mandant). Alles read-only gegen die Manifeste.
