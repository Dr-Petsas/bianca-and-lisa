"""Satz-Katalog des Baukasten-Tests (Chef 29.08.2026).

Jeder Baustein traegt ~10 alternative Formulierungen — daraus baut der
Story-Bauer (geschichten.py) einen Testanruf. Saetze mit Platzhaltern
({tag}, {vorname}, {nachname}, {kasse}) werden erst beim Story-Bau zu
konkretem Text; das Audio entsteht on demand je (Stimme, Text) und wird
unter tests/baukasten/audio/ gecacht.

Die Telefon-Varianten sprechen IMMER 01776004600 (DEV_PHONE) — als
Zahlwoerter in verschiedenen Gruppierungen, alle von bianca/telefon.aus_satz
rueckwaerts parsebar (Test in test_baukasten.py).
"""

from __future__ import annotations

# ---------------------------------------------------------------- Eroeffnung

EROEFFNUNG_MACHEN = [
    "Guten Tag, ich hätte gerne einen Termin.",
    "Hallo, ich würde gern einen Termin ausmachen.",
    "Schönen guten Tag, ich bräuchte mal wieder einen Termin bei Ihnen.",
    "Guten Morgen, ich möchte gerne einen Termin vereinbaren.",
    "Hallo, können Sie mir einen Termin geben?",
    "Guten Tag, ich rufe an, weil ich einen Termin brauche.",
    "Hallo, ich wollte fragen, ob ich kurzfristig einen Termin bekommen kann.",
    "Guten Tag, ich müsste mal wieder vorbeikommen — geht da was?",
    "Hallo, ich bräuchte bitte einen Termin in Ihrer Praxis.",
    "Guten Tag, ich möchte einen Termin machen, am besten bald.",
]

EROEFFNUNG_ABSAGEN = [
    "Guten Tag, ich muss leider meinen Termin absagen.",
    "Hallo, ich möchte einen Termin stornieren.",
    "Guten Tag, ich kann meinen Termin leider nicht wahrnehmen.",
    "Hallo, mir ist was dazwischengekommen, ich muss den Termin absagen.",
    "Guten Tag, ich sage hiermit meinen Termin ab.",
    "Hallo, ich schaffe es zu meinem Termin leider nicht.",
    "Guten Tag, ich müsste einen Termin bei Ihnen absagen.",
    "Hallo, ich möchte meinen Termin gerne canceln.",
    "Guten Tag, ich falle leider aus und muss den Termin absagen.",
    "Hallo, bitte streichen Sie meinen Termin.",
]

EROEFFNUNG_VERSCHIEBEN = [
    "Guten Tag, ich müsste meinen Termin leider verschieben.",
    "Hallo, ich möchte meinen Termin gerne umbuchen.",
    "Guten Tag, kann ich meinen Termin auf einen anderen Tag legen?",
    "Hallo, mir ist etwas dazwischengekommen — ich muss den Termin verlegen.",
    "Guten Tag, ich würde meinen Termin gern verschieben.",
    "Hallo, ich brauche einen neuen Termin, der alte passt nicht mehr.",
    "Guten Tag, geht es, meinen Termin zu verschieben?",
    "Hallo, ich möchte meinen Termin auf später verlegen.",
    "Guten Tag, der Termin passt mir nicht mehr, ich müsste umplanen.",
    "Hallo, können wir meinen Termin bitte verschieben?",
]

EROEFFNUNG_ERFAHREN = [
    "Guten Tag, wann ist eigentlich mein nächster Termin?",
    "Hallo, ich wollte fragen, wann mein Termin ist.",
    "Guten Tag, ich habe meinen Terminzettel verlegt — wann muss ich kommen?",
    "Hallo, können Sie mir sagen, wann ich dran bin?",
    "Guten Tag, ich weiß nicht mehr, wann mein Termin ist.",
    "Hallo, ich glaube ich habe bald einen Termin, wissen Sie wann?",
    "Guten Tag, ich wollte nur kurz meinen Termin erfragen.",
    "Hallo, wann war noch gleich mein Termin bei Ihnen?",
    "Guten Tag, ich habe vergessen, wann mein Termin ist — können Sie nachsehen?",
    "Hallo, steht bei Ihnen ein Termin für mich im Kalender?",
]

# ------------------------------------------------------------ Schonmal-Frage

SCHONMAL_JA = [
    "Ja, ich war schon öfter bei Ihnen.",
    "Ja, ich bin schon lange Patient bei Ihnen.",
    "Ja klar, ich komme ja jedes Jahr.",
    "Ja, ich war erst letztes Jahr da.",
    "Ja, ich bin Patientin bei Ihnen.",
    "Ja, ich war schon mal da.",
    "Ja, schon ein paar Mal.",
    "Ja, ich bin Stammpatient.",
    "Ja, ich war vor einer Weile bei Ihnen in Behandlung.",
    "Ja, ich bin bei Ihnen in Behandlung.",
]

SCHONMAL_NEIN = [
    "Nein, ich war noch nie bei Ihnen.",
    "Nein, ich bin ganz neu.",
    "Nein, das wäre das erste Mal.",
    "Nein, ich bin Neupatient.",
    "Nein, noch nie — ich bin gerade erst hergezogen.",
    "Nein, ich wurde Ihnen empfohlen, ich war noch nicht da.",
    "Nein, ich suche gerade einen neuen Zahnarzt.",
    "Nein, bisher war ich woanders.",
    "Nein, ich kenne Ihre Praxis noch gar nicht.",
    "Nein, das ist mein erster Anruf bei Ihnen.",
]

# ------------------------------------------------------------- Behandlerwahl

ARZT_MUSTER = [
    "Bei Doktor {arzt}.",
    "Zu Doktor {arzt}, bitte.",
    "Ich war zuletzt bei Doktor {arzt}.",
    "Doktor {arzt}.",
    "Am liebsten bei Doktor {arzt}.",
    "Ich glaube, das war Doktor {arzt}.",
    "Wenn es geht, zu Doktor {arzt}.",
    "Bei Herrn Doktor {arzt} bitte.",
    "Immer bei Doktor {arzt}.",
    "Das müsste Doktor {arzt} gewesen sein.",
]

ARZT_EGAL = [
    "Das ist mir egal, Hauptsache bald.",
    "Egal, wer gerade Zeit hat.",
    "Da habe ich keine Präferenz.",
    "Ist mir gleich, nehmen Sie den nächsten freien.",
    "Egal, ich kenne ja noch niemanden bei Ihnen.",
    "Das dürfen Sie aussuchen.",
    "Ganz egal, wer zuerst kann.",
    "Mir egal — wer hat denn am schnellsten was frei?",
    "Keine Präferenz, gerne der erste freie Termin.",
    "Das überlasse ich Ihnen.",
]

# ------------------------------------------------------------- Besuchsgruende

GRUND_ZAHNSCHMERZEN = [
    "Ich habe ziemlich starke Zahnschmerzen.",
    "Mein Zahn tut seit gestern richtig weh.",
    "Ich habe Zahnschmerzen, unten links pocht es.",
    "Es geht um Zahnschmerzen, das zieht bis ins Ohr.",
    "Ich habe seit ein paar Tagen Schmerzen an einem Backenzahn.",
    "Mir tut ein Zahn weh, vor allem bei Kaltem.",
    "Ich habe Schmerzen beim Kauen, da stimmt was nicht.",
    "Ein Zahn macht Ärger, die Schmerzen werden immer schlimmer.",
    "Ich habe Zahnweh und halte das nicht mehr lange aus.",
    "Es pocht an einem Zahn, ich glaube, da ist was entzündet.",
]

GRUND_IMPLANTAT = [
    "Es geht um eine Implantatberatung.",
    "Ich möchte gern ein Implantat besprechen.",
    "Ich interessiere mich für ein Zahnimplantat.",
    "Mir fehlt ein Zahn, ich hätte gern eine Beratung zum Implantat.",
    "Ich wollte mal durchsprechen, ob ein Implantat für mich infrage kommt.",
    "Es geht um eine Implantatbesprechung.",
    "Ich brauche einen Beratungstermin wegen eines Implantats.",
    "Ich überlege, mir ein Implantat machen zu lassen.",
    "Mein alter Zahnarzt hat ein Implantat empfohlen, das würde ich gern besprechen.",
    "Ich hätte gerne Informationen zu einem Implantat, am besten in einem Termin.",
]

GRUND_INVISALIGN = [
    "Ich hätte gern eine Invisalign-Beratung.",
    "Es geht um Invisalign, diese durchsichtigen Schienen.",
    "Ich interessiere mich für Invisalign.",
    "Ich möchte meine Zähne mit Invisalign richten lassen.",
    "Machen Sie auch Invisalign? Da hätte ich gern einen Beratungstermin.",
    "Ich wollte mich zu Invisalign beraten lassen.",
    "Es geht um eine Aligner-Behandlung, Invisalign.",
    "Ich habe von Invisalign gehört und möchte das gern besprechen.",
    "Eine Freundin hat Invisalign gemacht, das will ich auch — geht das bei Ihnen?",
    "Ich hätte gern einen Termin für eine Invisalign-Beratung.",
]

GRUND_SCHIEFE_ZAEHNE = [
    "Meine Zähne sind schief, das möchte ich gerne richten lassen.",
    "Ich will meine schiefen Zähne gerade machen lassen.",
    "Es geht darum, meine Zähne begradigen zu lassen.",
    "Meine unteren Zähne sind ziemlich schief geworden.",
    "Ich störe mich an meinen schiefen Vorderzähnen.",
    "Ich hätte gern eine Beratung, weil meine Zähne schief stehen.",
    "Meine Zähne haben sich verschoben, die sollen wieder gerade werden.",
    "Ich möchte meine Zähne gerade richten lassen.",
    "Die Zähne oben stehen schief, was kann man da machen?",
    "Ich würde gern besprechen, wie ich meine Zähne gerade bekomme.",
]

GRUND_SCHLAFSCHIENE = [
    "Es geht um eine Schlafschiene.",
    "Ich brauche eine Schnarchschiene.",
    "Ich hätte gern einen Termin wegen einer Schlafschiene.",
    "Mein Partner sagt, ich schnarche furchtbar — ich bräuchte so eine Schiene.",
    "Es geht um eine Schiene gegen das Schnarchen.",
    "Ich habe Schlafapnoe und soll eine Schiene bekommen.",
    "Ich möchte eine Narval-Schiene anpassen lassen.",
    "Wegen meiner Schlafapnoe bräuchte ich eine Unterkieferschiene.",
    "Ich schnarche stark und möchte eine Schnarchschiene besprechen.",
    "Der Lungenarzt meinte, eine Schnarchschiene könnte mir helfen.",
]

GRUND_UEBERWEISUNG_GRUEGER = [
    "Ich bin von Doktor Grüger überwiesen worden.",
    "Doktor Grüger hat mich zu Ihnen überwiesen.",
    "Ich komme auf Überweisung von Doktor Grüger.",
    "Doktor Grüger aus dem Schlaflabor schickt mich zu Ihnen.",
    "Ich habe eine Überweisung von Doktor Grüger dabei.",
    "Doktor Grüger meinte, ich soll mich bei Ihnen melden.",
    "Ich soll auf Anraten von Doktor Grüger zu Ihnen kommen.",
    "Die Überweisung ist von Doktor Grüger.",
    "Doktor Grüger hat mich wegen der Schiene zu Ihnen geschickt.",
    "Ich wurde vom Schlaflabor bei Doktor Grüger zu Ihnen überwiesen.",
]

GRUND_UEBERWEISUNG_LANGE = [
    "Ich bin von Doktor Lange überwiesen worden.",
    "Doktor Lange hat mich zu Ihnen überwiesen.",
    "Ich komme auf Überweisung von Doktor Lange.",
    "Doktor Lange aus der Schlafklinik schickt mich.",
    "Ich habe eine Überweisung von Doktor Lange.",
    "Doktor Lange meinte, Sie machen diese Schienen.",
    "Ich soll mich auf Empfehlung von Doktor Lange bei Ihnen vorstellen.",
    "Die Überweisung kommt von Doktor Lange.",
    "Doktor Lange hat mich wegen des Schnarchens zu Ihnen geschickt.",
    "Ich wurde von Doktor Lange aus dem Schlaflabor überwiesen.",
]

GRUND_UEBERWEISUNG_SCHLAFLABOR = [
    "Ich bin vom Schlaflabor zu Ihnen überwiesen worden.",
    "Das Schlaflabor hat mich zu Ihnen geschickt.",
    "Ich komme mit einer Überweisung aus dem Schlaflabor.",
    "Ich war im Schlaflabor, die haben mich an Sie verwiesen.",
    "Vom Schlaflabor hieß es, Sie passen diese Schienen an.",
    "Die Schlafklinik hat mich an Ihre Praxis überwiesen.",
    "Ich habe eine Überweisung vom Schlaflabor für so eine Schiene.",
    "Nach der Untersuchung im Schlaflabor soll ich jetzt zu Ihnen.",
    "Das Schlaflabor meinte, ich brauche eine Schiene von Ihnen.",
    "Ich komme direkt aus dem Schlaflabor mit einer Überweisung.",
]

GRUND_PZR = [
    "Ich hätte gern eine professionelle Zahnreinigung.",
    "Es wird mal wieder Zeit für eine Zahnreinigung.",
    "Ich brauche einen Termin zur Zahnreinigung.",
    "Einmal Zahnreinigung, bitte.",
    "Ich möchte eine PZR machen lassen.",
    "Meine letzte Zahnreinigung ist ewig her, ich bräuchte mal wieder eine.",
    "Ich wollte einen Termin für die professionelle Zahnreinigung ausmachen.",
    "Zahnreinigung bitte, am liebsten zeitnah.",
    "Ich hätte gern wieder meine halbjährliche Zahnreinigung.",
    "Können Sie mir einen Termin zur Zahnreinigung geben?",
]

GRUND_KONTROLLE = [
    "Nur zur Kontrolle.",
    "Ich brauche einen Kontrolltermin.",
    "Einfach mal wieder alles durchchecken lassen.",
    "Die jährliche Kontrolle steht an.",
    "Ich möchte einen Termin zur Vorsorge.",
    "Es ist nichts Akutes, nur die normale Kontrolle.",
    "Ich brauche den Stempel fürs Bonusheft, also eine Kontrolle.",
    "Routineuntersuchung, bitte.",
    "Ich war lange nicht mehr da, einmal Kontrolle bitte.",
    "Nur nachsehen lassen, ob alles in Ordnung ist.",
]

# --------------------------------------------------------------- Terminwunsch

WUNSCH_MUSTER = [
    "Nächste Woche {tag} bitte, die Uhrzeit ist mir egal.",
    "Am liebsten nächste Woche {tag}, egal um wie viel Uhr.",
    "Geht was nächste Woche am {tag}? Die Uhrzeit ist egal.",
    "Nächste Woche {tag} würde mir gut passen, Uhrzeit egal.",
    "Ich hätte gern nächste Woche {tag}, da bin ich flexibel.",
    "Wenn möglich nächste Woche {tag} — zur Not auch eine andere Uhrzeit.",
    "Nächsten {tag} bitte, mir ist jede Uhrzeit recht.",
    "Können wir nächste Woche {tag} machen? Uhrzeit ist mir wirklich egal.",
    "Nächste Woche {tag} wäre perfekt, ich richte mich nach Ihnen.",
    "Bitte nächste Woche {tag}, ganz gleich zu welcher Uhrzeit.",
]

SLOT_FRUEHER = [
    "Hm, geht es vielleicht etwas früher?",
    "Das ist mir eigentlich zu spät — haben Sie was Früheres?",
    "Gibt es auch einen früheren Termin?",
    "Etwas früher wäre mir lieber.",
    "Haben Sie noch etwas am früheren Vormittag?",
    "Können wir das früher legen?",
    "Früher ginge bei mir besser.",
    "Gibt es an dem Tag noch was davor?",
    "Das ist spät — was haben Sie denn früher frei?",
    "Lieber früher, wenn das möglich ist.",
]

SLOT_SPAETER = [
    "Geht es vielleicht etwas später?",
    "Das ist mir zu früh — haben Sie auch was Späteres?",
    "Gibt es einen späteren Termin an dem Tag?",
    "Etwas später wäre mir lieber.",
    "Haben Sie noch etwas am Nachmittag?",
    "Können wir das später legen?",
    "Später ginge bei mir besser, ich muss vorher arbeiten.",
    "Gibt es an dem Tag noch was danach?",
    "Das ist früh — was haben Sie denn später noch frei?",
    "Lieber später, wenn das möglich ist.",
]

SLOT_ANNAHME = [
    "Ja, den nehme ich.",
    "Gut, dann machen wir das so.",
    "In Ordnung, der passt mir.",
    "Ja, das geht klar.",
    "Okay, den Termin nehme ich gerne.",
    "Ja, super, das passt.",
    "Einverstanden, buchen Sie den bitte.",
    "Ja, dann nehmen wir den.",
    "Der passt tatsächlich, ja gerne.",
    "Alles klar, dann so.",
]

# ------------------------------------------------------------------ Identitaet

NAME_MUSTER = [
    "Ich heiße {vorname} {nachname}.",
    "Mein Name ist {vorname} {nachname}.",
    "{vorname} {nachname}.",
    "{nachname}, {vorname} {nachname}.",
    "Ich bin {vorname} {nachname}.",
    "Der Name ist {vorname} {nachname}.",
    "{vorname} {nachname} ist mein Name.",
    "Ich heiße {nachname}, {vorname} {nachname}.",
    "Also, mein Name ist {vorname} {nachname}.",
    "{vorname} {nachname}, wie der Vorname schon sagt.",
]

TELEFON = [
    "Meine Nummer ist null eins sieben sieben, sechs null null, vier sechs null null.",
    "Die Handynummer lautet null eins sieben sieben, sechs null null, vier sechs, null null.",
    "Null eins sieben sieben, sechshundert, sechsundvierzig, null null.",
    "Sie erreichen mich unter null eins sieben sieben, sechs null null, vier sechs null null.",
    "Null eins siebenundsiebzig, sechs null null, vier sechs null null.",
    "Ich gebe Ihnen meine Handynummer: null eins sieben sieben, sechs null null, vier sechs null null.",
    "Null eins sieben sieben, sechshundert, vier sechs, doppel null.",
    "Notieren Sie gern: null eins sieben sieben, sechs null null, sechsundvierzig, null null.",
    "Meine Mobilnummer: null eins sieben sieben, sechs, null, null, vier, sechs, null, null.",
    "Null eins sieben sieben, sechs null null, vier sechs null null — das ist mein Handy.",
]

READBACK_JA = [
    "Ja, das stimmt.",
    "Ja, genau.",
    "Richtig.",
    "Ja, korrekt.",
    "Genau so ist es.",
    "Ja, die Nummer stimmt.",
    "Stimmt genau.",
    "Ja, alles richtig.",
    "Korrekt, ja.",
    "Ja, passt.",
]

READBACK_NEIN = [
    "Nein, das war nicht richtig — noch mal: null eins sieben sieben, sechs null null, vier sechs null null.",
    "Nicht ganz — ich wiederhole: null eins sieben sieben, sechs null null, vier sechs null null.",
    "Nein, da stimmt was nicht — ich sage sie noch mal: null eins sieben sieben, sechs null null, vier sechs null null.",
    "Das stimmt so nicht, ich sage sie noch mal langsam: null eins sieben sieben, sechs null null, vier sechs null null.",
    "Nein. Null eins sieben sieben, sechshundert, sechsundvierzig, null null.",
]

# ----------------------------------------------------------------- Versicherung

KASSEN_PRIVAT = ["der Debeka", "der Allianz", "der DKV", "Signal Iduna", "der AXA",
                 "der Barmenia", "der HUK", "der Gothaer", "der Continentale", "der ARAG"]
KASSEN_GESETZLICH = ["der AOK", "der Techniker Krankenkasse", "der Barmer", "der DAK",
                     "der IKK classic", "der KKH", "der hkk", "der Knappschaft",
                     "der BKK", "der Techniker"]

VERSICHERUNG_PRIVAT_MUSTER = [
    "Ich bin privat versichert.",
    "Privat, bei {kasse}.",
    "Ich bin Privatpatient, bei {kasse}.",
    "Privat versichert, {kasse}.",
    "Ich bin bei {kasse}, privat.",
    "Privatpatientin, bei {kasse}.",
    "Ich zahle privat, versichert bin ich bei {kasse}.",
    "Privat — {kasse}.",
    "Bei {kasse}, das ist eine private Versicherung.",
    "Ich bin privat bei {kasse} versichert.",
]

VERSICHERUNG_GESETZLICH_MUSTER = [
    "Ich bin gesetzlich versichert.",
    "Gesetzlich, bei {kasse}.",
    "Ich bin Kassenpatient, bei {kasse}.",
    "Gesetzlich versichert, {kasse}.",
    "Ich bin bei {kasse}.",
    "Kassenpatientin, bei {kasse}.",
    "Ganz normal gesetzlich, bei {kasse}.",
    "Gesetzlich — {kasse}.",
    "Bei {kasse}, gesetzlich.",
    "Ich bin gesetzlich bei {kasse} versichert.",
]

VERSICHERUNG_GLEICH = [
    "Nein, da hat sich nichts geändert.",
    "Alles beim Alten.",
    "Nein, das ist noch genauso.",
    "Unverändert.",
    "Nein, ich bin immer noch genauso versichert.",
    "Da ist alles gleich geblieben.",
]

VERSICHERUNG_WECHSEL = [
    "Ja, das hat sich geändert — ich bin jetzt privat versichert.",
    "Ja, ich bin inzwischen Privatpatient.",
    "Ja, ich habe gewechselt, jetzt privat.",
    "Ja, das ist jetzt anders: ich bin gesetzlich versichert.",
    "Ja, ich bin wieder in die gesetzliche gewechselt.",
    "Ja, seit Januar bin ich privat versichert.",
]

# --------------------------------------------------------------------- Diverses

PZR_JA = [
    "Ja, gerne gleich mit dazu.",
    "Ja, das können wir mitmachen.",
    "Gute Idee, ja bitte.",
    "Ja, wenn das zusammen geht, gerne.",
    "Ja, bitte gleich mit Zahnreinigung.",
    "Ja, machen wir mit.",
]

PZR_NEIN = [
    "Nein danke, erst mal nicht.",
    "Nein, nur der Termin bitte.",
    "Diesmal nicht, danke.",
    "Nein, das mache ich ein andermal.",
    "Nein danke, das lasse ich diesmal weg.",
    "Nein, heute nur das eine Anliegen.",
]

BESTAETIGUNG_JA = [
    "Ja, bitte.",
    "Ja, genau so.",
    "Ja, machen Sie das so.",
    "Ja, einverstanden.",
    "Ja, das passt so.",
    "Ja, gerne.",
    "Ja, so machen wir das.",
    "Ja, in Ordnung.",
    "Ja, bestätige ich.",
    "Ja, alles richtig so.",
]

ABSCHIED = [
    "Vielen Dank, auf Wiederhören!",
    "Danke schön, tschüss!",
    "Super, danke Ihnen. Auf Wiederhören.",
    "Dankeschön, bis dann!",
    "Vielen Dank für Ihre Hilfe, auf Wiederhören.",
    "Danke, das war's schon. Tschüss!",
    "Alles klar, vielen Dank. Auf Wiederhören!",
    "Danke sehr, einen schönen Tag noch!",
    "Prima, danke. Bis dann!",
    "Herzlichen Dank, auf Wiederhören.",
]

# -------------------------------------------------------- Abschweifer (Themen)

ABSCHWEIFER = {
    "wehgetan": [
        "Ach, und eins noch: der letzte Termin war furchtbar, der Doktor hat mir richtig wehgetan.",
        "Ich muss sagen, beim letzten Mal hat das ganz schön wehgetan.",
        "Letztes Mal war schlimm — die Spritze hat höllisch wehgetan.",
        "Ich habe noch drei Tage nach dem letzten Termin Schmerzen gehabt.",
        "Beim letzten Bohren hat mir der Doktor richtig wehgetan, das sage ich ehrlich.",
        "Der letzte Besuch war eine Qual, das hat so wehgetan.",
        "Ich sag's mal so: nach dem letzten Termin konnte ich zwei Tage nichts kauen.",
        "Beim letzten Mal war die Betäubung zu schwach, das hat richtig wehgetan.",
        "Ehrlich gesagt habe ich etwas Angst, letztes Mal hat es sehr wehgetan.",
        "Der letzte Eingriff hat mehr wehgetan als versprochen.",
    ],
    "verschoben2x": [
        "Mein letzter Termin ist übrigens zweimal von Ihnen verschoben worden.",
        "Ich muss loswerden: Sie haben meinen Termin schon zweimal verschoben.",
        "Beim letzten Mal wurde mein Termin zweimal verlegt, das war ärgerlich.",
        "Ihr habt meinen Termin zweimal umgeschmissen, das fand ich nicht so toll.",
        "Zweimal wurde mein Termin verschoben — ich hoffe, diesmal klappt es.",
        "Letztes Jahr wurde mein Termin gleich zweimal von der Praxis abgesagt.",
        "Ich hoffe, der Termin hält diesmal — er wurde ja schon zweimal verschoben.",
        "Nicht böse gemeint, aber mein Termin wurde von Ihnen zweimal verlegt.",
        "Mein Mann meinte, bei ihm wurde der Termin auch zweimal verschoben.",
        "Zweimal verschoben und einmal ausgefallen — das lief zuletzt nicht rund.",
    ],
    "rechnung_teuer": [
        "Die letzte Rechnung war übrigens viel zu teuer, fand ich.",
        "Ich fand die letzte Rechnung ganz schön happig.",
        "Sagen Sie mal, warum war die letzte Rechnung so hoch?",
        "Die Rechnung vom letzten Mal hat mich fast umgehauen.",
        "Ich habe mich über die letzte Rechnung geärgert, die war zu teuer.",
        "Die letzte Behandlung war teurer als besprochen.",
        "Bei der letzten Rechnung bin ich fast vom Stuhl gefallen.",
        "Die Rechnung war deutlich höher als angekündigt.",
        "Ich fand die Abrechnung beim letzten Mal überzogen.",
        "Die letzte Rechnung müssen wir bei Gelegenheit mal besprechen, die war heftig.",
    ],
    "pzr_schlecht": [
        "Die letzte Zahnreinigung war ehrlich gesagt nicht gut.",
        "Mit der Zahnreinigung beim letzten Mal war ich unzufrieden.",
        "Die letzte Zahnreinigung hat kaum was gebracht.",
        "Bei der letzten Zahnreinigung wurde geschludert, finde ich.",
        "Die Zahnreinigung neulich war ziemlich oberflächlich.",
        "Nach der letzten Zahnreinigung sah es aus wie vorher.",
        "Die Dame bei der letzten Zahnreinigung war sehr grob.",
        "Die letzte Zahnreinigung hat wehgetan und wenig gebracht.",
        "Ich war mit der letzten Zahnreinigung überhaupt nicht zufrieden.",
        "Die Zahnreinigung war diesmal leider enttäuschend.",
    ],
    "fussball": [
        "Haben Sie gestern das Spiel gesehen? Fortuna hat ja mal wieder verloren.",
        "Ganz anderes Thema: schauen Sie eigentlich Fußball? Das Derby war ja irre.",
        "Ich bin noch ganz fertig vom Fußball gestern, was für ein Spiel!",
        "Sagen Sie, sind Sie Fußballfan? Ich muss das Endspiel unbedingt sehen.",
        "Der Termin darf nicht mit dem Champions-League-Abend kollidieren, da schaue ich Fußball.",
        "Mein Sohn spielt samstags immer Fußball, deswegen bin ich da verhindert.",
        "Fußball gucken geht natürlich vor, deshalb bitte nicht dienstagabends.",
        "Ich komme gerade vom Fußballplatz, entschuldigen Sie die Hintergrundgeräusche.",
        "Wenn Deutschland spielt, verschiebe ich sogar Zahnarzttermine, haha.",
        "Beim letzten Termin lief im Wartezimmer Fußball, das fand ich super.",
    ],
    "trump": [
        "Was sagen Sie eigentlich zu Trump? Das ist doch alles verrückt geworden.",
        "Haben Sie die Nachrichten gesehen? Dieser Trump schon wieder...",
        "Ganz ehrlich, dieser Trump macht mich wahnsinnig, überall nur noch Politik.",
        "Mit den Zöllen von Trump wird doch alles teurer, auch beim Zahnarzt bestimmt.",
        "Ich rege mich gerade über die Politik auf, dieser Trump, sage ich Ihnen.",
        "Trump hin oder her, Hauptsache die Zähne halten, oder?",
        "Finden Sie Trump eigentlich auch so schlimm wie ich?",
        "Die Weltlage mit Trump macht mir Sorgen, da vergisst man glatt die Zähne.",
        "Erst Trump in den Nachrichten und jetzt auch noch Zahnarzt — was ein Tag.",
        "Sagen Sie mal ehrlich: Trump — Wahnsinn, oder?",
    ],
    "iran": [
        "Bei den Nachrichten über den Iran kriegt man ja Angst, finden Sie nicht?",
        "Dieser Krieg im Iran beschäftigt mich sehr, furchtbar das alles.",
        "Haben Sie das vom Iran gehört? Schreckliche Zeiten.",
        "Der Krieg da unten im Iran, das macht einem schon zu schaffen.",
        "Ich schaue kaum noch Nachrichten, dieser Iran-Konflikt ist so bedrückend.",
        "Erst der Krieg im Iran und dann noch der Zahnarzt, das Leben ist schon hart.",
        "Meine Nachbarin kommt aus dem Iran, die ist ganz verzweifelt wegen des Kriegs.",
        "Was sagen Sie zum Iran? Ich finde das alles sehr beunruhigend.",
        "Bei dem Kriegsgerede um den Iran vergisst man fast die normalen Sorgen.",
        "Die Lage im Iran ist schlimm, da kommt man ins Grübeln.",
    ],
    "kosten_hoch": [
        "Ich finde ja generell, Zahnarztkosten sind viel zu hoch geworden.",
        "Zahnärzte sind einfach zu teuer, das muss ich mal loswerden.",
        "Bei den Preisen beim Zahnarzt kann man sich das ja kaum noch leisten.",
        "Alles wird teurer, und beim Zahnarzt langt man besonders hin.",
        "Die Zahnarztkosten explodieren, finden Sie nicht?",
        "Ehrlich, die Kosten beim Zahnarzt sind der Wahnsinn geworden.",
        "Warum ist Zahnersatz eigentlich so unbezahlbar teuer?",
        "Ich schiebe den Besuch vor mir her, weil das immer so teuer wird.",
        "Zahngesundheit ist Luxus geworden, sage ich Ihnen.",
        "Die Preise beim Zahnarzt sind doch nicht mehr normal.",
    ],
    "hartz4": [
        "Ich muss dazu sagen, ich bin Hartz-vier-Empfänger — geht das trotzdem?",
        "Ich bekomme Bürgergeld, ich hoffe, die Behandlung geht trotzdem.",
        "Ich bin Hartz vier, viel Geld habe ich nicht.",
        "Als Bürgergeld-Empfänger muss ich aufs Geld gucken, sage ich gleich dazu.",
        "Ich lebe von Hartz vier, was Teures kann ich mir nicht leisten.",
        "Geld ist bei mir knapp, ich bin im Bürgergeld-Bezug.",
        "Ich sage es offen: ich bin Hartz-vier-Empfänger und kann keine großen Sprünge machen.",
        "Bei mir ist das Budget eng, ich bekomme Bürgergeld.",
        "Ich bin arbeitslos und beziehe Bürgergeld, nur dass Sie Bescheid wissen.",
        "Viel geht bei mir nicht, ich lebe vom Amt.",
    ],
    "ratenzahlung": [
        "Kann ich bei Ihnen eigentlich in Raten zahlen?",
        "Geht das auch mit Ratenzahlung?",
        "Bieten Sie Ratenzahlung an?",
        "Könnte ich die Behandlung in Raten abbezahlen?",
        "Gibt es bei Ihnen eine Finanzierung oder Ratenzahlung?",
        "Ich könnte das nicht auf einmal zahlen — geht das in Raten?",
        "Wie sieht es mit Ratenzahlung aus bei größeren Sachen?",
        "Kann man die Rechnung bei Ihnen in Raten begleichen?",
        "Wäre eine Ratenzahlung möglich, falls es teuer wird?",
        "Ich müsste das in Raten zahlen, ginge das?",
    ],
    "taxi": [
        "Ich bräuchte ein Taxi, um zu Ihnen zu kommen — stellen Sie Taxischeine aus?",
        "Können Sie mir einen Taxischein ausstellen? Anders komme ich nicht zu Ihnen.",
        "Ich kann nicht mehr gut laufen, gibt es von Ihnen einen Taxigutschein?",
        "Übernimmt die Praxis das Taxi zu Ihnen?",
        "Ich müsste mit dem Taxi kommen, zahlt das die Praxis?",
        "Gibt es bei Ihnen Taxischeine für die Anfahrt?",
        "Ohne Taxi schaffe ich den Weg nicht — können Sie da was machen?",
        "Stellen Ihre Ärzte Taxischeine aus?",
        "Wie komme ich denn zu Ihnen, gibt es einen Fahrdienst oder Taxischein?",
        "Ich bräuchte für den Termin ein Taxi, geht das über die Praxis?",
    ],
    "wartezeit": [
        "Beim letzten Mal habe ich über eine Stunde im Wartezimmer gesessen.",
        "Ich hoffe, die Wartezeit ist diesmal kürzer als letztes Mal.",
        "Letztes Mal musste ich ewig warten, das war schon ärgerlich.",
        "Muss ich wieder so lange warten wie beim letzten Termin?",
        "Eine Stunde Wartezimmer wie neulich — das geht gar nicht.",
        "Ich sage nur: letztes Mal saß ich sehr, sehr lange im Wartezimmer.",
    ],
    "lob": [
        "Ich muss mal sagen: Ihre Praxis ist wirklich die netteste, die ich kenne.",
        "Beim letzten Mal war das Team so freundlich, großes Lob!",
        "Ich bin sehr zufrieden bei Ihnen, deshalb komme ich gern wieder.",
        "Die Behandlung beim letzten Mal war super, vielen Dank nochmal.",
        "Man wird bei Ihnen immer so nett behandelt, das schätze ich sehr.",
        "Kompliment an die Praxis, bei Ihnen fühlt man sich gut aufgehoben.",
    ],
}

# --------------------------------------------------- Verwalten (Absage/Umbuchung)

WANN_HINWEIS_MUSTER = [
    "Der Termin ist nächste Woche {tag}.",
    "Das müsste nächste Woche {tag} sein.",
    "Ich glaube, der ist am {tag} nächster Woche.",
    "Nächste Woche {tag}, soweit ich weiß.",
    "Am {tag} kommender Woche.",
    "Der ist nächsten {tag}.",
]

WANN_WEISS_NICHT = [
    "Das weiß ich ehrlich gesagt nicht mehr.",
    "Keine Ahnung, ich habe den Zettel verlegt.",
    "Puh, das weiß ich nicht mehr genau.",
    "Ich weiß es nicht mehr, deswegen rufe ich ja an.",
    "Das habe ich leider vergessen.",
    "Weiß ich nicht mehr — irgendwann demnächst.",
]

# ------------------------------------------------------------------- Störungen

ZWISCHENFRAGE_PREIS = [
    "Was kostet eigentlich eine Zahnreinigung bei Ihnen?",
    "Darf ich kurz fragen, was die Zahnreinigung kostet?",
    "Was würde denn eine professionelle Zahnreinigung kosten?",
    "Kurze Zwischenfrage: was kostet bei Ihnen die PZR?",
    "Wie teuer ist bei Ihnen eine Zahnreinigung?",
    "Was nehmen Sie für eine Zahnreinigung?",
]

HALBSATZ_FRAGMENTE = [
    "Hallo, ich habe nächste Woche Dienstag ein",
    "Ich hätte gerne einen",
    "Also, ich wollte eigentlich nur",
    "Mein Name ist übrigens",
    "Ich rufe an wegen der",
]

# Halbsatz-PAARE fuer den Story-Runner: Teil 1 klingt unfertig (Denkpause),
# Teil 2 kommt nach Biancas "warte" — serverseitig gefuegt ergeben beide
# einen normalen Eroeffnungssatz (W-HALBSATZ-Probe im echten Anruf).
HALBSATZ_PAARE = [
    ("Guten Tag, ich hätte gerne einen", "Termin bei Ihnen, am besten bald."),
    ("Hallo, ich rufe an wegen einem", "Termin, den ich gern ausmachen würde."),
    ("Guten Tag, ich wollte fragen, ob", "ich bei Ihnen einen Termin bekommen kann."),
    ("Hallo, ich bräuchte mal wieder einen", "Termin in Ihrer Praxis."),
    ("Guten Tag, es geht um einen", "Termin, den ich vereinbaren möchte."),
]

# ---------------------------------------------------------------- Neue Anliegen

ANLIEGEN_REZEPT = [
    "Ich bräuchte bitte ein Rezept.",
    "Können Sie mir ein Rezept ausstellen? Mein Schmerzmittel ist alle.",
    "Ich brauche ein neues Rezept für mein Medikament.",
    "Es geht um ein Rezept, das mir der Doktor versprochen hat.",
    "Ich wollte ein Rezept abholen lassen — geht das?",
    "Mir fehlt noch das Rezept vom letzten Termin.",
    "Ich bräuchte ein Rezept für die Mundspülung.",
    "Können Sie mir ein Rezept fertig machen? Ich hole es dann ab.",
    "Ich rufe wegen eines Rezepts an.",
    "Der Doktor wollte mir noch ein Rezept ausstellen, ich brauche es jetzt.",
]

ANLIEGEN_UEBERWEISUNG = [
    "Ich bräuchte eine Überweisung zum Kieferchirurgen.",
    "Können Sie mir eine Überweisung ausstellen?",
    "Ich brauche eine Überweisung für den Radiologen.",
    "Es geht um eine Überweisung, die mir noch fehlt.",
    "Der Doktor wollte mich überweisen — ich bräuchte das Papier dazu.",
    "Ich hole eine Überweisung ab, wann geht das?",
    "Mir fehlt die Überweisung für die Klinik.",
    "Ich brauche bitte noch eine Überweisung zum Spezialisten.",
    "Können Sie mir die Überweisung fertig machen?",
    "Ich rufe an, weil ich eine Überweisung benötige.",
]

ANLIEGEN_RECHNUNGSKOPIE = [
    "Ich bräuchte eine Kopie meiner letzten Rechnung.",
    "Können Sie mir die Rechnung noch mal zuschicken?",
    "Ich habe meine Rechnung verloren, ich brauche eine Rechnungskopie.",
    "Für die Versicherung brauche ich eine Kopie der Rechnung.",
    "Können Sie mir die letzte Rechnung als Kopie ausstellen?",
    "Ich benötige ein Duplikat meiner Rechnung.",
    "Die Krankenkasse will die Rechnung sehen — ich bräuchte eine Kopie.",
    "Können Sie mir die Rechnung vom letzten Termin noch einmal ausdrucken?",
    "Ich brauche bitte eine Rechnungskopie für meine Unterlagen.",
    "Es geht um eine Kopie meiner Rechnung von neulich.",
]

ANLIEGEN_UNTERLAGEN = [
    "Ich bräuchte meine Unterlagen, ich wechsle den Zahnarzt.",
    "Können Sie mir meine Patientenunterlagen zusammenstellen?",
    "Ich hätte gern eine Kopie meiner Patientenakte.",
    "Ich brauche meine Röntgenbilder für einen anderen Arzt.",
    "Können Sie mir meine Behandlungsunterlagen mitgeben?",
    "Ich möchte meine Unterlagen abholen — was muss ich dafür tun?",
    "Mein neuer Zahnarzt braucht meine Akte von Ihnen.",
    "Ich benötige meine Röntgenaufnahmen und den Befund.",
    "Können Sie mir meine Akte kopieren? Ich ziehe um.",
    "Es geht um meine Patientenunterlagen, die hätte ich gern.",
]

# ------------------------------------------------------------------ Nachschlag

RUECKBLICK_GUT = [
    "Alles gut gewesen, danke der Nachfrage.",
    "Doch, das war angenehm diesmal.",
    "War alles in Ordnung.",
    "Gut gelaufen, keine Beschwerden.",
    "Sehr zufrieden, danke.",
    "Alles bestens verheilt.",
]

FUER_WEN = [
    "Der Termin ist für meinen Sohn.",
    "Es geht um meine Tochter.",
    "Ich rufe für meine Mutter an.",
    "Der Termin wäre für meinen Mann.",
]

# ------------------------------------------------ Kurzantworten fuer den Runner

VORNAME_NUR = [
    "{vorname}.",
    "Der Vorname ist {vorname}.",
    "{vorname}, wie gesagt.",
]

NACHNAME_NUR = [
    "{nachname}.",
    "Der Nachname ist {nachname}.",
    "{nachname} hinten.",
]

# "Soll ich den Termin wirklich absagen/verschieben?" (absage_ok/verschieb_ok)
VERWALTEN_JA = [
    "Ja, bitte absagen.",
    "Ja, genau den meine ich.",
    "Ja, bitte.",
    "Ja, den bitte.",
    "Ja, richtig.",
    "Ja, machen Sie das bitte.",
]

# Auswahl aus einer vorgelesenen Terminliste (terminwahl/slot-Listen).
TERMINWAHL_ERSTER = [
    "Den ersten, bitte.",
    "Der erste passt.",
    "Nehmen wir den ersten.",
    "Der zuerst genannte, bitte.",
]

# "Möchten Sie direkt einen neuen Termin vereinbaren?" nach einer Absage.
NEUBUCHUNG_NEIN = [
    "Nein danke, erst mal nicht.",
    "Nein, das war's dann schon.",
    "Nein, ich melde mich dann wieder.",
    "Nein danke, im Moment nicht.",
]

# "Kann ich sonst noch etwas für Sie tun?" — Abschluss ohne neues Anliegen.
NICHTS_MEHR = [
    "Nein danke, das war alles.",
    "Nein, das war's. Vielen Dank!",
    "Nein, danke — Sie haben mir sehr geholfen.",
    "Das war schon alles, danke.",
    "Nein, alles erledigt. Danke!",
    "Nein danke, mehr brauche ich nicht.",
]

# telefon_alt (Akte traegt andere Nummer): neue Nummer soll gelten.
TELEFON_ALT_NEU = [
    "Bitte tragen Sie die neue Nummer ein.",
    "Die alte können Sie löschen, die neue gilt.",
    "Nehmen Sie bitte die neue Nummer.",
    "Die neue bitte — die alte stimmt nicht mehr.",
]

# ================================================================== Werkzeuge

BUCHSTABIER_ALPHABET = {
    "a": "Anton", "ä": "Ärger", "b": "Berta", "c": "Cäsar", "d": "Dora",
    "e": "Emil", "f": "Friedrich", "g": "Gustav", "h": "Heinrich", "i": "Ida",
    "j": "Julius", "k": "Kaufmann", "l": "Ludwig", "m": "Martha", "n": "Nordpol",
    "o": "Otto", "ö": "Ökonom", "p": "Paula", "q": "Quelle", "r": "Richard",
    "s": "Samuel", "t": "Theodor", "u": "Ulrich", "ü": "Übermut", "v": "Viktor",
    "w": "Wilhelm", "x": "Xanthippe", "y": "Ypsilon", "z": "Zacharias",
    "ß": "Eszett",
}


def buchstabier_satz(nachname: str, stil: int = 0) -> str:
    """'Berger' -> 'B wie Berta, E wie Emil, ...' in drei Sprechformen."""
    teile = []
    for c in nachname.lower():
        if c in BUCHSTABIER_ALPHABET:
            teile.append(f"{c.upper()} wie {BUCHSTABIER_ALPHABET[c]}")
    kette = ", ".join(teile)
    einzeln = "-".join(c.upper() for c in nachname if c.isalpha())
    formen = [
        f"Ich buchstabiere: {kette}.",
        f"Gerne: {kette}.",
        f"{nachname}, also {einzeln}.",
    ]
    return formen[stil % len(formen)]


def arzt_satz(arzt: str, nr: int = 0) -> str:
    return ARZT_MUSTER[nr % len(ARZT_MUSTER)].format(arzt=arzt)


def wunsch_satz(tag: str, nr: int = 0) -> str:
    return WUNSCH_MUSTER[nr % len(WUNSCH_MUSTER)].format(tag=tag)


def wann_hinweis_satz(tag: str, nr: int = 0) -> str:
    return WANN_HINWEIS_MUSTER[nr % len(WANN_HINWEIS_MUSTER)].format(tag=tag)


def name_satz(vorname: str, nachname: str, nr: int = 0) -> str:
    return NAME_MUSTER[nr % len(NAME_MUSTER)].format(vorname=vorname, nachname=nachname)


def versicherung_satz(privat: bool, nr: int = 0) -> str:
    if privat:
        m = VERSICHERUNG_PRIVAT_MUSTER[nr % len(VERSICHERUNG_PRIVAT_MUSTER)]
        return m.format(kasse=KASSEN_PRIVAT[nr % len(KASSEN_PRIVAT)])
    m = VERSICHERUNG_GESETZLICH_MUSTER[nr % len(VERSICHERUNG_GESETZLICH_MUSTER)]
    return m.format(kasse=KASSEN_GESETZLICH[nr % len(KASSEN_GESETZLICH)])


# Die Besuchsgruende, aus denen die Automatik zieht (id -> Varianten + was
# der Test hinterher als gebuchtes Motiv erwartet; None = kein fester Anspruch).
GRUENDE = {
    "zahnschmerzen": (GRUND_ZAHNSCHMERZEN, "akute Beschwerden"),
    "implantat": (GRUND_IMPLANTAT, "IMP Besprechung"),
    "invisalign": (GRUND_INVISALIGN, "KFO Besprechung"),
    "schiefe_zaehne": (GRUND_SCHIEFE_ZAEHNE, "KFO Besprechung"),
    "schlafschiene": (GRUND_SCHLAFSCHIENE, "SLM Besprechung"),
    "ueberweisung_grueger": (GRUND_UEBERWEISUNG_GRUEGER, "SLM Besprechung"),
    "ueberweisung_lange": (GRUND_UEBERWEISUNG_LANGE, "SLM Besprechung"),
    "ueberweisung_schlaflabor": (GRUND_UEBERWEISUNG_SCHLAFLABOR, "SLM Besprechung"),
    "pzr": (GRUND_PZR, "Zahnreinigung"),
    "kontrolle": (GRUND_KONTROLLE, "Kontroll"),
}

ANLIEGEN = {
    "rezept": ANLIEGEN_REZEPT,
    "ueberweisung_schein": ANLIEGEN_UEBERWEISUNG,
    "rechnungskopie": ANLIEGEN_RECHNUNGSKOPIE,
    "unterlagen": ANLIEGEN_UNTERLAGEN,
}

# Stimmen (muessen als Referenzen im TTS-Container liegen — tts_serve/stimmen/)
STIMMEN_M = ["thomas", "markus", "stefan", "juergen", "andreas"]
STIMMEN_W = ["sabine", "petra", "julia"]

# Namens-Pool fuer die Stories: Vorname passt zum Stimmklon (Chef: menschliche
# Namen), Nachnamen sind natuerlich, aber selten — so lassen sich Test-Akten
# im Kalender wiederfinden.
VORNAMEN = {
    "thomas": "Thomas", "markus": "Markus", "stefan": "Stefan",
    "juergen": "Jürgen", "andreas": "Andreas",
    "sabine": "Sabine", "petra": "Petra", "julia": "Julia",
}
NACHNAMEN = [
    "Brandtner", "Feldkamp", "Grunewald", "Hasselbach", "Kernbach",
    "Lindhorst", "Morgenroth", "Quandt", "Rosenbusch", "Steinfurt",
]

TESTNUMMER = "01776004600"
