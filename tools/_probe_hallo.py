from bianca import gehirn
from kern import sprech

sit = {"anrufer": {
    "vorname": "Michael", "nachname": "Petsas",
    "geschlecht": "male", "telefon": "+491776004600",
}}
h = gehirn.anrufer_hallo(sit)
f = gehirn.anrufer_check_frage(sit, selbst=True)
print("HALLO", h)
print("FULL", f)
print("SAETZE", sprech.tts_saetze(sprech.sanitize(f)))
