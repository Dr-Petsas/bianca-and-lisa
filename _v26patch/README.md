# V4-Quellen (20.09.2026)

Diese Dateien sind der Mund von Produktionsstand V4: V2.6 plus die
Patches, die im laufenden Container `telefonki-bianca-v26-1` lagen und
per `docker commit` zu `telefonki:produktionsstand-v4-20260920` wurden.

| Datei | Wohin im Container |
| --- | --- |
| `flow.py` | `/app/bianca/flow.py` |
| `gehirn.py` | `/app/bianca/gehirn.py` |
| `verwalten.py` | `/app/bianca/verwalten.py` |
| `slots.py` | `/app/kern/slots.py` |
| `praxisregeln.py` | `/app/kern/praxisregeln.py` |

Das vollständige Image und die Server-`.env` liegen **nicht** hier,
sondern unter `_snapshot-produktionsstand-v4/` (gitignoriert) und
`/home/cursor/telefonki-backups/produktionsstand-v4-20260920/`.

Anleitung: `docs/PRODUKTIONSSTAND-V4.md`.
