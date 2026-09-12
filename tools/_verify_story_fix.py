from tests.baukasten import geschichten

q = ("Geht es um einen Termin, eine Auskunft oder möchten Sie "
     "mit einem Mitarbeiter sprechen?")
print("frage", geschichten._frage_aus_text(q))
story = {"anliegen": geschichten.TERMIN, "grund": "ZE Besprechung",
         "nachname": "Feldkamp", "seed": 1}
lage = geschichten.lage_neu()
lage.update({"eroeffnet": True, "biancaText": q})
zug = geschichten.naechster_baustein(story, lage)
print("zug", zug["baustein"], zug["text"][:80])
