"""STT-Hotwords fuer Lisa/Bianca — Claras V7-Idee, ohne Heads-up-Marker.

Parakeet hat kein echtes Hotword-Bias: die Liste speist nur die Fuzzy-
Nachkorrektur (stt_serve/postcorrect.py). Behandler kommen aus dem Tenant;
hier liegen die Woerter, die am Patiententelefon staendig falsch ankommen.
"""

from __future__ import annotations

# Haeufige Vornamen (wie bianca/gehirn._VORNAMEN) — "Beter" -> "Peter".
VORNAMEN = (
    "Alexander", "Andreas", "Anna", "Anne", "Anja", "Barbara", "Bernd",
    "Birgit", "Christian", "Christina", "Christine", "Claudia", "Daniel",
    "Daniela", "David", "Dennis", "Dieter", "Dirk", "Elena", "Elke",
    "Eva", "Felix", "Florian", "Frank", "Gabriele", "Hanna", "Hans",
    "Heike", "Helga", "Ingrid", "Jan", "Jens", "Johanna", "Jonas",
    "Julia", "Juergen", "Kai", "Karin", "Karl", "Katharina", "Katja",
    "Kerstin", "Klaus", "Laura", "Lena", "Leon", "Lisa", "Lukas",
    "Manfred", "Maria", "Marie", "Markus", "Martin", "Martina",
    "Matthias", "Max", "Melanie", "Michael", "Michaela", "Monika",
    "Nadine", "Nicole", "Nina", "Oliver", "Patrick", "Paul", "Peter",
    "Petra", "Philipp", "Sabine", "Sandra", "Sarah", "Sebastian",
    "Simone", "Stefan", "Stefanie", "Susanne", "Thomas", "Tobias",
    "Ulrich", "Ursula", "Uwe", "Werner", "Wolfgang",
)

# Praxis-/Buchungsvokabeln — Clara-V7-Profil minus Kommando-Marker
# (Heads-up, Kons, Teleskopkrone, Recall, Aufnahme). Umlaut + ASCII,
# weil Parakeet beides liefert.
PRAXIS = (
    "Kontrolle", "Kontrolluntersuchung", "Erstuntersuchung",
    "Zahnreinigung", "Wurzelbehandlung", "Implantat",
    "Krone", "Bruecke", "Brücke", "Fuellung", "Füllung",
    "Karies", "Schmerzen", "Schmerz", "Nachmittag",
    "Vormittag", "Nachname", "Vorname", "Handynummer", "Termin",
    "Absage", "Verschieben", "Prophylaxe", "Weisheitszahn",
    "Zahnersatz", "Unterlagen",
    "Grafenberg", "Medical", "Center", "CeraWhite",
    "Reparatur",
)

# Haeufige Nachnamen dieser Praxis (Clara-V7-Profil + griechische
# Namens-Hoerfehler). Fuzzy-Nachkorrektur: "Zannis" -> "Tzannis".
NACHNAMEN = (
    "Tzannis", "Thrandorf", "Diedershagen", "Heuser", "Kasper",
    "Kaufmann", "Meier", "Ackermann", "Kyriakidou", "Vassiliou",
    "Charalambous", "Papadopoulos", "Georgiadis", "Theodorakis",
    "Ruether", "Rüther",
)
