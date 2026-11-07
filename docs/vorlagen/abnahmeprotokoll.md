# Abnahmeprotokoll Geodaten-Import-Pipeline

Vorlage. Grundlage: Leistungsbeschreibung Abschnitt 8 (Liefergegenstände) und 11 (Abnahme).

| | |
|---|---|
| Auftraggeber | |
| Auftragnehmer | |
| Vergabenummer / Bestellnummer | |
| Datum der Abnahme | |
| Teilnehmende | |
| Stand des Repositorys (Commit) | |

## Liefergegenstände

| Nr. | Liefergegenstand | Wo | geprüft | Anmerkung |
|---|---|---|---|---|
| 1 | Quellcode, dokumentiert, in Git, unter der vereinbarten Open-Source-Lizenz | Repository | ☐ | |
| 2 | Docker-Setup: Image, Compose mit PostgreSQL/PostGIS, Konfiguration über Umgebungsvariablen | `Dockerfile`, `docker-compose.yml`, `.env.beispiel` | ☐ | |
| 3 | Konfigurationsmechanismus für neue WFS-/CSV-Quellen ohne Codeänderung | `config/quellen.yaml`, `--probelauf` | ☐ | |
| 4 | Import-Bericht je Lauf (JSON und Textzusammenfassung) | `berichte/` | ☐ | |
| 5 | Dokumentation: Installation, Betrieb, Entwicklung (neue Quellen), Datenmodell | `README.md`, `docs/` | ☐ | |
| 6 | Lizenzübersicht der Drittkomponenten | `README.md`, `sbom.cdx.json` | ☐ | |
| 7 | Übergabesitzung durchgeführt | | ☐ | |

## End-to-End-Testlauf

| | |
|---|---|
| Lauf-ID | |
| WFS-Quelle(n) | |
| CSV-Quelle(n) | |
| Ergebnis je Quelle (neu / geändert / gelöscht / unverändert) | |
| Bericht als JSON und Text erzeugt und korrekt | ☐ |
| Prüfkette `./pruefen.sh` ohne Befund | ☐ |
| Anlagen | Laufbericht `<lauf>.json`, `<lauf>.txt` |

## Ergebnis

☐ Abgenommen  ☐ Abgenommen mit folgenden Mängeln, Nachbesserung bis: ____________  ☐ Nicht abgenommen

Mängel:

Ort, Datum, Unterschrift Auftraggeber: ______________________

Ort, Datum, Unterschrift Auftragnehmer: ______________________
