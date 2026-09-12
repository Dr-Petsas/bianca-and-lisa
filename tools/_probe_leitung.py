from bianca import weiterleiten, flow
from kern.tenants import laden

satz = "Hallo, Petsas mein Name. Bin ich mit der Praxis Dr. Petsas verbunden?"
sit = {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}
z = flow.zug(sit, satz)
print("erkannt", weiterleiten.erkannt(satz))
print("transfer", None if not z else z.get("transfer"))
print("hangup", None if not z else z.get("hangup"))
print("text", None if not z else z.get("text"))
