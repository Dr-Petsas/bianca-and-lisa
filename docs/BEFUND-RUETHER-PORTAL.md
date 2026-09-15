# Befund Praxis Dr. Denise Rüther — was im Portal noch fehlt

Stand 15.09.2026, alles read-only gegen die Live-Daten geprüft
(`clients/AWdFeDldR81P3jmiq869`, Standort `loc_d7gfcuss`, DID
+49 211 542 244 160, Assistent **Ben**).

Der Code ist fertig: Ben spricht mit seiner männlichen Stimme, stellt sich als
Ben vor (W-STIMME-MANDANT) und erfindet seit dem 15.09. keine Öffnungszeiten
mehr (W-ZEITEN-WACHE). Was jetzt noch schiefgeht, liegt an der Konfiguration im
Portal — fünf Punkte, nach Dringlichkeit.

## 1. Zwei aktive Agenten auf derselben Nummer (BLOCKER)

| Dokument | Name | inbound | enabled | Begrüßung | Termin-Tools |
| --- | --- | --- | --- | --- | --- |
| `LtHkW6I1xSwDpWy5M3vy` | Ben | ja | ja | vorhanden | AN |
| `jeLZftpLKZdQaDUwVml6` | Bianca | ja | ja | **leer** | AUS |

Beide hängen an `+4921154244160`. Heute gewinnt Ben — aber nur, weil die
Cloud Function den ersten Treffer nach Dokument-ID nimmt. Wird ein Feld
geändert oder ein Index neu gebaut, kann genauso gut der Bianca-Datensatz
gewinnen: dann meldet sich der Anruf **ohne Begrüßung und ohne
Buchungsmöglichkeit**.

→ Der Datensatz `jeLZftpLKZdQaDUwVml6` muss gelöscht oder auf `enabled=false`
gesetzt werden.

## 2. Der Praxis-Prompt ist leer (BLOCKER für alles Fachliche)

Von den Prompt-Feldern des Agenten ist nur `systemPrompt` gefüllt (462 Zeichen:
Datum, Zeitzone, Anrede-Hinweis). `rolePrompt`, `tasksPrompt`,
`specialFeaturesPrompt`, `locationPrompt`, `patientsPrompt`,
`appointmentPrompt`, `mandatoryPrompt` sind **leer**.

Damit weiß Ben nichts über die Praxis: keine Behandlerinnen, keine Adresse,
keine Regeln zu Rezepten, Befunden oder Schwangerschaft. Genau daraus entstand
die Erfindung der Öffnungszeiten — das Modell füllt die Lücke, wenn niemand sie
füllt. Der Wächter fängt das jetzt ab, aber ehrliches Schweigen ist nur die
zweitbeste Antwort.

→ Text steht fertig in [`docs/prompt-ruether.md`](prompt-ruether.md) (drei
Felder, wortgleich einfügen: Rolle, Besonderheiten, Standort).

## 3. Öffnungszeiten stehen auf dem Portal-Default

`openingHours` trägt für **alle sieben Tage** 08:00–18:00. Das ist die
unveränderte Vorgabe aus der Anlage, kein echter Praxisplan (Sonntag
inbegriffen). `kern/standort.py` verwirft genau dieses Muster absichtlich
(„nie raten") — Ben hat zu den Zeiten also keine Quelle und sagt seit dem
15.09.: „Zu den Öffnungszeiten liegen mir keine verlässlichen Angaben vor —
das Praxisteam sagt Ihnen das genau."

→ Echte Zeiten in den **Standorteinstellungen** eintragen. Dann liest Ben sie
von dort vor, ohne dass am Prompt etwas geändert werden muss.

## 4. 21 von 31 Besuchsgründen sind telefonisch gesperrt (fachlich kritisch)

`allowOnlineBooking` ist nur bei 10 Terminarten gesetzt. Gesperrt sind
ausgerechnet die Kernleistungen:

**Telefonisch buchbar (10)** — durchweg Beratungstermine:
Endometriose Erstberatung (45), Erstes Gespräch Teenager (30),
HPV-Impfberatung (15), Hormonstatus Besprechung (30),
Kinderwunsch Erstberatung (45), Mammographie-Befundbesprechung (20),
Osteoporose-Risiko Beratung (20), Pillenwechsel Beratung (20),
Verhütungsberatung (30), Wechseljahresberatung (30).

**Gesperrt (21)** — u. a. Krebsvorsorge, Krebsvorsorge Wechseljahre,
PAP/HPV-Abstrich, Schwangerschaft Ersttermin, Schwangerschaft Vorsorge,
Ersttrimester-Screening, CTG-Kontrolle, Wochenbett-Nachkontrolle,
Spirale einsetzen, Spiralenkontrolle, Kolposkopie, Konisation,
Brustultraschall, Knoten in der Brust, Starke Regelschmerzen,
Zyklusstörung abklären, Zyklusmonitoring, Hormontherapie Kontrolle,
Chlamydien-Test, STD-Screening, Vaginale Infektion.

Live gegengeprüft (nur Lesen, kein Termin geschrieben): Ben ordnet die Wünsche
sauber zu — „Krebsvorsorge" trifft „GYN Krebsvorsorge", „Abstrich machen"
trifft „PAP/HPV-Abstrich". Die Plattform liefert für diese Motive dann aber
**null Zeiten**, weil `getFreeTimeSlots` die Online-Sperre auch dem
Telefon-Agenten gegenüber durchsetzt.

**Und das ist der eigentlich gefährliche Teil:** die Ausweich-Mechanik
(W-MOTIV-KONSISTENT) sucht in so einem Fall mit dem „Kontroll"-Motiv der Praxis
weiter. Rüther führt kein Kontroll-Motiv — also greift der letzte Rückfall und
nimmt den **ersten harmlosen Eintrag der Liste**. Das ist hier
„GYN Endometriose Erstberatung", 45 Minuten. Eine Anruferin, die eine
Krebsvorsorge möchte, bekäme einen 45-Minuten-Endometriose-Erstberatungstermin
(mit Notiz, dass eigentlich Krebsvorsorge gewünscht war). Fachlich falsch und
dreimal so lang wie nötig.

→ Zwei Wege, am besten beide:
1. Im Portal die Online-Buchung für die Vorsorge-/Kontroll-Motive freischalten
   (dann buchen die Anruferinnen genau das, was sie wollen).
2. Code-seitig: das Ausweich-Motiv darf nur ein echtes Kontroll-/Vorsorge-Motiv
   sein — sonst gar keines, dafür ehrliche Auskunft plus Rückrufnotiz. Das ist
   ein eigener, kleiner Patch (siehe „Nächster Schritt").

## 5. Dialplan auf dem Live-Asterisk

Der Eintrag für 4160 liegt als Referenzkopie in
`sip_bridge/extensions_bianca.conf` (feste AudioSocket-UUID `…4160`, Brücke und
`BRIDGE_DID_MAP` kennen sie, `test_did_4160_fuehrt_zu_ben` hält das fest). Auf
dem Live-Asterisk (212.132.104.205) fehlt er noch — von hier gibt es keinen
Shell-Zugang. Ohne diesen Eintrag klingelt die Nummer nicht bei Ben.

## Nächster Schritt im Code

Punkt 4, zweiter Teil: `kern/calendar._kontrolle_ersatz` akzeptiert heute jedes
Motiv, das `tenants._sicheres_default` liefert — auch den blinden „erster
Eintrag"-Rückfall. Der Patch prüft, ob der Ersatz wirklich nach Kontrolle/
Vorsorge/Nachkontrolle aussieht, und liefert sonst `None`: dann sagt Ben
ehrlich, dass diese Terminart telefonisch nicht buchbar ist, und legt eine
Rückrufnotiz an. MedDent und Thaler haben „KCH Kontrolluntersuchung" und
bleiben davon unberührt.
