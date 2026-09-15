# Befund Blessing: zu gesprächig — 15.09.2026

Vorbereitung für **Opus 5.1 max**. Nur Repo `F:\Bianca&Lisa TelefonKI`.
Clara, MAS, Lena, Demo nicht anfassen. Kein Deploy, bis der Chef das explizit sagt.

## Auftrag an Opus

Der junge Blessing findet die Telefon-KI zu gesprächig. Auftrag: **alles
Gespräch außerhalb der Aufgabenstellung** bei Mandant `blessing`
(`clientId UUJnPzoYPa4yYyzcaGlm`, DID `+4921154244120`) knapper machen.

**Aufgabenstellung Blessing (eng):** Anliegen erkennen → Termin / Absage /
Verschieben / Auskunft / Notfall-Sofortregel / Dokument-Vorsprache.
Nicht: Smalltalk, Selbstvorstellung als „die Neue“, Empathie-Essays,
medizinische Beratung, Behandlerwahl (es gibt nur Doktor Blessing),
Doktor-Notiz-Zusatzfrage, KI-Rechtfertigungssermon.

**Nicht rückbauen:** W-BLESSING-AKUT, DOKUMENT-VORSPRACHEREGEL, W-FACH-WACHE,
W-ZEITEN-WACHE (belegte Zeiten bleiben sprechbar), W-ANREDE, Fakten-Wache.
MedDent/Thaler/Rüther müssen byte-identisch bleiben, außer ein Satz ist
ohnehin mandantenscharf.

**DoD**

1. Neue Tests `tests/test_blessing_knapp.py` (offline) mit den Live-Wortlauten
   unten. Jeder Positivfall hat eine Gegenprobe, die einen nötigen Job-Satz
   stehen lässt.
2. `python -m tests.lauf_bianca` bleibt grün; bestehende Blessing-Tests
   (`test_blessing_*`, `test_fach_wache`, `test_dokument_hook`,
   `test_zeiten_wache`) unangetastet grün.
3. Nach dem Patch: dieselben Sätze aus den Top-5-Kategorien dürfen bei
   `tenantId=blessing` nicht mehr so gesprochen werden.
4. Kein zweiter Prozess, kein Prompt-Gedicht. Harte Kürzung im Code.

Rohmaterial: `.data/blessing-today-pack/` (Transkripte, Zählung).
Live-Quelle: pickadoc1 `telefonki-bianca-1:/app/.data/anrufe/bianca/`.

---

## Korpus 15.09.2026

| Menge | Zahl |
| --- | ---: |
| Anrufe mit `tenantId=blessing` | 118 |
| Davon mit Anrufer-Sprache | 102 |
| Leer / Aufleger | 16 |
| 45 s – 2 min | 34 |
| 2 – 5 min | 37 |
| länger als 5 min | 18 |
| Ein Thaler-Anruf rutschte in den Rohdump (`d7f485d7…`, Begrüßung „Thaler Zahnmedizin“) | nicht mitzählen |

Zählbasis der Phrasen: 103 Gespräche mit Anrufer-Wort im Pack, inkl. des
einen Thaler-Fehltreffers. Die Blessing-Muster unten sind davon unabhängig
belegt — „Ich bin die Neue“ und die Unklar-Schleife sitzen fest im Code.

---

## Katalog nach Häufigkeit

Rangfolge nach **gesprochenen Zügen** (nicht nach Bauchgefühl).
`Art`: Maschine = deterministischer Satz, LLM = freies Modell, Hybrid = beides.

### 1. Unklar-Schleife — 109 + 106 Züge in 54 Anrufen (52 %)

**Satz (fest, `kern/gespraech.unklar_antwort`):**
„Ich habe „…“ verstanden. Was meinen Sie damit? Meinen Sie vielleicht etwas anderes?“

Live trifft das **gültige Dermatologie-Wörter** und **klare Gesprächssignale**:

| Anrufer | Bianca | Anruf |
| --- | --- | --- |
| „Weitere Medikamentekontrolle.“ | Unklar-Satz | `0331a945` |
| „Rosacea, Weiterbehandlung.“ | Unklar-Satz | `0331a945` |
| „Ja, richtig.“ (auf die Katalogfrage) | Unklar-Satz | `50563be8` |
| „Wie bitte?“ | Unklar-Satz | `1e53c4d4` |
| „Hallo.“ / „Ja, hallo“ / „Oh, hallo“ / „Thank you“ | Unklar-Satz | mehrere |
| „Die Bitte.“ / „habt“ (STT-Schnipsel) | Unklar-Satz | `53986f42` |

Das ist der teuerste Eindruck von Geschwätz: Bianca **stellt das Gesagte
als unverständlich hin**, statt es zuzuordnen oder die offene Frage
einmal knapp zu wiederholen.

**Soll Blessing:** STT-Müll und Einwort-Ja auf eine offene Wahl → kurze
Wiederholung der offenen Frage oder `warte`. Nie den Zwei-Fragen-Unklar-Satz
auf ein Fachwort aus `sttHotwords` / Motivkatalog (Rosacea, Nagelpilz,
Screening, Ekzem, …) und nie auf „Wie bitte?“, „Ja, richtig.“, „Hallo“.

---

### 2. „Ich bin die Neue!“ — 82 Anrufe (80 %)

**Quelle:** `bianca/gehirn.py` `HALLO_NEU` / `HALLO_NEU_WER`.

Kommt im **zweiten Zug**, oft **nachdem** die Begrüßung schon „Sie sprechen
mit Bianca, der Telefonassistentin“ gesagt hat. Doppelt, und für eine
bestehende Hautarztpraxis unpassend.

Varianten daneben: „Wir kennen uns noch nicht“ (59 Anrufe), „Schön, dass
Sie anrufen“ / „schön Sie wieder zu hören“ (38 Anrufe).

Beispiel `53986f42`: Anrufer „Hallo, Busch, guten Morgen!“ →
„Wir kennen uns noch nicht. Ich bin die Neue! Guten Morgen. Wie kann ich Ihnen helfen?“
— obwohl der Mann nur seinen Namen sagt und einen Termin will.

**Soll Blessing:** Hallo-Eisbrecher aus. Bekannter Anrufer: Name einmal,
dann Job. Unbekannt: ein „Guten Tag.“ plus offene Job-Frage. Kein „Neue“.

---

### 3. Presence / Anker-Geschwätz — „Sind Sie noch dran?“ 51, „Ich bin noch da“ 55, „Meine Frage war“ 44

Maschine (`kern/stille`, Frage-Anker). In 22 Anrufen dieselbe Frage ≥ 3×.

Das wirkt nicht höflich, sondern wie ein Monolog gegen die Leitung.
Besonders Gift, wenn parallel die Unklar-Schleife läuft (`53986f42`,
`50563be8`, `1e53c4d4`).

**Soll Blessing:** Presence höchstens einmal pro Anruf, dann knappe
offene Frage, dann schweigen. „Meine Frage war:“ nur wenn der Anrufer
wirklich vom Faden weg ist — nicht nach jedem STT-Schnipsel.

---

### 4. Katalogfrage nach schon klarem Terminwunsch — 39 Züge / 32 Anrufe

„Worum geht es denn — um eine Hautkontrolle, akute Hautbeschwerden, eine
Beratung oder etwas anderes?“
Quelle: `kern/fachprofil._BESUCHSGRUND_FRAGEN["dermatologie"]`.

Die Frage ist **fachlich richtig**, kommt aber oft **nach** „Ich bräuchte
einen Termin“ und fühlt sich wie Smalltalk an. Schlimmer: wer „Beratung“
oder „etwas anderes“ sagt, bekommt Satz 5.

---

### 5. „Diese Leistung wird in dieser Praxis nicht angeboten“ — 25 Züge / 15 Anrufe

**Quelle:** `kern/fachprofil.nicht_buchbar_antwort`.

Widerspruch: die Katalogfrage **bietet „Beratung“ an**, die Antwort
**Beratung** wird abgelehnt. Blessing hat im Katalog u. a.
„Beratung Allergie“, „Beratung Kosmetik“, „Beratung Botox / Filler“,
„Beratung Entfernung von störenden Hautveränderungen“.

`d64b2cf9`: „Eine Beratung.“ → „Diese Leistung wird in dieser Praxis nicht angeboten.“
`1e53c4d4`: Nagel-/Fußwunden beschrieben → dieselbe Ablehnung, dann
nochmal die Katalogfrage.

**Soll Blessing:** „Beratung“ ohne Zusatz → nachhaken (Allergie / Kosmetik /
Botox / Hautveränderung), nie ablehnen. Dermatologische Beschwerden
(Nagelpilz, Wunde, Ausschlag, Rosacea) → Motiv mappen, nie „nicht angeboten“.

---

### 6. KI-Entlastungs-Sermon — 15 Züge / 14 Anrufe

**Quelle:** `bianca/weiterleiten.ENTLASTUNG` (W-ANMELDUNG).

Vier Sätze, ~40 Wörter, jedes Mal wenn jemand einen Menschen will:

> Ich bin die KI-Telefonassistentin der Praxis und entlaste die Anmeldung.
> Eine direkte menschliche Telefonannahme ist leider nicht möglich, weil die
> Praxis durch Telefonate stark belastet ist und sonst die medizinische
> Versorgung der Patienten darunter leidet. Bitte haben Sie Verständnis, auch
> wenn eine KI-Assistenz am Telefon neu und manchmal schwierig ist. Ich
> verbessere mich mit jedem Anruf und jedem gemeldeten Problem. Worum geht es?

Live: `18b7e81b` („ich möchte gern mit einem Menschen sprechen“),
`880… Huber` nach mehreren gescheiterten Slots.

**Soll Blessing:** Ein Satz. „Ich kann Sie hier am Telefon weiterhelfen —
einen Menschen stelle ich nicht durch. Worum geht es?“ Zweiter Wunsch →
Rückruf anbieten, fertig. Kein Rechtfertigungssermon.

---

### 7. Identitäts-Doppelung — „Habe ich Sie richtig erkannt?“ 34, „für Sie selbst?“ 25

Maschine (W-ANRUFER-CHECK). Bei Blessing oft **nach** schon klarem
Terminwunsch und manchmal **obwohl** der Anrufer unbekannt ist
(`a8fcbcb4`: „Wir kennen uns noch nicht … Gut. Habe ich Sie richtig erkannt?“).

Ein Arzt, ein Kalender — „für Sie selbst?“ ist selten nötig, außer ein
Dritter ist im Satz.

**Soll Blessing:** Check nur bei echtem CF-Treffer. Kein Check nach
„Wir kennen uns noch nicht“. „Für Sie selbst?“ nur nach Dritt-Signal.

---

### 8. Behandler-Frage bei einem Arzt — 25 Züge / 19 Anrufe

„Wissen Sie noch, bei welchem Behandler Sie zuletzt waren?“
Blessing hat **einen** Kalender: Doktor Charlotte Blessing.

**Soll Blessing:** Frage streichen. Bestand → Kartei, sonst still
Doktor Blessing.

---

### 9. „Kann ich sonst noch etwas für Sie tun?“ — 36 Züge / 28 Anrufe

Formel-Frage, live bis zur Schleife (bekannt aus `a8fcbcb4`, 13×).
Nach gescheiterter Buchung oder nach Unklar wirkt sie höhnisch.

**Soll Blessing:** Höchstens einmal nach **erfolgreichem** Abschluss.
Nach Fehler / Notiz: Abschied, nicht noch eine Runde Smalltalk.

---

### 10. Doktor-Notiz-Zusatz — 14 Züge / 11 Anrufe

**Quelle:** `gehirn.arzt_notiz_frage`

> Soll ich für den Termin noch eine Notiz für den Doktor anlegen?
> Irgendeine besondere Frage, auf die er eingehen soll?

Zusatzfrage **nach** dem Ja zum Slot, **vor** der Nummer. Der Anrufer
will den Termin, nicht ein zweites Anamnesegespräch.

**Soll Blessing:** Frage aus. Wortlaut des Anliegens still in die
Terminnotiz, wenn er den gebuchten Grund nicht deckt (gibt es schon).

---

### 11. LLM-Empathie und Scheinmedizin — 19 Züge

Freies Modell, Talk-Floor. Keine Aufgabe.

| Anrufer | Bianca | Anruf |
| --- | --- | --- |
| Haut-Bedenken, „Nachsicht“ | „Das klingt nach einer wichtigen Sorge… Meinten Sie Kontrolle oder neues Symptom?“ | `53986f42` |
| Nägel/Fußwunden | „hartnäckiges Problem… unbedingt ärztlich begutachtet werden“ | `1e53c4d4` |
| „Temiserein baden“ (STT) | „sehr spezielle und interessante Behandlung. Ist das ein Tippfehler?“ | `1e53c4d4` |
| Kopfhautwunden Kind | Alter der Tochter erfragen, dann Walk-in plus erfundene Zeiten | `c3ceefdd` |
| „Esneak“ (STT) | „das ist eine gute Idee, die kann man gut im Alltag nutzen“ | `50563be8` |
| verschlossene Tür / alter Termin | „Das klingt so, als hätten Sie eine Frage zu Ihrem letzten Besuch. Darf ich wissen, worum es genau geht?“ | `0f0c686c` |

**Soll Blessing:** Talk-Schicht für Blessing auf `off` oder so eng, dass
nur Job + eine knappe Quittung bleibt. Kein Mitleid, keine Diagnose,
kein Raten über STT-Müll.

---

### 12. Dokument-Mauer als Begrüßung — 18 Züge / 6 Anrufe

Rezept-/Überweisungs-Block inkl. „Eine dritte Person kann sie grundsätzlich
nicht abholen.“ In `1401` (`Zamida`) kommt der **ganze Block schon im
zweiten Zug**, bevor das Anliegen steht.

Die Regel ist richtig (W-BLESSING-AKUT / Vorsprache). Der **Zeitpunkt**
ist falsch: erst wenn jemand wirklich ein Rezept/eine Überweisung verlangt.

---

### 13. Wohlsein — 7 Anrufe

„Wie geht es Ihnen?“ / „das ist ja eine schöne Überraschung!“
`2032` Riedinger: Hallo + Überraschung + Wohlsein + „Was kann ich sonst
noch für Sie tun?“ in **einem** Zug, ohne Anliegen.

Steht schon unter W-HALLO-ANTWORT / `hallo_frage_unpassend` — greift
live zu selten.

---

### 14. Erfundene Öffnungszeiten + Walk-in — Anruf `c3ceefdd`

Blessing-Begrüßung, Notfall-Tochter Kopfhaut. Zwei **verschiedene**
Zeitpläne im selben Gespräch (B05 ≠ B07), plus eine lange Reutlinger
Wegbeschreibung, plus „kommen Sie einfach vorbei, wir sehen sie sofort“.

Walk-in bei Akut **darf** nach der Praxisregel kommen — aber nur mit
**belegten** Zeiten (W-ZEITEN-WACHE). Zwei widersprüchliche Pläne =
Erfindung. Das ist der Vorfall, den der junge Blessing meint, wenn er
sagt, die KI labere.

---

### 15. Kalender tot — 34 Züge / 5 Anrufe

„Der Terminkalender antwortet gerade nicht.“ / „Ich schaue kurz nach.“
Das ist kein Plaudern, sondern ein Betriebsfehler. Trotzdem füllt Bianca
die Totzeit mit Extra-Sätzen. Für Opus: Füller bei Blessing auf einen
kurzen Satz deckeln (`FILLER_MAX` gilt schon — prüfen, warum trotzdem
„Einen Moment. Ich suche… Einen Moment bitte.“ doppelt kommt).

---

## Was der junge Blessing hört (typischer Ablauf)

1. Begrüßung (ok)
2. „Ich bin die Neue!“ (überflüssig)
3. „Habe ich Sie erkannt?“ / „schon mal da?“ / „welcher Behandler?“ (zu viel)
4. Katalog-Menü, dann Ablehnung von „Beratung“
5. Unklar-Satz auf das Fachwort
6. LLM erklärt die Hautlage
7. Presence „Sind Sie noch dran?“
8. Slot, dann Doktor-Notiz-Frage
9. „Sonst noch etwas?“

Das ist Gespräch **um** die Aufgabe herum. Zielablauf:

> Begrüßung → Anliegen (ein Satz) → fehlende Pflichtfelder → Slot →
> Ja → Handy → eintragen → Abschied.

---

## Code-Stellen (Einsteigerkarte)

| Symptom | Datei | Symbol |
| --- | --- | --- |
| Unklar-Zwei-Fragen | `kern/gespraech.py` | `unklar_antwort` |
| Wann Unklar feuert | `bianca/agent.py` | `wirkt_unklar` / `UNKLAR_ANTWORT` |
| „Ich bin die Neue“ | `bianca/gehirn.py` | `HALLO_NEU*` |
| Wohlsein | `bianca/gehirn.py` | `HALLO_ANRUF`, `HALLO_BESUCH` |
| Katalog + nicht angeboten | `kern/fachprofil.py` | `besuchsgrund_frage`, `nicht_buchbar_antwort` |
| KI-Sermon | `bianca/weiterleiten.py` | `ENTLASTUNG` |
| Doktor-Notiz | `bianca/gehirn.py` | `arzt_notiz_frage` |
| Behandler-Frage | `bianca/gehirn.py` | `arztwahl` / `arzt_check` bei `len(calendars)==1` |
| Talk-Floor | `kern/gespraech.py` | `TALK_SCHICHT` |
| Presence | `kern/stille.py` | `PRESENCE`, `GESAMT_MAX` |

Bevorzugter Weg: **mandantenscharfe Kürzung** (`tenantId=="blessing"` oder
`fachgebiet=="dermatologie"`), nicht globale Löschung der Sätze — sonst
bricht MedDent.

---

## Empfohlene Arbeitspakete (Reihenfolge)

1. **Unklar bei Blessing entschärfen** — größter Frequenzhebel, sofort hörbar.
2. **Hallo ohne „Neue“ / ohne Wohlsein** bei Blessing.
3. **„Beratung“ nicht ablehnen**; Ein-Arzt-Kalender ohne Behandlerfrage.
4. **ENTLASTUNG auf einen Satz** bei Blessing.
5. **Arzt-Notiz-Frage aus** bei Blessing.
6. **Talk-Schicht Blessing knapper** (kein Empathie-Essay, kein STT-Raten).
7. **Sonst-noch** nur nach Erfolg, max. 1.

Nicht in diesem Paket: Kalender-HTTP-Ausfälle, `needs_phone` (liegt als
W-AKTE-HANDY, Anruf `a8fcbcb4`).

---

## Goldene Gegenproben (nicht kaputtmachen)

- Akute Haut + Sprechzeit → Sofortkommen-Regel bleibt.
- „Ich brauche ein Rezept“ → Vorsprache, kein Abholversprechen.
- Zahnwunsch bei Blessing → Fach-Wache, kein PZR/Bleaching.
- Belegte Öffnungszeiten aus Standort/Prompt dürfen gesagt werden.
- MedDent sagt weiter „Ich bin die Neue!“, wenn der Chef das so will.

---

## Evidenz-Anrufe zum Nachstellen (ohne Write)

| ID | Warum |
| --- | --- |
| `53986f42` | Neue + Unklar + Empathie + Vornamen-Schleife, 8 min |
| `50563be8` | „Ja, richtig“ = Unklar; Slot ignoriert „kein Donnerstag“; STT „Esneak“ wird Thema |
| `1e53c4d4` | LLM rätselt über STT; Leistung nicht angeboten trotz Nagelpilz |
| `d64b2cf9` | „Beratung“ abgelehnt |
| `18b7e81b` | Mensch-Wunsch → ENTLASTUNG-Sermon |
| `c3ceefdd` | Notfall Kind: Anamnese, erfundene Zeiten, Walk-in |
| `a8fcbcb4` | Neue + erkannt? + Buchung scheitert + Sonst-noch-Schleife |
| `0331a945` | Rosacea/Medikamente = Unklar, dann „nicht angeboten“ |
