# Belegfilme

Drei kurze Filme zeigen den Erstlauf der Pipeline im MOSIDI-Compose vom 07.11.2026 (Bericht `20261107T043632Z`, 145,36 s), den Folgelauf direkt danach (`20261107T043901Z`, 141,8 s, alles unverändert) und den Fehlerfall aus dem Prototyp vom 30.10.2026. Ansehen im Browser: https://andremadstop.github.io/geodaten-import-pipeline/

| Film | Länge | Werkzeug | Ordner |
|---|---|---|---|
| Der Campus wächst aus den Daten | 39 s | Blender 5.1 (bpy) | [`blender/`](blender/) |
| Der Lauf im Terminal | 39 s | pycairo, ffmpeg | [`terminal/`](terminal/) |
| Was bei jedem Lauf passiert | 74 s | Manim Community 0.22 | [`manim/`](manim/) |

Jede Zahl und jede Berichtszeile in den Filmen stammt aus den Laufberichten unter `beispielberichte/`; was nur schematisch ist (etwa die Verteilung der Laufzeit auf die vier Schritte oder Gebäudehöhen ohne Geschosszahl), steht im Bild und in der README des jeweiligen Films. Die Skripte bauen die Filme neu und gleichen die Zahlen dabei gegen die Berichte ab.

Nicht im Repository liegen die Geodaten, aus denen die Karte entsteht (Gebäude, Gemeinden, Kreise der LGB, Statistischer Bericht des Amts für Statistik): Quelldaten werden nicht mit dem Code veröffentlicht (Antwort 69 der TH). Das Skript `blender/holen.py` lädt sie bei Bedarf von denselben Diensten wie die Pipeline.

Die Skripte sind Einmal-Werkzeuge für die Filme, kein Teil der Pipeline und nicht im Image; in `pyproject.toml` sind sie deshalb von Stilregeln ausgenommen.

Geobasisdaten © GeoBasis-DE/LGB, dl-de/by-2-0 · Statistik: Amt für Statistik Berlin-Brandenburg, CC BY 3.0 DE · INKAR: © BBSR Bonn 2025, dl-de/by-2-0 · Kreise im Fehlerfall: © BKG (2026), dl-de/by-2-0
