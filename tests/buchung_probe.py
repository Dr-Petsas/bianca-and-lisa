"""Buchungs-Probe direkt gegen die Cloud Functions: WO klemmt masBookAppointment?

1. Levis kommende Termine zeigen (Streu-Buchungen früherer Proben finden).
2. getFreeTimeSlots roh abrufen (Petsas, Kontrolle, ab 2026-09-03) — exakte Strings.
3. masBookAppointment mit dem ERSTEN rohen Slot-String aufrufen und die
   Antwort UNGEKÜRZT ausgeben. Bei Erfolg wird sofort wieder abgesagt.
"""

import json
import sys

sys.path.insert(0, r"F:\Bianca&Lisa TelefonKI")

from kern import calendar as kal  # noqa: E402
from kern.calendar import _cf_post  # noqa: E402
from kern.tenants import laden  # noqa: E402

TENANT = laden("meddent")
PATIENT_ID = "ptSfmJGCLPKzx3OcfaMq"  # Levi Tzannis
CAL_PETSAS = "zex5bmv5jfIHWVW6zHbg"
MOTIV_KONTROLLE = "qOQCI4vV2EhQVmKmRqdu"


def main() -> int:
    # 1) Kommende Termine (Streu-Buchungen?)
    status, data = _cf_post("masPatientLastDoctor", {
        "clientId": TENANT["clientId"],
        "locationId": TENANT["locationId"],
        "patientId": PATIENT_ID,
    })
    print(f"masPatientLastDoctor status={status}")
    print(json.dumps(data, ensure_ascii=False, indent=1)[:1200])
    print()

    # 2) Freie Slots roh
    found = kal.find_slots(
        TENANT,
        {"calendarId": CAL_PETSAS, "visitMotiveId": MOTIV_KONTROLLE},
        start_date="2026-09-03",
        source="probe",
    )
    roh = found.get("slots") or []
    print(f"find_slots ok={found.get('ok')} n={len(roh)}")
    for x in roh[:5]:
        print(f"  slot roh: {x!r}")
    if not roh:
        return 1
    erster = roh[0] if isinstance(roh[0], str) else (roh[0].get("iso") or roh[0].get("start"))
    print()

    # 3) Buchen mit exakt diesem String
    body = {
        "clientId": TENANT["clientId"],
        "locationId": TENANT["locationId"],
        "patientId": PATIENT_ID,
        "calendarId": CAL_PETSAS,
        "visitMotiveId": MOTIV_KONTROLLE,
        "appointmentStartDate": erster,
    }
    print(f"masBookAppointment body.appointmentStartDate={erster!r}")
    status, data = _cf_post("masBookAppointment", body)
    print(f"masBookAppointment status={status}")
    print(json.dumps(data, ensure_ascii=False, indent=1)[:1500])
    print()

    aid = (data or {}).get("appointmentId") if isinstance(data, dict) else ""
    if status == 200 and isinstance(data, dict) and data.get("status") == "success":
        tag = str(erster)[:10]
        weg = kal.cancel_appointment(
            TENANT,
            {"firstName": "Levi", "lastName": "Tzannis", "appointmentDate": tag},
        )
        print(f"AUFGERÄUMT: cancelled={weg.get('cancelled')} ({weg.get('spoken')}) aid={aid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
