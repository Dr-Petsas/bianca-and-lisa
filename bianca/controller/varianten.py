"""Zehn sprechbare Varianten je Fall — deterministisch nach Zugnummer.

Der Reducer liefert nur die Absicht. Hier entstehen die Saetze. Platzhalter
kommen ausschliesslich aus belegten Fakten (``{anrede}``, ``{name}``,
``{arzt}``, ``{grund}``, ``{thema}``). Fehlt ein Fakt, faellt die Variante
auf eine Form ohne ihn zurueck.
"""

from __future__ import annotations

from typing import Mapping

_F: dict[str, tuple[str, ...]] = {
    "anmeldung": (
        "Ich bin die KI-Telefonassistentin der Praxis und entlaste die Anmeldung. "
        "Eine direkte menschliche Telefonannahme ist leider nicht möglich, weil "
        "die Praxis durch Telefonate stark belastet ist und sonst die medizinische "
        "Versorgung der Patienten darunter leidet. Bitte haben Sie Verständnis, "
        "auch wenn eine KI-Assistenz am Telefon neu und manchmal schwierig ist. "
        "Ich verbessere mich mit jedem Anruf und jedem gemeldeten Problem. "
        "Worum geht es? Ich helfe Ihnen gern direkt.",
        "Hier spricht die digitale Telefonassistentin — ich entlaste bewusst die "
        "Anmeldung, damit das Team in der Praxis bei den Patienten bleiben kann. "
        "Persönlich durchstellen kann ich deshalb nicht; die Leitungen wären sonst "
        "dauernd besetzt. Ich weiß, das ist ungewohnt. Sagen Sie mir einfach Ihr "
        "Anliegen, ich übernehme es direkt.",
        "Ich bin die telefonische Assistentin der Praxis und fange die Anrufe ab, "
        "damit die Anmeldung nicht unter der Last zusammenbricht. Einen Menschen "
        "kann ich Ihnen gerade nicht verbinden — genau deshalb bin ich hier. "
        "Was darf ich für Sie tun?",
        "Die Praxis hat mich als digitale Assistentin ans Telefon gesetzt, damit "
        "das Praxisteam bei der Versorgung bleibt. Eine direkte Verbindung zur "
        "Anmeldung ist nicht eingerichtet. Ich kläre Termine, Absagen und Fragen "
        "sofort. Worum geht es?",
        "Ich entlaste die Anmeldung: Jeder Anruf, den ich selbst lösen kann, "
        "hält den Empfang frei für die Patienten vor Ort. Deshalb stelle ich "
        "nicht zu einer Mitarbeiterin durch. Bitte haben Sie ein wenig Geduld "
        "mit der neuen Technik — ich lerne mit jedem Gespräch. Wie kann ich helfen?",
        "Am Apparat ist die KI-Assistentin der Praxis. Die menschliche Annahme "
        "ist absichtlich nicht geschaltet, weil zu viele Telefonate die Behandlung "
        "stören. Ich übernehme Ihr Anliegen hier. Worum geht es?",
        "Sie erreichen die digitale Telefonassistenz. Die Anmeldung wird entlastet, "
        "damit Ärztin und Team ungestört arbeiten können. Ich verbinde Sie deshalb "
        "nicht mit einer Mitarbeiterin, löse aber Termine und Rückrufe direkt. "
        "Was liegt an?",
        "Ich bin die Assistentin am Telefon und genau dafür da, die Anmeldung zu "
        "schonen. Eine persönliche Durchstellung gibt es nicht — das belastet sonst "
        "die Versorgung. Sagen Sie mir Ihr Anliegen, ich kümmere mich.",
        "Hier ist die KI am Praxis-Telefon. Wir haben die menschliche Annahme "
        "bewusst weggelassen, weil die Leitungen die Sprechstunde sonst auffressen. "
        "Ich höre zu und erledige, was telefonisch geht. Worum geht es?",
        "Die Praxis lässt mich die Anrufe halten, damit niemand am Empfang zwischen "
        "Telefon und Patient zerrieben wird. Durchstellen zu einer Mitarbeiterin "
        "kann ich nicht. Dafür kläre ich Ihr Anliegen sofort. Wie kann ich helfen?",
    ),
    "anrufer_check": (
        "{anrede} {name} — habe ich Sie richtig erkannt?",
        "Wenn ich richtig liege, spreche ich mit {anrede} {name}. Stimmt das?",
        "In der Leitung sehe ich {anrede} {name}. Habe ich die richtige Person?",
        "{anrede} {name}, darf ich kurz gegenprüfen: Sie sind es, ja?",
        "Ich habe hier {anrede} {name} hinterlegt. Ist das zutreffend?",
        "Kurze Kontrolle: Sie sind {anrede} {name}, richtig?",
        "Bevor ich weitergehe — habe ich {anrede} {name} richtig erkannt?",
        "Die Nummer gehört zu {anrede} {name}. Passt das?",
        "Ein kurzes Ja oder Nein genügt: Spreche ich mit {anrede} {name}?",
        "Zur Sicherheit: {anrede} {name}, ja?",
    ),
    "anrufer_check_kurz": (
        "Habe ich Sie richtig erkannt? Ein kurzes Ja oder Nein genügt.",
        "Liege ich mit der Person richtig — ja oder nein?",
        "Kurze Kontrolle: Habe ich die richtige Person am Apparat?",
        "Sind Sie die Person, die ich hier hinterlegt habe?",
        "Darf ich kurz gegenprüfen, ob ich Sie richtig erkannt habe?",
        "Stimmt die Zuordnung, die ich hier sehe?",
        "Habe ich Sie getroffen — ja oder nein?",
        "Bin ich bei der richtigen Person?",
        "Passt die Erkennung so, oder liege ich falsch?",
        "Kurzes Ja oder Nein: Habe ich Sie erkannt?",
    ),
    "auskunft_klar": (
        "Meinen Sie einen bereits vereinbarten Termin — oder möchten Sie einen neuen vereinbaren?",
        "Geht es um einen bestehenden Termin, oder soll ich einen neuen suchen?",
        "Nur damit ich nichts falsch anfange: Auskunft zum vorhandenen Termin, oder einen neuen legen?",
        "Soll ich in Ihren bestehenden Termin schauen, oder einen neuen eintragen?",
        "Zwei Möglichkeiten: den schon gebuchten Termin vorlesen — oder einen neuen finden. Was davon?",
        "Ist das eine Nachfrage zu einem Termin, den Sie schon haben, oder ein neuer Wunsch?",
        "Bestehenden Termin nachschauen, oder neu vereinbaren?",
        "Damit ich nicht in die falsche Richtung loslaufe: schon vereinbart, oder neu?",
        "Wünschen Sie die Daten Ihres aktuellen Termins — oder einen neuen Slot?",
        "Klarheit kurz: vorhandenen Termin ansagen, oder einen neuen buchen?",
    ),
    "bezug": (
        "Ich sehe, Sie waren vor {wann} wegen {grund} bei {arzt}. Ich buche Ihnen wieder bei {arzt}. ",
        "Sie waren vor {wann} bei {arzt} wegen {grund} — ich lege den Termin wieder bei {arzt}. ",
        "Beim letzten Besuch vor {wann} waren Sie bei {arzt} ({grund}). Ich buche wieder bei {arzt}. ",
        "In der Kartei: vor {wann} {grund} bei {arzt}. Ich nehme wieder {arzt}. ",
        "Ihr letzter Termin vor {wann} war bei {arzt} wegen {grund}. Wieder bei {arzt}. ",
        "Zuletzt vor {wann} hat Sie {arzt} gesehen ({grund}). Ich buche dort wieder. ",
        "Aus der Akte: vor {wann} bei {arzt}, Anlass {grund}. Ich bleibe bei {arzt}. ",
        "Sie waren das letzte Mal vor {wann} bei {arzt}, damals {grund}. Wieder {arzt}. ",
        "Ich sehe den letzten Besuch vor {wann} bei {arzt} wegen {grund}. Wieder bei {arzt}. ",
        "Letzter Eintrag vor {wann}: {arzt}, {grund}. Ich buche Ihnen wieder bei {arzt}. ",
    ),
    "angebot_persoenlich": (
        "{anrede} {name}, ich habe {slot} frei — passt das?",
        "{anrede} {name}, frei wäre {slot}. Passt Ihnen das?",
        "{anrede} {name}, ich könnte {slot} anbieten. Geht das?",
        "{anrede} {name}, {slot} wäre frei. Soll ich den nehmen?",
        "{anrede} {name}, als Nächstes frei: {slot}. Passt das?",
        "{anrede} {name}, ich sehe {slot}. Möchten Sie den?",
        "{anrede} {name}, verfügbar ist {slot}. Passt Ihnen das?",
        "{anrede} {name}, ich hätte {slot}. Ist das recht?",
        "{anrede} {name}, offen ist {slot}. Nehmen wir den?",
        "{anrede} {name}, {slot} habe ich frei. Geht das?",
    ),
    "arzt_notiz": (
        "Soll die Ärztin darüber hinaus noch eine Nachricht zum Termin erhalten?",
        "Darf ich der Ärztin eine kurze Notiz zum Termin hinterlegen?",
        "Möchten Sie der Ärztin noch etwas für den Termin mitgeben?",
        "Soll ich eine Nachricht für die Ärztin zum Termin notieren?",
        "Will die Ärztin eine Notiz zum Termin bekommen — ja oder nein?",
        "Soll ich der Ärztin etwas zum Termin hinterlegen?",
        "Eine Nachricht an die Ärztin zum Termin — möchten Sie das?",
        "Darf ich noch eine Notiz für die Ärztin aufnehmen?",
        "Soll die Ärztin eine kurze Nachricht zum Termin sehen?",
        "Möchten Sie der Ärztin noch etwas mitteilen?",
    ),
    "termin_hinweis": (
        "Welchen Termin meinen Sie denn — Datum oder Uhrzeit?",
        "Können Sie mir den Termin genauer nennen?",
        "An welchem Tag war der Termin, den Sie meinen?",
        "Welches Datum oder welche Uhrzeit soll ich suchen?",
        "Nennen Sie mir bitte den Tag oder die Uhrzeit.",
        "Welchen der Termine soll ich nehmen?",
        "Gibt es ein Datum, an dem ich suchen soll?",
        "Wann ungefähr war der Termin?",
        "Welchen Tag oder welche Uhrzeit darf ich suchen?",
        "Sagen Sie mir den Termin, den Sie meinen.",
    ),
    "bezug_suche": (
        "Ich schaue direkt, wann etwas frei ist. ",
        "Dann suche ich gleich einen passenden Slot. ",
        "Ich prüfe sofort die nächsten freien Zeiten. ",
        "Einen Moment, ich schaue in den Kalender. ",
        "Ich sehe nach, was zeitnah frei ist. ",
        "Dann lege ich gleich die freien Termine daneben. ",
        "Ich hole die nächsten freien Fenster. ",
        "Sofort schaue ich, wo etwas offen ist. ",
        "Ich vergleiche das mit den freien Zeiten. ",
        "Dann gehe ich direkt in die Slotsuche. ",
    ),
    "schonmal": (
        "Waren Sie denn schon einmal bei uns in der Praxis?",
        "Waren Sie schon Patientin oder Patient bei uns?",
        "Waren Sie schon einmal hier?",
        "Kennen wir uns schon aus einem früheren Besuch?",
        "Waren Sie schon mal in Behandlung bei uns?",
        "Sind Sie schon einmal da gewesen?",
        "Waren Sie schon als Patientin oder Patient bei uns vorstellig?",
        "Haben wir Sie schon einmal gesehen?",
        "Waren Sie schon früher bei uns?",
        "Ist das Ihr erster Besuch — oder waren Sie schon einmal da?",
    ),
    "behandler": (
        "Zu welchem Behandler möchten Sie denn?",
        "Haben Sie einen Wunsch-Behandler?",
        "Bei welchem Behandler darf ich den Termin legen?",
        "Welcher Behandler soll es sein?",
        "Haben Sie einen bestimmten Behandler im Kopf?",
        "Zu welchem Behandler soll der Termin?",
        "Welchen Behandler darf ich eintragen?",
        "Gibt es einen Wunsch-Behandler?",
        "Soll ich einen bestimmten Behandler nehmen?",
        "Bei welchem Behandler soll ich suchen?",
    ),
    "besuchsgrund": (
        "Worum geht es bei dem Termin?",
        "Was ist der Anlass?",
        "Welches Anliegen soll ich eintragen?",
        "Worum soll sich der Termin drehen?",
        "Was darf die Ärztin oder der Arzt vorbereiten?",
        "Welcher Besuchsgrund passt?",
        "Was liegt an — Kontrolle, Beschwerden, etwas anderes?",
        "Wofür brauchen Sie den Termin?",
        "Was soll ich als Grund vermerken?",
        "Worum geht es inhaltlich?",
    ),
    "wunschzeit": (
        "Wann würde es Ihnen denn passen?",
        "Haben Sie einen Wunschtag oder eine Tageszeit?",
        "Wann käme es Ihnen recht?",
        "Gibt es Tage, die Ihnen besonders gut passen?",
        "Vormittags, nachmittags — oder ein bestimmter Tag?",
        "Wann soll ich suchen?",
        "Welche Zeitlage wäre Ihnen lieb?",
        "Haben Sie schon ein Zeitfenster im Kopf?",
        "Wann wäre es Ihnen am liebsten?",
        "Nennen Sie mir gern Tag oder Tageszeit.",
    ),
    "nachname": (
        "Wie ist Ihr Nachname?",
        "Wie heißen Sie mit Nachnamen?",
        "Darf ich den Nachnamen haben?",
        "Unter welchem Nachnamen soll ich suchen?",
        "Wie lautet der Nachname?",
        "Wie darf ich Sie im Kalender finden — der Nachname?",
        "Welchen Nachnamen trage ich ein?",
        "Bitte der Nachname.",
        "Wie schreiben wir den Nachnamen?",
        "Nachname bitte — am besten deutlich.",
    ),
    "vorname": (
        "Und wie ist Ihr Vorname?",
        "Wie heißen Sie mit Vornamen?",
        "Darf ich noch den Vornamen?",
        "Und der Vorname?",
        "Welchen Vornamen soll ich dazu nehmen?",
        "Vorname bitte.",
        "Wie ist der Vorname?",
        "Und vorne?",
        "Den Vornamen hätte ich noch gern.",
        "Wie darf ich den Vornamen eintragen?",
    ),
    "versicherung": (
        "Sind Sie gesetzlich oder privat versichert?",
        "Gesetzlich oder privat — was trifft zu?",
        "Wie sind Sie versichert, gesetzlich oder privat?",
        "Kasse oder privat?",
        "Tragen Sie eine gesetzliche oder eine private Versicherung?",
        "Privat oder gesetzlich versichert?",
        "Welche Versicherung — gesetzlich oder privat?",
        "Zum Schluss die Versicherung: gesetzlich oder privat?",
        "Sind Sie bei einer Kasse oder privat versichert?",
        "Gesetzlich, oder privat?",
    ),
    "telefon": (
        "Unter welcher Handynummer erreichen wir Sie?",
        "Welche Mobilnummer darf ich für die SMS nehmen?",
        "Ihre Handynummer bitte.",
        "Wohin soll die Bestätigung — die Mobilnummer?",
        "Auf welche Nummer darf ich die SMS schicken?",
        "Handynummer, unter der wir Sie erreichen?",
        "Welche Nummer soll ins Handyfeld?",
        "Mobilnummer für die Bestätigung?",
        "Wohin darf die SMS?",
        "Ihre Erreichbarkeit per Handy bitte.",
    ),
    "rueckruf_ja": (
        "Rezepte und Überweisungen kann ich telefonisch leider nicht ausstellen — "
        "das geht nur persönlich in der Praxis. Soll ich Ihnen dafür einen Rückruf einrichten?",
        "Ein Rezept oder eine Überweisung bestelle ich am Telefon nicht. "
        "Das klären wir nur vor Ort. Darf ich einen Rückruf notieren?",
        "Dokumente wie Rezept oder Überweisung gehen nicht über mich. "
        "Persönlich in der Praxis — oder soll die Praxis Sie zurückrufen?",
        "Am Telefon stelle ich keine Rezepte aus. Kommen Sie vorbei, "
        "oder notiere ich einen Rückruf?",
        "Das schafft nur die Praxis persönlich, nicht das Telefon. "
        "Soll ich einen Rückruf aufnehmen?",
        "Rezept und Überweisung: nur vor Ort. Möchten Sie, dass jemand zurückruft?",
        "Telefonisch darf ich das nicht zusagen. Rückruf einrichten — ja oder nein?",
        "Solche Unterlagen gibt es nicht am Hörer. Rückruf vom Team, oder kommen Sie vorbei?",
        "Ich darf das nicht am Telefon erledigen. Soll die Praxis Sie anrufen?",
        "Das gehört in die Sprechstunde. Darf ich einen Rückrufwunsch aufschreiben?",
    ),
    "unterlagen": (
        "Befunde, Röntgenbilder und die Akte schicke ich nicht per E-Mail — "
        "Einsicht gibt es nur persönlich in der Praxis. Soll ich einen Rückruf notieren?",
        "Einsicht in die Behandlungsunterlagen gebe ich am Telefon nicht — "
        "das geht nur persönlich in der Praxis. Soll ich einen Rückruf notieren?",
        "Die Akte lese ich nicht vor und schicke sie auch nicht per Telefon zu. "
        "Das klären Sie vor Ort. Darf ich einen Rückruf aufnehmen?",
        "Behandlungsunterlagen sind nichts für die Leitung. Kommen Sie vorbei, "
        "oder soll das Team Sie zurückrufen?",
        "Einsicht gibt es nur in der Praxis, nicht am Hörer. Rückruf einrichten?",
        "Die Unterlagen gebe ich telefonisch nicht heraus. Soll jemand zurückrufen?",
        "Akteneinsicht ist persönlich. Darf ich das als Rückrufwunsch vermerken?",
        "Am Telefon zeige ich keine Akte. Praxis vor Ort — oder Rückruf?",
        "Das ist ein persönlicher Vorgang in der Praxis. Soll ich jemanden bitten zurückzurufen?",
        "Unterlagen schicke oder lese ich hier nicht. Rückruf vom Team, ja oder nein?",
        "Einsicht nur vor Ort. Möchten Sie, dass die Praxis Sie anruft?",
    ),
    "fachfrage": (
        "Zu {thema} gebe ich am Telefon keine medizinische Auskunft. "
        "Soll ich einen Rückruf bei der Ärztin einrichten — oder möchten Sie einen Termin?",
        "Medizinische Fragen zu {thema} beantworte ich nicht selbst. "
        "Rückruf von der Ärztin, oder einen Termin zur Besprechung?",
        "Dazu gehört die Ärztin, nicht das Telefon. "
        "Darf ich einen Rückruf notieren, oder einen Termin legen?",
        "{thema} klären wir nicht am Hörer. Rückruf oder Termin — was darf ich tun?",
        "Ich berate nicht zu {thema}. Soll die Ärztin zurückrufen, oder buche ich einen Termin?",
        "Das ist eine Fachfrage, keine Terminsuche. Rückruf einrichten oder Termin vereinbaren?",
        "Am Telefon erkläre ich {thema} nicht. Möchten Sie einen Rückruf oder einen Termin?",
        "Dafür braucht es die Ärztin. Rückrufwunsch, oder soll ich einen Slot suchen?",
        "Ich halte mich bei {thema} zurück. Rückruf oder Vorstellungstermin?",
        "Inhaltlich zu {thema} sage ich nichts zu. Rückruf notieren — oder Termin?",
    ),
    "unklar": (
        "Das habe ich nicht sicher verstanden. Geht es um einen neuen Termin, "
        "einen bestehenden, eine Absage oder etwas anderes?",
        "Kurz nachfassen: neuer Termin, bestehender Termin, Absage — oder ein anderes Anliegen?",
        "Ich bin nicht sicher. Möchten Sie vereinbaren, nachschauen, verschieben oder absagen?",
        "Damit ich richtig einbiege: neuer Termin, Auskunft zum vorhandenen, oder etwas anderes?",
        "Noch einmal in Ruhe: Worum geht es genau?",
        "Ich will nichts falsch anfangen. Termin neu, Termin nachschauen, oder ein anderes Thema?",
        "Sagen Sie es mir gern noch einmal mit dem Anliegen in einem Satz.",
        "Ich habe den Kern nicht getroffen. Was darf ich für Sie tun?",
        "Bitte den Auftrag in einem Satz: neu, nachschauen, verschieben, absagen?",
        "Woran soll ich zuerst arbeiten — neuer Termin oder etwas anderes?",
    ),
    "hallo": (
        "Hallo, wie kann ich Ihnen helfen?",
        "Guten Tag — worum geht es?",
        "Ja, ich bin da. Was darf ich tun?",
        "Hallo, ich höre.",
        "Gern — wie kann ich helfen?",
        "Hier. Worum geht es?",
        "Hallo, sagen Sie mir Ihr Anliegen.",
        "Ich bin dran. Was liegt an?",
        "Guten Tag, ich höre Ihnen zu.",
        "Ja bitte — worum geht es?",
    ),
    "hilfe": (
        "Ja, gern. Sagen Sie mir einfach, worum es geht.",
        "Natürlich. Was darf ich für Sie klären?",
        "Ich bin da. Welches Anliegen haben Sie?",
        "Gern helfe ich. Worum geht es?",
        "Sagen Sie mir den Auftrag, ich ziehe mit.",
        "Ja. Termin, Absage, Auskunft — was davon?",
        "Ich übernehme. Was liegt an?",
        "Gern. In einem Satz: worum geht es?",
        "Ich höre. Was kann ich tun?",
        "Ja, legen Sie los — ich bin da.",
    ),
}


def waehle(key: str, zug_nr: int = 0, **werte: str) -> str:
    """Deterministische Variante. Unbekannter Key -> leer."""
    liste = _F.get(key) or ()
    if not liste:
        return ""
    satz = liste[int(zug_nr) % len(liste)]
    sauber = {k: v for k, v in werte.items() if v}
    try:
        return satz.format_map(_Default(sauber))
    except (KeyError, ValueError):
        return satz


class _Default(dict):
    def __missing__(self, key: str) -> str:
        return ""


def zug_von(fakten: Mapping[str, str] | None) -> int:
    if not fakten:
        return 0
    roh = str(fakten.get("zug") or "0")
    try:
        return int(roh)
    except ValueError:
        return 0


__all__ = ["waehle", "zug_von"]
