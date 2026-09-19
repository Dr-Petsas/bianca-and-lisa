"""Scannt Mitschnitte nach Anliegen-Wortlauten (read-only).

Liest ``.data/anrufe/bianca/*/anruf.json`` lokal oder --root und schreibt
eine Haeufigkeitsliste nach ``.data/anliegen_scan.json``. Nie Kalender,
nie Schreiben ins Live-System.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bianca.controller.anliegen import deute  # noqa: E402


def _texte(manifest: dict) -> list[str]:
    out: list[str] = []
    for z in manifest.get("zuege") or []:
        if not isinstance(z, dict):
            continue
        for k in ("anrufer", "text", "gesagt", "transcript"):
            t = z.get(k)
            if isinstance(t, str) and t.strip():
                out.append(t.strip())
                break
    return out


def scan(root: Path) -> dict:
    zaehl: Counter[str] = Counter()
    belege: dict[str, list[str]] = {}
    dateien = 0
    for pfad in sorted(root.glob("*/anruf.json")):
        dateien += 1
        try:
            data = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        texte = _texte(data if isinstance(data, dict) else {})
        if not texte:
            continue
        intent, slots = deute(texte[0])
        key = (intent.value if intent else "sonst") + "|" + ",".join(
            f"{k}={v}" for k, v in slots.items()
        )
        zaehl[key] += 1
        belege.setdefault(key, [])
        if len(belege[key]) < 8:
            belege[key].append(texte[0][:180])
    return {
        "dateien": dateien,
        "anliegen": [
            {"key": k, "n": n, "belege": belege.get(k, [])}
            for k, n in zaehl.most_common()
        ],
    }


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".data" / "anrufe" / "bianca"
    report = scan(root)
    ziel = ROOT / ".data" / "anliegen_scan.json"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['dateien']} Dateien in {root}")
    for zeile in report["anliegen"][:20]:
        print(f"  {zeile['n']:4d}  {zeile['key']}")
        for b in zeile["belege"][:2]:
            print(f"        {b}")


if __name__ == "__main__":
    main()
