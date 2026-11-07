# Film „Was bei jedem Lauf passiert“

Kurzer Erklärfilm (rund 74 s, 1920 × 1080, 30 fps, ohne Ton) auf fünf Blättern im Stil eines
Zeichenblatts. Er zeigt, was die Pipeline bei jedem Lauf tut, und belegt es mit Zahlen und
Berichtszeilen aus echten Läufen. Gebaut mit [Manim Community](https://www.manim.community/) 0.22.1.

- `film.mp4`: der Film (H.264, yuv420p, `+faststart`)
- `standbild.png`: Endstand von Blatt 4 (Belege), geeignet als Vorschaubild
- `film.gif`: Titel und Karte (Sekunde 1,5 bis 9,1 des Films), 960 px breit, 12 Bilder je Sekunde
- `film.py`: der Film als Programm; `geometrie.py`: Vorstufe für die Kartenlinien

## Was die Blätter zeigen

| Blatt | Inhalt |
|---|---|
| 1 Quellen und Ziel | Gemeinde- und Kreisgrenzen Brandenburgs, danach die drei Anbieter (WFS der LGB, Statistischer Bericht des Amts für Statistik als XLSX, INKAR-Gesamtdatei als ZIP), die Pipeline und die Bestandstabellen von MOSIDI |
| 2 Vier Schritte je Quelle | Abrufen, Prüfen (Quellen-Wächter), Vergleichen (fachlicher Schlüssel gegen `pipeline_meta.bestand`), Abgleichen in einer Transaktion je Quelle; Zähler von `gemeinden_lgb` im Erst- und Folgelauf |
| 3 Was den Bestand schützt | Löschsperre, Rückgang-Schutz, Raumdaten mit `loeschen: false`, Ausfall einer Quelle; dazu der Bericht eines Laufs mit absichtlich unerreichbarer Quelle |
| 4 Belege aus echten Läufen | 413 / 413 Gemeinden (Compose-Setup von MOSIDI, Prüfkonfiguration Brandenburg), 33.547.606 INKAR-Werte bundesweit (10.978 Gemeinden, Lieferkonfiguration, Lauf 20261107T044222Z) mit Wertabgleich 0 / 0 / 0, Datenbanktests 70 von 70 auf PostgreSQL 16.15 und 18.6, 424 Tests in `pruefen.sh` |
| 5 Bericht und Protokoll | Laufbericht des Erstlaufs im Compose-Setup (Prüfkonfiguration Brandenburg, daher 62929 INKAR-Werte statt der 33.547.606 des bundesweiten Laufs; ohne Hinweiszeilen) und die Tabellen von `pipeline_meta` |

## Woher jede Zahl kommt

`film.py` liest alle Zahlen und Berichtszeilen beim Rendern aus den Belegdateien in
`beispielberichte/` und bricht ab, wenn eine Datei etwas anderes sagt als erwartet. Die gelesenen
Werte schreibt es nach `zahlen.json` im Datenordner.

| Im Film | Datei |
|---|---|
| Gemeinden: Erstlauf neu 413, Folgelauf unverändert 413 (neu, geändert, gelöscht je 0); 18 Kreise | `beispielberichte/pruefstand-2026-11-07-e51/mosidi-compose/20261107T043632Z.json` und `20261107T043901Z.json` |
| Laufbericht auf Blatt 5 (145,36 s) | `beispielberichte/pruefstand-2026-11-07-e51/mosidi-compose/20261107T043632Z.txt` |
| Bericht mit ausgefallener Quelle auf Blatt 3 | `beispielberichte/20261030T074610Z.txt` und `.json` (Prototyp, 30.10.2026) |
| 33.547.606 INKAR-Werte, Lauf 20261107T044222Z | `beispielberichte/pruefstand-2026-11-07-e51/quellen/20261107T044222Z.json` (`inkar_gemeinden`, neu) und `.txt` (Kopfzeile) |
| 10.978 Gemeinden (bundesweit) | `beispielberichte/pruefstand-2026-11-07-e51/quellen/datenbank-auszug.txt` (Zeile INKAR, Spalte `kennziffern`) |
| fehlend 0, überzählig 0, abweichend 0 | `beispielberichte/pruefstand-2026-11-07-e51/wertabgleich/ergebnis-vollumfang.txt` |
| 70 von 70 auf PostgreSQL 16.15 und 18.6 | `beispielberichte/pruefstand-2026-11-07-e51/datenbanktests.log` |
| 424 Tests | `beispielberichte/pruefstand-2026-11-07-e51/pruefen.log` |

Die übrigen Aussagen stehen in `README.md` (Rückgang-Schutz: 0 Objekte oder mehr als die Hälfte
weniger; konfigurierte Felder), `config/quellen.yaml` (`loeschen: false`, Schlüssel `nationalco`,
Tabellennamen, Dateiname des Statistischen Berichts), `docs/betrieb.md` (Löschsperre bei Objekten
ohne ID oder Geometrie oder weniger als gemeldet) und `sql/pipeline_meta.sql` (Tabellen von
`pipeline_meta`, „Steuerung und Protokoll, nie Fachdaten“).

## Was schematisch ist

Im Film als „schematisch“ gekennzeichnet: der Aufbau auf Blatt 1 (Symbole für Dienst, Tabelle,
ZIP, Pipeline und Datenbank), der Ablauf auf Blatt 2 und die Piktogramme auf Blatt 3. Die
Gemeindefläche auf Blatt 3 ist eine echte Gemeinde aus den Daten der LGB.

## Namensnennung

- Gemeinde- und Kreisgrenzen: © GeoBasis-DE/LGB, dl-de/by-2-0
- Statistischer Bericht A I 4 / A V 2 (`SB_A01-04_00_2025j01_BB.xlsx`): Amt für Statistik Berlin-Brandenburg, CC BY 3.0 DE
- INKAR: © BBSR Bonn 2025, dl-de/by-2-0

## Neu bauen

Die Geodaten liegen nicht im Repo. `geometrie.py` erwartet in einem Datenordner
`gemeinden.geojson` (413 Gemeinden) und `kreise.geojson` (18 Kreise) in EPSG:25833, abgerufen vom
WFS der LGB wie die Quellen `gemeinden_lgb` und `kreise_lgb` in `config/pruefkonfiguration.yaml`
(Objektarten, Felder und Dienst stehen dort). Voreingestellt ist `cache/filme/` (von Git
ausgeschlossen), ein anderer Ordner über `FILM_DATEN`.

Voraussetzungen: [uv](https://docs.astral.sh/uv/), ffmpeg, die Systembibliotheken von Manim (Cairo,
Pango) und die Schriften Fira Sans, Fira Sans Condensed und Hack.

Aus der Repo-Wurzel:

```sh
export FILM_DATEN=cache/filme
uv run --no-project --with shapely==2.2.0 python docs/filme/manim/geometrie.py
uv run --no-project --with manim==0.22.1 manim -qh --frame_rate 30 --disable_caching \
    --media_dir cache/filme/media docs/filme/manim/film.py Lauf
ffmpeg -i cache/filme/media/videos/film/1080p30/Lauf.mp4 -c:v libx264 -crf 20 -preset slow \
    -pix_fmt yuv420p -movflags +faststart -an docs/filme/manim/film.mp4
# Standbild: Endstand von Blatt 4
uv run --no-project --with manim==0.22.1 manim -qh -s --disable_caching \
    --media_dir cache/filme/media docs/filme/manim/film.py Standbild
cp cache/filme/media/images/film/Standbild_ManimCE_v0.22.1.png docs/filme/manim/standbild.png
# GIF: Titel und Karte
ffmpeg -ss 1.5 -t 7.6 -i docs/filme/manim/film.mp4 -vf "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" docs/filme/manim/film.gif
```

Ohne `--frame_rate 30` rendert `-qh` mit 60 fps. Die Belegdateien in `beispielberichte/` werden nur
gelesen.
