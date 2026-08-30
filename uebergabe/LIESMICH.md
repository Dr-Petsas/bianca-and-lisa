# Übergabe-Ordner

Grok liest **diesen Ordner**, wenn du im Chat sagst:

- **Übergabe**
- **letzter Teststudio-Auftrag**
- **arbeite den Auftrag ab**

## Dateien

| Datei | Wer schreibt | Was drin ist |
|---|---|---|
| `liste.md` | Teststudio | **eine** Liste aller Vorfälle, klar getrennt |
| `aktuell.md` | Teststudio nach Einzellauf oder Selbst-Anruf | letzter Lauf |
| `vorschlag.md` | **du** (Popup oder diese Datei) | Was Bianca anders machen soll |
| `archiv/` | Teststudio | Rohdateien je Gespräch (Quelle für die eine Liste) |

Im Verlauf eine Bianca-Antwort mit **Stimmt nicht** markieren und kurz schreiben, was falsch war. Am Ende das Popup für den Gesamteindruck. **Selbst anrufen** = du sprichst (oder tippst), kein Caller-Audio.

Clara, MAS-2, Lena-Voice und pickadoc-live-base werden nicht angefasst.

Seite im Studio: `/studio/uebergabe` (oder `http://127.0.0.1:8097/uebergabe`).
Eine Übertragungs-Liste, alle Gespräche nacheinander, getrennt durch eine Linie.
**In Zwischenablage kopieren** und ab und zu in den Cursor-Chat einfügen — kein Automatismus.

Nach dem Speichern im Popup geht derselbe Text in diesen Ordner. `vorschlag.md` kannst du auch direkt hier schreiben.
