from bianca import gehirn
from kern.patients import arzt_sprechname
from kern.tenants import laden

t = laden("meddent")
an = {
    "vorname": "Michael", "nachname": "Petsas",
    "geschlecht": "male", "telefon": "+491776004600",
}
sit_neu = {"tenant": t, "anrufer": an, "anruferHalloGesagt": True}
sit_alt = {
    "tenant": t, "anrufer": an, "anruferHalloGesagt": True,
    "vorigesGespraech": {"ts": 1, "wann": "heute"},
}
print("erst", gehirn.anrufer_check_frage(sit_neu, selbst=True))
print("wieder", gehirn.anrufer_check_frage(sit_alt, selbst=True))
print("hallo-neu", gehirn.anrufer_hallo({"tenant": t, "anrufer": an}))
print("arzt", arzt_sprechname("Petsas", t))
print("pzr", gehirn.ist_pzr_zusage("So eintragen bitte."))
