from kern import gedaechtnis as g

print("anzeige", g.anzeige())
print("enabled", g.enabled())
t, ids = g._kontext_stand("491777074403", "Patrick Herbst")
print("ids", ids)
print(t[:900])
