from bianca import flow, gehirn
from kern.patients import arzt_sprechname
from kern.tenants import laden

print("frau", arzt_sprechname("Eva Thaler"))
print("dr", arzt_sprechname("Dr. Eva Thaler"))
print("herr", gehirn.anrede({"vorname": "Leonid", "nachname": "Sarkaldeva"}))
sit = {
    "tenant": laden("meddent"),
    "messages": [{"role": "system", "content": "x"}],
    "offered": [{"iso": "2026-09-10T17:00:00+02:00", "spoken": "x"}],
    "flussFrage": "Welcher davon passt Ihnen?",
}
s = gehirn.sammler(sit)
s.update({"modus": "buchen", "phase": "gebucht", "nachname": "Sarkaldeva",
          "vorname": "Leonid", "frage": ""})
z = flow.zug(sit, "Ja, und mein Nachname hat sich geändert.")
print("korr", (z or {}).get("text", "")[:80], "frage", gehirn.sammler(sit)["frage"])
