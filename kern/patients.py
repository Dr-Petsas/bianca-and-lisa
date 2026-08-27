"""Patientensuche über masSearchPatients. Termine optional über MAS (nur lesen)."""

from __future__ import annotations

import re
from typing import Any

import httpx

from kern.config import CF_BASE, DEV_PHONE, MAS_URL, WRITE_LIVE
from kern.slots import spoken_slot

PARTICLES = {
    "el", "al", "ale", "ben", "bin", "ibn", "abu", "van", "von", "der", "den",
    "de", "di", "da", "do", "du", "le", "la", "los", "las", "dos", "das", "st",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def name_varianten(spoken: str, max_n: int = 4) -> list[str]:
    clean = re.sub(r"[^\w\s'-]", " ", spoken or "", flags=re.UNICODE)
    clean = " ".join(clean.split()).strip()
    if not clean:
        return []
    out: list[str] = []

    def push(v: str) -> None:
        t = _s(v)
        if len(t) < 2:
            return
        if any(x.lower() == t.lower() for x in out):
            return
        if len(out) < max_n:
            out.append(t)

    push(clean)
    teile = clean.split()
    if len(teile) >= 2:
        kern = [t for t in teile[1:] if t.lower() not in PARTICLES]
        if kern:
            push(" ".join(kern))
        push(teile[0])
    return out


def _phone_of(p: dict) -> str:
    for k in ("mobilePhoneNumber", "mobilePhone", "phoneNumber", "phone", "telephone"):
        v = _s(p.get(k))
        if v:
            return v
    return ""


def _digits(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def format_de_phone(raw: str) -> str:
    d = _digits(raw)
    if d.startswith("49") and len(d) > 10:
        d = "0" + d[2:]
    if d == "01776004600":
        return "0177 6004600"
    if len(d) >= 10:
        return f"{d[:4]} {d[4:7]} {d[7:]}"
    return raw or ""


def search_patients(tenant: dict, query: str) -> dict[str, Any]:
    variants = name_varianten(query)
    if not variants:
        return {"ok": True, "patients": []}
    seen: dict[str, dict] = {}
    last_err = ""
    for q in variants:
        try:
            r = httpx.post(
                f"{CF_BASE}/masSearchPatients",
                json={
                    "clientId": _s(tenant.get("clientId")),
                    "locationId": _s(tenant.get("locationId")),
                    "query": q,
                },
                timeout=8.0,
            )
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        except httpx.HTTPError as e:
            last_err = str(e)
            continue
        if r.status_code != 200 or data.get("status") != "success":
            last_err = data.get("message") or f"http_{r.status_code}"
            continue
        for p in data.get("patients") or []:
            if not isinstance(p, dict):
                continue
            key = _s(p.get("id")) or f"{_s(p.get('firstName'))} {_s(p.get('lastName'))}".lower()
            if key and key not in seen:
                seen[key] = p
        # Erste Variante ist der volle Name — gibt es Treffer, reicht das.
        # Weitere Varianten sind nur der phonetische Rettungsanker bei null Treffern.
        if seen:
            break
    hits = list(seen.values())
    # Echte Patienten zuerst, Seed-/Testdatensaetze ans Ende (stabile Sortierung).
    hits.sort(key=ist_testakte)
    return {"ok": True, "patients": hits[:8], "error": last_err}


def _termine_aus_patient(p: dict) -> dict[str, list]:
    past, upcoming = [], []
    for key, bucket in (("lastAppointments", past), ("pastAppointments", past),
                        ("upcomingAppointments", upcoming), ("nextAppointments", upcoming)):
        raw = p.get(key)
        if isinstance(raw, list):
            bucket.extend(raw)
    last = p.get("lastAppointment") or p.get("lastAppointmentDate")
    nxt = p.get("nextAppointment") or p.get("nextAppointmentDate")
    if last and not past:
        past.append(last)
    if nxt and not upcoming:
        upcoming.append(nxt)
    return {"past": past[:5], "upcoming": upcoming[:5]}


def _iso_aus(item: dict) -> str:
    iso = _s(item.get("iso") or item.get("start") or item.get("startDate") or item.get("appointmentStartDate"))
    if iso:
        return iso
    ms = item.get("startMs")
    try:
        n = int(ms)
    except (TypeError, ValueError):
        return ""
    if n > 10_000_000_000:
        n = n / 1000.0
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(n, ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%dT%H:%M")


def _norm_termin(item: Any) -> dict[str, str] | None:
    if item is None:
        return None
    if isinstance(item, str):
        iso = item
        label = spoken_slot(item) if "T" in item else item
        return {"id": "", "iso": iso, "date": iso[:10] if len(iso) >= 10 else "", "label": label}
    if not isinstance(item, dict):
        return None
    iso = _iso_aus(item)
    when = _s(item.get("when") or item.get("spoken") or item.get("label"))
    grund = _s(item.get("visitMotiveName") or item.get("visitMotive") or item.get("title") or item.get("reason"))
    arzt = _s(item.get("calendarName") or item.get("doctorName"))
    if not when and iso:
        when = spoken_slot(iso) if "T" in iso else iso
    if not when:
        return None
    extra = " · ".join(x for x in (grund, arzt) if x)
    return {
        "id": _s(item.get("id") or item.get("appointmentId")),
        "iso": iso,
        "date": iso[:10] if len(iso) >= 10 else "",
        "label": f"{when}{(' — ' + extra) if extra else ''}",
    }


def termine_fuer(tenant: dict, patient: dict) -> dict[str, list]:
    aus_akte = _termine_aus_patient(patient)
    past = [x for x in (_norm_termin(i) for i in aus_akte["past"]) if x]
    upcoming = [x for x in (_norm_termin(i) for i in aus_akte["upcoming"]) if x]
    name = (
        f"{_s(patient.get('firstName'))} {_s(patient.get('lastName'))}".strip()
        or _s(patient.get("name"))
    )
    if not upcoming and MAS_URL and name:
        try:
            r = httpx.post(
                f"{MAS_URL}/tools/patient-appointments",
                headers={"X-Client-Id": _s(tenant.get("clientId"))},
                json={"name": name, "clientId": _s(tenant.get("clientId"))},
                timeout=8.0,
            )
            data = r.json() if r.status_code == 200 else {}
        except httpx.HTTPError:
            data = {}
        for a in data.get("upcoming") or []:
            n = _norm_termin(a)
            if n:
                upcoming.append(n)
        nxt = _norm_termin(data.get("next"))
        if nxt and not upcoming:
            upcoming.append(nxt)
    return {"past": past[:5], "upcoming": upcoming[:5]}


def handy_e164(raw: str) -> str:
    d = _digits(raw)
    if not d:
        return ""
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("0"):
        d = "49" + d[1:]
    if not d.startswith("49"):
        d = "49" + d
    return "+" + d


def handy_ok(raw: str) -> bool:
    d = _digits(handy_e164(raw))
    return 11 <= len(d) <= 14


def ist_testname(first: str, last: str, name: str = "") -> bool:
    blob = " ".join(x for x in (_s(first), _s(last), _s(name)) if x).lower()
    if blob in {"anna test", "max mustermann", "erika mustermann"}:
        return True
    last_l = _s(last).lower()
    return last_l in {"test", "demo", "mustermann"}


# Seed-/Fixture-Datensaetze, die in der echten Kartei liegen (CampaignR-Test,
# Demo-Seeds). Vorfall 27.08.2026: Lisa buchte auf "campaignr-test-dr-petsas"
# (firstName "Dr.", lastName "Petsas") — der Termin stand mit Muell-Daten im
# Terminbuch. Solche Saetze nie stillschweigend waehlen, in Listen nach hinten.
_TEST_ID_PREFIXES = ("campaignr-test", "campaignr_", "demo-cr", "demo_cr", "testtrain")
_TITEL_VORNAMEN = {"dr", "dr med", "prof", "prof dr", "prof dr med", "herr", "frau"}


def _nur_titel(first: str) -> bool:
    fn = " ".join(_s(first).lower().replace(".", " ").split())
    return fn in _TITEL_VORNAMEN


def ohne_titel(name: str) -> str:
    """Fuehrende Titel-Tokens ("Dr.", "Prof.", "Herr", …) abwerfen."""
    teile = _s(name).split()
    while teile and teile[0].lower().rstrip(".") in {"dr", "prof", "med", "herr", "frau"}:
        teile = teile[1:]
    return " ".join(teile)


def arzt_sprechname(name: str) -> str:
    """"Dr. Michael Petsas, M.Sc." -> "Doktor Petsas" — fuers SPRECHEN.

    Der Vorname faellt bewusst weg: ElevenLabs spricht englisch klingende
    Vornamen ("Michael") trotz language_code=de gern englisch aus
    (Chef 27.08.2026). Fuer Kalender-Aufloesung den VOLLEN Namen verwenden.
    """
    kern_name = _s(name).split(",")[0].strip()
    if not kern_name:
        return ""
    tokens = [t.lower().rstrip(".") for t in kern_name.replace(".", ". ").split()]
    hat_prof = "prof" in tokens
    hat_dr = "dr" in tokens
    rest = ohne_titel(kern_name).split()
    nachname = rest[-1] if rest else ""
    if not nachname:
        return kern_name
    titel = "Professor" if hat_prof else ("Doktor" if hat_dr else "")
    return f"{titel} {nachname}".strip()


def ist_testakte(p: dict) -> bool:
    pid = _s(p.get("id")).lower()
    if pid.startswith(_TEST_ID_PREFIXES):
        return True
    if _nur_titel(p.get("firstName")):
        return True
    return ist_testname(p.get("firstName"), p.get("lastName"))


def ist_dev_handy(raw: str) -> bool:
    d = _digits(raw)
    if not d:
        return False
    dev = _digits(DEV_PHONE)
    if d == dev:
        return True
    return d == "49" + dev.lstrip("0")


def _cf_create(tenant: dict, first: str, last: str, phone: str, *, birth: str = "", gender: str = "") -> tuple[int, Any]:
    body = {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "firstName": first,
        "lastName": last,
        "mobilePhoneNumber": phone,
    }
    if birth:
        body["birthDate"] = birth
    if gender:
        body["gender"] = gender
    try:
        r = httpx.post(f"{CF_BASE}/masCreatePatient", json=body, timeout=12.0)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return r.status_code, data
    except httpx.HTTPError as e:
        return 0, {"message": str(e)}


def _suche_eindeutig(tenant: dict, first: str, last: str) -> dict[str, Any] | None:
    q = f"{first} {last}".strip()
    if not q:
        return None
    treffer = [
        p for p in (search_patients(tenant, q).get("patients") or [])
        if not ist_testakte(p)
    ]
    if not treffer:
        return None
    if len(treffer) == 1:
        return treffer[0]
    fl, ll = first.lower(), last.lower()
    for p in treffer:
        if _s(p.get("firstName")).lower() == fl and _s(p.get("lastName")).lower() == ll:
            return p
    return None


def akte_anlegen(
    tenant: dict,
    *,
    first: str,
    last: str,
    phone: str,
    birth: str = "",
    gender: str = "",
    name: str = "",
) -> dict[str, Any]:
    """Sucht zuerst. Neue Akte nur mit echtem Namen und Handy. Keine Testnamen."""
    first, last = _s(first), _s(last)
    if _nur_titel(first):
        # "Dr."/"Herr" ist kein Vorname — nie als Akten-Vorname eintragen.
        first = ""
    if not last and name:
        teile = ohne_titel(name).split()
        if len(teile) >= 2:
            first = first or teile[0]
            last = teile[-1]
        elif len(teile) == 1:
            last = teile[0]
    if ist_testname(first, last, name):
        return {
            "ok": False,
            "spoken": "Testnamen lege ich nicht in der echten Kartei an.",
        }
    if not first or not last:
        return {
            "ok": False,
            "spoken": "Vor- und Nachname brauche ich, um die Akte anzulegen.",
        }
    vorhanden = _suche_eindeutig(tenant, first, last)
    if vorhanden:
        karte = karten_patient(vorhanden)
        return {
            "ok": True,
            "created": False,
            "existing": True,
            "patient": karte,
            "spoken": f"Die Akte von {karte['name']} ist schon da.",
        }
    if ist_dev_handy(phone):
        return {
            "ok": False,
            "spoken": (
                "Die Praxis-Testnummer darf ich keiner neuen Akte geben. "
                "Ich brauche die Handynummer des Patienten."
            ),
        }
    e164 = handy_e164(phone)
    if not handy_ok(e164):
        return {
            "ok": False,
            "spoken": "Ohne eine echte Handynummer lege ich niemanden an.",
        }
    karte = {
        "id": "",
        "firstName": first,
        "lastName": last,
        "name": f"{first} {last}".strip(),
        "birthDate": _s(birth),
        "phone": e164,
        "phoneDisplay": format_de_phone(e164),
        "gender": _s(gender),
    }
    if not WRITE_LIVE:
        return {
            "ok": True,
            "created": False,
            "dryRun": True,
            "patient": karte,
            "spoken": (
                f"Die Akte für {first} {last} hätte ich jetzt angelegt — "
                "der Test schreibt die Kartei noch nicht."
            ),
        }
    status, data = _cf_create(tenant, first, last, e164, birth=birth, gender=gender)
    if status == 200 and isinstance(data, dict) and data.get("status") == "success":
        p = data.get("patient") if isinstance(data.get("patient"), dict) else {}
        fertig = karten_patient(p) if p.get("id") else {**karte, **p}
        if not fertig.get("name"):
            fertig["name"] = f"{first} {last}".strip()
        neu = bool(data.get("created"))
        return {
            "ok": True,
            "created": neu,
            "existing": not neu,
            "patient": fertig,
            "spoken": (
                f"Die Akte von {fertig.get('name') or first + ' ' + last} ist angelegt."
                if neu else
                f"Die Akte von {fertig.get('name') or first + ' ' + last} ist schon da."
            ),
        }
    return {
        "ok": False,
        "staged": True,
        "patient": karte,
        "spoken": (
            "Die Daten merke ich mir. Beim ersten Termin trage ich die Akte fest ein. "
            "Wann passt es?"
        ),
    }


def patient_aufloesen(tenant: dict, patient: dict) -> dict[str, Any]:
    """Hängt die Kartei-ID an, wenn der Name WIRKLICH passt. Legt niemanden neu an.

    Vorfall 27.08.2026 14:53: Die Suche nach "Don Johnson" traf über die
    Nachnamen-Variante nur "Nikki Johnson" — der EINE Treffer wurde blind
    übernommen, der Termin landete auf der falschen Akte (falscher Name im
    Kalender, SMS an die falsche Nummer). Ein Treffer zählt nur noch, wenn
    Nachname UND (falls genannt) Vorname übereinstimmen.
    """
    pat = dict(patient or {})
    if _s(pat.get("id")):
        return pat
    q = _s(pat.get("name")) or f"{_s(pat.get('firstName'))} {_s(pat.get('lastName'))}".strip()
    if not q:
        return pat
    found = search_patients(tenant, q)
    # Stille Aufloesung waehlt NIE einen Seed-/Testdatensatz — lieber keine ID
    # (dann fragt Lisa nach Name + Handy und legt sauber an).
    treffer = [p for p in (found.get("patients") or []) if not ist_testakte(p)]
    if not treffer:
        return pat
    qn = q.lower()
    p_first = _s(pat.get("firstName")).lower()
    p_last = _s(pat.get("lastName")).lower()
    if not p_last:
        teile = ohne_titel(q).split()
        if len(teile) >= 2:
            p_first = p_first or teile[0].lower()
            p_last = teile[-1].lower()
        elif len(teile) == 1:
            p_last = teile[0].lower()

    def _passt(p: dict) -> bool:
        k_first = _s(p.get("firstName")).lower()
        k_last = _s(p.get("lastName")).lower()
        if p_last and k_last and k_last != p_last:
            return False
        if p_first and k_first and k_first != p_first:
            return False
        return bool(k_last or f"{k_first} {k_last}".strip() == qn)

    passende = [p for p in treffer if _passt(p)]
    gewaehlt = None
    if len(passende) == 1:
        gewaehlt = passende[0]
    else:
        for p in passende:
            kn = f"{_s(p.get('firstName'))} {_s(p.get('lastName'))}".strip().lower()
            if kn == qn:
                gewaehlt = p
                break
    if not gewaehlt:
        if treffer and not passende:
            print(f"patients: Treffer verworfen (Name passt nicht) fuer {q!r}", flush=True)
        return pat
    karte = karten_patient(gewaehlt)
    for k in ("past", "upcoming", "devPhone", "devPhoneRaw"):
        if pat.get(k) and not karte.get(k):
            karte[k] = pat[k]
    return karte


def karten_patient(p: dict) -> dict[str, Any]:
    phone = _phone_of(p)
    return {
        "id": _s(p.get("id")),
        "firstName": _s(p.get("firstName")),
        "lastName": _s(p.get("lastName")),
        "name": f"{_s(p.get('firstName'))} {_s(p.get('lastName'))}".strip(),
        "gender": _s(p.get("gender")),
        "birthDate": _s(p.get("birthDate")),
        "phone": phone,
        "phoneDisplay": format_de_phone(phone) if phone else "",
        "devPhone": format_de_phone(DEV_PHONE),
        "devPhoneRaw": DEV_PHONE,
        "test": ist_testakte(p),
    }
